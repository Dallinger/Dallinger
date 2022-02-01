import logging
from datetime import datetime
from operator import attrgetter
from rq import Queue
from rq import get_current_job
from dallinger import db
from dallinger import information
from dallinger import models
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
        participant = models.Participant.query.filter_by(id=participant_id).all()[0]
    else:
        raise ValueError(
            "Error: worker_function needs either an assignment_id or a "
            "participant_id, they cannot both be None"
        )

    participant_id = participant.id

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

    min_real_bonus = 0.01

    def __call__(self):
        if not self.is_eligible(self.participant):
            return

        self.update_participant_end_time()
        self.participant.status = "submitted"
        self.commit()

        self.approve_assignment()

        if not self.data_is_ok():
            self.fail_data_check()
            self.experiment.recruiter.recruit(n=1)

            return

        # If their data is ok, pay them a bonus.
        # Note that the bonus is paid before the attention check.
        bonus = self.experiment.bonus(participant=self.participant)
        self.participant.bonus = bonus
        if bonus >= self.min_real_bonus:
            self.award_bonus(bonus)
        else:
            self.log("Bonus = {}: NOT paying bonus".format(bonus))

        if self.did_attend():
            self.approve_submission()
            self.experiment.recruit()
        else:
            self.fail_submission()
            self.experiment.recruiter.recruit(n=1)

    def is_eligible(self, particpant):
        eligible_statuses = ("working", "overrecruited", "returned", "abandoned")
        return particpant.status in eligible_statuses

    def data_is_ok(self):
        """Run a check on our participant's data"""
        return self.experiment.data_check(participant=self.participant)

    def did_attend(self):
        return self.experiment.attention_check(participant=self.participant)

    def approve_assignment(self):
        self.participant.recruiter.approve_hit(self.assignment_id)
        self.participant.base_pay = self.config.get("base_payment")

    def award_bonus(self, bonus):
        self.log("Bonus = {}: paying bonus".format(bonus))
        self.participant.recruiter.reward_bonus(
            self.participant,
            bonus,
            self.experiment.bonus_reason(),
        )

    def fail_data_check(self):
        self.participant.status = "bad_data"
        self.experiment.data_check_failed(participant=self.participant)
        self.commit()

    def approve_submission(self):
        self.log("All checks passed.")
        self.participant.status = "approved"
        self.experiment.submission_successful(participant=self.participant)
        self.commit()

    def fail_submission(self):
        self.log("Attention check failed.")
        self.participant.status = "did_not_attend"
        self.experiment.attention_check_failed(participant=self.participant)
        self.commit()


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
