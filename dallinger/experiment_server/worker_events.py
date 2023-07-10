import logging
from datetime import datetime
from operator import attrgetter

from rq import Queue, get_current_job

from dallinger import db, information, models
from dallinger.config import get_config

logger = logging.getLogger(__name__)


def _config():
    config = get_config()
    if not config.ready:
        config.load()

    return config


def _loaded_experiment(args):
    from dallinger import experiment

    klass = experiment.load()
    return klass(args)


def _get_queue(name="default"):
    # Connect to Redis Queue
    return Queue(name, connection=db.redis_conn)


@db.scoped_session_decorator
def worker_function(
    event_type, assignment_id, participant_id, node_id=None, details=None
):
    """Process the notification."""
    _config()
    q = _get_queue()
    try:
        db.logger.debug(
            "rq: worker_function working on job id: %s", get_current_job().id
        )
        db.logger.debug(
            "rq: Received Queue Length: %d (%s)", len(q), ", ".join(q.job_ids)
        )
    except AttributeError:
        db.logger.debug("Debug worker_function called synchronously")

    exp = _loaded_experiment(db.session)
    key = "-----"

    exp.log(
        "Received an {} notification for assignment {}, participant {}".format(
            event_type, assignment_id, participant_id
        ),
        key,
    )

    if event_type == "TrackingEvent":
        node = None
        if node_id:
            node = models.Node.query.get(node_id)
        if not node:
            participant = None
            if participant_id:
                # Lookup assignment_id to create notifications
                participant = models.Participant.query.get(participant_id)
            elif assignment_id:
                participants = models.Participant.query.filter_by(
                    assignment_id=assignment_id
                ).all()
                # if there are one or more participants select the most recent
                if participants:
                    participant = max(participants, key=attrgetter("creation_time"))
                    participant_id = participant.id
            if not participant:
                exp.log(
                    "Warning: No participant associated with this "
                    "TrackingEvent notification.",
                    key,
                )
                return
            nodes = participant.nodes()
            if not nodes:
                exp.log(
                    "Warning: No node associated with this "
                    "TrackingEvent notification.",
                    key,
                )
                return
            node = max(nodes, key=attrgetter("creation_time"))

        if not details:
            details = {}
        info = information.TrackingEvent(origin=node, details=details)
        db.session.add(info)
        db.session.commit()
        return

    runner_cls = WorkerEvent.for_name(event_type)
    if not runner_cls:
        exp.log("Event type {} is not supported... ignoring.".format(event_type))
        return

    if assignment_id is not None:
        # save the notification to the notification table
        notif = models.Notification(assignment_id=assignment_id, event_type=event_type)
        db.session.add(notif)
        db.session.commit()

        # try to identify the participant
        participants = models.Participant.query.filter_by(
            assignment_id=assignment_id
        ).all()

        # if there are one or more participants select the most recent
        if participants:
            participant = max(participants, key=attrgetter("creation_time"))

        # if there are none print an error
        else:
            exp.log(
                "Warning: No participants associated with this "
                "assignment_id. Notification will not be processed.",
                key,
            )
            return None

    elif participant_id is not None:
        # XXX Why is this not a Participant.get()?
        participant = models.Participant.query.filter_by(id=participant_id).all()[0]
    else:
        raise ValueError(
            "Error: worker_function needs either an assignment_id or a "
            "participant_id, they cannot both be None"
        )

    runner = runner_cls(
        participant, assignment_id, exp, db.session, _config(), datetime.now()
    )
    runner()
    db.session.commit()


class WorkerEvent(object):
    key = "-----"

    supported_event_types = (
        "AssignmentAccepted",
        "AssignmentAbandoned",
        "AssignmentReassigned",
        "AssignmentReturned",
        "AssignmentSubmitted",
        "BotAssignmentSubmitted",
        "BotAssignmentRejected",
        "NotificationMissing",
    )

    @classmethod
    def for_name(cls, name):
        if name in cls.supported_event_types:
            return globals()[name]

    def __init__(self, participant, assignment_id, experiment, session, config, now):
        self.participant = participant
        self.assignment_id = assignment_id
        self.experiment = experiment
        self.session = session
        self.config = config
        self.now = now

    @property
    def data(self):
        return {
            "event_type": self.__class__.__name__,
            "participant_id": self.participant.id,
            "assignment_id": self.assignment_id,
            "timestamp": self.now,
        }

    def commit(self):
        self.session.commit()

    def log(self, message):
        self.experiment.log(message, self.key)

    def update_participant_end_time(self):
        self.participant.end_time = self.now


class AssignmentAccepted(WorkerEvent):
    def __call__(self):
        pass


class AssignmentAbandoned(WorkerEvent):
    def __call__(self):
        if self.participant.status == "working":
            self.update_participant_end_time()
            self.participant.status = "abandoned"
            self.experiment.assignment_abandoned(participant=self.participant)


class AssignmentReturned(WorkerEvent):
    def __call__(self):
        if self.participant.status == "working":
            self.update_participant_end_time()
            self.participant.status = "returned"
            self.experiment.assignment_returned(participant=self.participant)


class AssignmentSubmitted(WorkerEvent):
    def __call__(self):
        self.experiment.on_assignment_submitted_to_recruiter(
            participant=self.participant, event=self.data
        )


class BotAssignmentSubmitted(WorkerEvent):
    def __call__(self):
        self.log("Received bot submission.")
        self.update_participant_end_time()

        # No checks for bot submission
        self.participant.recruiter.approve_hit(self.assignment_id)
        self.participant.status = "approved"
        self.experiment.submission_successful(participant=self.participant)
        self.commit()
        self.experiment.recruit()


class BotAssignmentRejected(WorkerEvent):
    def __call__(self):
        self.log("Received rejected bot submission.")
        self.update_participant_end_time()
        self.participant.status = "rejected"
        self.commit()

        # We go back to recruiting immediately
        self.experiment.recruit()


class NotificationMissing(WorkerEvent):
    def __call__(self):
        if self.participant.status == "working":
            self.update_participant_end_time()
            self.participant.status = "missing_notification"


class AssignmentReassigned(WorkerEvent):
    def __call__(self):
        self.update_participant_end_time()
        self.participant.status = "replaced"
        self.experiment.assignment_reassigned(participant=self.participant)
