

class WorkerEvent(object):

    key = '-----'

    supported_event_types = (
        'AssignmentAccepted',
        'AssignmentAbandoned',
        'AssignmentReassigned',
        'AssignmentReturned',
        'AssignmentSubmitted',
        'BotAssignmentSubmitted',
        'BotAssignmentRejected',
        'NotificationMissing',
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


class AssignmentAccepted(WorkerEvent):

    def __call__(self):
        pass


class AssignmentAbandoned(WorkerEvent):

    def __call__(self):
        if self.participant.status == "working":
            self.participant.end_time = self.now
            self.participant.status = "abandoned"
            self.experiment.assignment_abandoned(participant=self.participant)


class AssignmentReturned(WorkerEvent):

    def __call__(self):
        if self.participant.status == "working":
            self.participant.end_time = self.now
            self.participant.status = "returned"
            self.experiment.assignment_returned(participant=self.participant)


class AssignmentSubmitted(WorkerEvent):

    def __call__(self):
        if self.participant.status not in ["working", "returned", "abandoned"]:
            return

        self.participant.end_time = self.now
        self.participant.status = "submitted"
        self.session.commit()

        # Approve the assignment.
        self.experiment.recruiter().approve_hit(self.assignment_id)
        self.participant.base_pay = self.config.get('base_payment')

        # Check that the participant's data is okay.
        worked = self.experiment.data_check(participant=self.participant)

        # If it isn't, fail their nodes and recruit a replacement.
        if not worked:
            self.participant.status = "bad_data"
            self.experiment.data_check_failed(participant=self.participant)
            self.session.commit()
            self.experiment.recruiter().recruit_participants(n=1)
        else:
            # If their data is ok, pay them a bonus.
            # Note that the bonus is paid before the attention check.
            bonus = self.experiment.bonus(participant=self.participant)
            self.participant.bonus = bonus
            if bonus >= 0.01:
                self.experiment.log("Bonus = {}: paying bonus".format(bonus), self.key)
                self.experiment.recruiter().reward_bonus(
                    self.assignment_id,
                    bonus,
                    self.experiment.bonus_reason())
            else:
                self.experiment.log("Bonus = {}: NOT paying bonus".format(bonus), self.key)

            # Perform an attention check.
            attended = self.experiment.attention_check(participant=self.participant)

            # If they fail the attention check, fail nodes and replace.
            if not attended:
                self.experiment.log("Attention check failed.", self.key)
                self.participant.status = "did_not_attend"
                self.experiment.attention_check_failed(participant=self.participant)
                self.session.commit()
                self.experiment.recruiter().recruit_participants(n=1)
            else:
                # All good. Possibly recruit more participants.
                self.experiment.log("All checks passed.", self.key)
                self.participant.status = "approved"
                self.experiment.submission_successful(participant=self.participant)
                self.session.commit()
                self.experiment.recruit()


class BotAssignmentSubmitted(WorkerEvent):

    def __call__(self):
        self.experiment.log("Received bot submission.", self.key)
        self.participant.end_time = self.now

        # No checks for bot submission
        self.experiment.recruiter().approve_hit(self.assignment_id)
        self.participant.status = "approved"
        self.experiment.submission_successful(participant=self.participant)
        self.session.commit()
        self.experiment.recruit()


class BotAssignmentRejected(WorkerEvent):

    def __call__(self):
        self.experiment.log("Received rejected bot submission.", self.key)
        self.participant.end_time = self.now
        self.participant.status = "rejected"
        self.session.commit()

        # We go back to recruiting immediately
        self.experiment.recruit()


class NotificationMissing(WorkerEvent):

    def __call__(self):
        if self.participant.status == "working":
            self.participant.end_time = self.now
            self.participant.status = "missing_notification"


class AssignmentReassigned(WorkerEvent):

    def __call__(self):
        self.participant.end_time = self.now
        self.participant.status = "replaced"
        self.experiment.assignment_reassigned(participant=self.participant)
