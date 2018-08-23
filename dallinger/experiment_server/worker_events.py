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

    def commit(self):
        self.session.commit()

    def log(self, message):
        self.experiment.log(message, self.key)

    def update_particant_end_time(self):
        self.participant.end_time = self.now


class AssignmentAccepted(WorkerEvent):

    def __call__(self):
        pass


class AssignmentAbandoned(WorkerEvent):

    def __call__(self):
        if self.participant.status == "working":
            self.update_particant_end_time()
            self.participant.status = "abandoned"
            self.experiment.assignment_abandoned(participant=self.participant)


class AssignmentReturned(WorkerEvent):

    def __call__(self):
        if self.participant.status == "working":
            self.update_particant_end_time()
            self.participant.status = "returned"
            self.experiment.assignment_returned(participant=self.participant)


class AssignmentSubmitted(WorkerEvent):

    min_real_bonus = 0.01

    def __call__(self):
        if not self.is_eligible(self.participant):
            return

        self.update_particant_end_time()
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
        self.participant.base_pay = self.config.get('base_payment')

    def award_bonus(self, bonus):
        self.log("Bonus = {}: paying bonus".format(bonus))
        self.participant.recruiter.reward_bonus(
            self.assignment_id,
            bonus,
            self.experiment.bonus_reason())

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
        self.update_particant_end_time()

        # No checks for bot submission
        self.participant.recruiter.approve_hit(self.assignment_id)
        self.participant.status = "approved"
        self.experiment.submission_successful(participant=self.participant)
        self.commit()
        self.experiment.recruit()


class BotAssignmentRejected(WorkerEvent):

    def __call__(self):
        self.log("Received rejected bot submission.")
        self.update_particant_end_time()
        self.participant.status = "rejected"
        self.commit()

        # We go back to recruiting immediately
        self.experiment.recruit()


class NotificationMissing(WorkerEvent):

    def __call__(self):
        if self.participant.status == "working":
            self.update_particant_end_time()
            self.participant.status = "missing_notification"


class AssignmentReassigned(WorkerEvent):

    def __call__(self):
        self.update_particant_end_time()
        self.participant.status = "replaced"
        self.experiment.assignment_reassigned(participant=self.participant)
