import logging
from datetime import datetime

from rq import get_current_job
from sqlalchemy.exc import DataError, InternalError

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


LOG_EVENT_TYPES = frozenset(
    (
        "AssignmentAccepted",
        "AssignmentAbandoned",
        "AssignmentReassigned",
        "AssignmentReturned",
        "RecruiterSubmissionComplete",
        "BotRecruiterSubmissionComplete",
        "BotAssignmentRejected",
        "NotificationMissing",
    )
)


@db.scoped_session_decorator
def worker_function(
    event_type,
    assignment_id,
    participant_id,
    node_id=None,
    receive_timestamp=None,
    details=None,
    queue_name="default",
):
    """Process the notification."""
    config = _config()
    session = db.session
    q = db.get_queue(name=queue_name)
    try:
        db.logger.debug(
            "rq: worker_function working on job id: %s", get_current_job().id
        )
        db.logger.debug(
            "rq: Received Queue Length: %d (%s)", len(q), ", ".join(q.job_ids)
        )
    except AttributeError:
        db.logger.debug(
            "Debug worker_function called synchronously or queue not specified"
        )

    exp = _loaded_experiment(session)
    key = "-----"

    # Logging every event is a bit verbose for experiment driven events
    if event_type in LOG_EVENT_TYPES:
        exp.log(
            "Received an {} notification for assignment {}, participant {}".format(
                event_type, assignment_id, participant_id
            ),
            key,
        )

    receive_time = (
        datetime.fromtimestamp(receive_timestamp)
        if receive_timestamp
        else datetime.now()
    )
    node = None
    if node_id:
        try:
            node = session.query(models.Node).get(node_id)
        except DataError:
            pass

    participant = None
    if participant_id is not None:
        try:
            participant = session.query(models.Participant).get(participant_id)
        except DataError:
            pass

    if assignment_id and not participant:
        try:
            participant = (
                session.query(models.Participant)
                .filter_by(assignment_id=assignment_id)
                .order_by(models.Participant.creation_time.desc())
                .first()
            )
        except (DataError, InternalError):
            participant = None

    if event_type == "TrackingEvent":
        record_tracking_event(participant, node, exp, session, details)
        return

    runner_cls = WorkerEvent.for_name(event_type)
    if not runner_cls:
        exp.log("Event type {} is not supported... ignoring.".format(event_type))
        return

    if assignment_id is not None:
        # save the notification to the notification table
        notif = models.Notification(assignment_id=assignment_id, event_type=event_type)
        session.add(notif)
        session.commit()

        if not participant:
            exp.log(
                "Warning: No participants associated with this "
                "assignment_id. Notification will not be processed.",
                key,
            )
            return
    elif not participant and not node:
        raise ValueError(
            "Error: worker_function needs either an assignment_id or a "
            "participant_id, they cannot both be None"
        )

    # Distinguish between the time of the event and the time it was pulled off
    # the queue for processing
    runner = runner_cls(
        participant,
        assignment_id,
        exp,
        session,
        config=config,
        now=datetime.now(),
        receive_time=receive_time,
        node=node,
        details=details,
    )
    runner()
    session.commit()


def record_tracking_event(participant, node, exp, session, details):
    """Tracking events aren't necessarily about participants, so
    we don't use a WorkerEvent to handle them.
    """
    key = "-----"
    details = details or {}

    if not node and not participant:
        exp.log(
            "Warning: No participant associated with this TrackingEvent notification.",
            key,
        )
        return

    if participant:
        node = (
            session.query(models.Node)
            .filter_by(participant_id=participant.id)
            .order_by(models.Node.creation_time.desc())
            .first()
        )
        if not node:
            exp.log(
                "Warning: No node associated with this TrackingEvent notification.",
                key,
            )
            return

    info = information.TrackingEvent(origin=node, details=details)
    session.add(info)
    session.commit()


class _WorkerMeta(type):
    _WORKER_EVENTS = {}

    def __init__(cls, name, bases, dct):
        """Register subclasses with a name registry"""
        cls._WORKER_EVENTS[name] = cls

    def for_name(cls, name):
        return cls._WORKER_EVENTS.get(name)


class WorkerEvent(metaclass=_WorkerMeta):
    key = "-----"

    def __init__(
        self,
        participant=None,
        assignment_id=None,
        experiment=None,
        session=None,
        config=None,
        now=None,
        receive_time=None,
        node=None,
        details=None,
    ):
        self.participant = participant
        self.assignment_id = assignment_id
        self.experiment = experiment
        self.session = session
        self.config = config
        self.now = now
        self.receive_time = receive_time
        self.node = node
        self.details = details

    @property
    def data(self):
        return {
            "event_type": self.__class__.__name__,
            "participant_id": self.participant.id,
            "assignment_id": self.assignment_id,
            "timestamp": self.now,
            "receive_time": self.receive_time,
            "details": self.details,
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


class RecruiterSubmissionComplete(WorkerEvent):
    def __call__(self):
        self.experiment.on_recruiter_submission_complete(
            participant=self.participant, event=self.data
        )


class BotRecruiterSubmissionComplete(WorkerEvent):
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


class WebSocketMessage(WorkerEvent):
    def __call__(self):
        self.experiment.receive_message(
            self.details["message"],
            channel_name=self.details["channel_name"],
            participant=self.participant,
            node=self.node,
            receive_time=self.receive_time,
        )
