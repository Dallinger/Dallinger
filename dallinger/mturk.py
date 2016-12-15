import datetime
import logging

from boto.mturk.connection import MTurkConnection
from boto.mturk.connection import MTurkRequestError
from boto.mturk.price import Price
from boto.mturk.qualification import LocaleRequirement
from boto.mturk.qualification import PercentAssignmentsApprovedRequirement
from boto.mturk.qualification import Qualifications
from boto.mturk.question import ExternalQuestion
from cached_property import cached_property

logger = logging.getLogger(__file__)


def timestr_to_dt(timestr):
    return datetime.datetime.strptime(timestr, '%Y-%m-%dT%H:%M:%SZ')


class MTurkServiceException(Exception):
    """Custom exception type"""


class MTurkService(object):
    """Facade for Amazon Mechanical Turk services provided via the boto
       library.
    """
    production_mturk_server = 'mechanicalturk.amazonaws.com'
    sandbox_mturk_server = 'mechanicalturk.sandbox.amazonaws.com'

    def __init__(self, aws_access_key_id, aws_secret_access_key, sandbox=True):
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.is_sandbox = sandbox

    @cached_property
    def mturk(self):
        """Cached MTurkConnection"""
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise MTurkServiceException('AWS access key and secret not set.')
        login_params = {
            'aws_access_key_id': self.aws_access_key_id,
            'aws_secret_access_key': self.aws_secret_access_key,
            'host': self.host
        }
        return MTurkConnection(**login_params)

    @property
    def host(self):
        if self.is_sandbox:
            return self.sandbox_mturk_server
        return self.production_mturk_server

    def check_credentials(self):
        """Verifies key/secret/host combination by making a balance inquiry"""
        return bool(self.mturk.get_account_balance())

    def set_rest_notification(self, url, hit_type_id):
        """Set a REST endpoint to recieve notifications about the HIT"""
        all_events = (
            "AssignmentAccepted",
            "AssignmentAbandoned",
            "AssignmentReturned",
            "AssignmentSubmitted",
            "HITReviewable",
            "HITExpired",
        )

        return self._is_ok(
            self.mturk.set_rest_notification(hit_type_id, url, event_types=all_events)
        )

    def register_hit_type(self, title, description, reward, duration_hours, keywords):
        """Register HIT Type for this HIT and return the type's ID, which
        is required for creating a HIT.
        """
        reward = reward
        duration_hours = datetime.timedelta(hours=duration_hours)
        hit_type = self.mturk.register_hit_type(
            title,
            description,
            reward,
            duration_hours,
            keywords=keywords,
            approval_delay=None,
            qual_req=None)[0]

        return hit_type.HITTypeId

    def build_hit_qualifications(self, approve_requirement, restrict_to_usa):
        """Translate restrictions/qualifications to boto Qualifications objects"""
        quals = Qualifications()
        quals.add(
            PercentAssignmentsApprovedRequirement(
                "GreaterThanOrEqualTo", approve_requirement)
        )

        if restrict_to_usa:
            quals.add(LocaleRequirement("EqualTo", "US"))

        return quals

    def create_qualification_type(self, name, description, status):
        """Passthrough. Create a new qualification Workers can be scored for.
        """
        qtype = self.mturk.create_qualification_type(name, description, status)[0]
        if qtype.IsValid != 'True':
            raise MTurkServiceException(
                "Qualification creation request was invalid for unknown reason.")

        return {
            'id': qtype.QualificationTypeId,
            'created': timestr_to_dt(qtype.CreationTime),
            'name': qtype.Name,
            'description': qtype.Description,
            'status': qtype.QualificationTypeStatus,
        }

    def assign_qualification(self, qualification_id, worker_id, score, notify=True):
        """Score a worker for a specific qualification"""
        return self._is_ok(self.mturk.assign_qualification(
            qualification_id,
            worker_id,
            score,
            notify
        ))

    def update_qualification_score(self, qualification_id, worker_id, score):
        """Score a worker for a specific qualification"""
        return self._is_ok(self.mturk.update_qualification_score(
            qualification_id,
            worker_id,
            score,
        ))

    def dispose_qualification_type(self, qualification_id):
        """Remove a qualification type we created"""
        return self._is_ok(
            self.mturk.dispose_qualification_type(qualification_id)
        )

    def get_workers_with_qualification(self, qualification_id):
        """Get workers with the given qualification."""
        done = False
        page = 1
        while not done:
            res = self.mturk.get_qualifications_for_qualification_type(
                qualification_id,
                page_size=100,
                page_number=page
            )
            if res:
                for r in res:
                    yield {'id': r.SubjectId, 'score': r.IntegerValue}
                page = page + 1
            else:
                done = True

    def set_qualification_score(self, qualification_id, worker_id, score, notify=True):
        """Convenience method will set a qualification score regardless of
        whether the worker already has a score for the specified qualification.
        """
        existing_workers = [
            w['id'] for w in self.get_workers_with_qualification(qualification_id)
        ]
        if worker_id in existing_workers:
            return self.update_qualification_score(qualification_id, worker_id, score)
        return self.assign_qualification(qualification_id, worker_id, score, notify)

    def create_hit(self, title, description, keywords, reward, duration_hours,
                   lifetime_days, ad_url, notification_url, approve_requirement,
                   max_assignments, us_only):
        """Create the actual HIT and return a dict with its useful properties."""
        frame_height = 600
        mturk_question = ExternalQuestion(ad_url, frame_height)
        qualifications = self.build_hit_qualifications(
            approve_requirement, us_only
        )
        hit_type_id = self.register_hit_type(
            title, description, reward, duration_hours, keywords
        )
        self.set_rest_notification(notification_url, hit_type_id)

        params = {
            'hit_type': hit_type_id,
            'question': mturk_question,
            'lifetime': datetime.timedelta(days=lifetime_days),
            'max_assignments': max_assignments,
            'title': title,
            'description': description,
            'keywords': keywords,
            'reward': Price(reward),
            'duration': datetime.timedelta(hours=duration_hours),
            'approval_delay': None,
            'qualifications': qualifications,
            'response_groups': [
                'Minimal',
                'HITDetail',
                'HITQuestion',
                'HITAssignmentSummary'
            ]
        }
        hit = self.mturk.create_hit(**params)[0]
        if hit.IsValid != 'True':
            raise MTurkServiceException("HIT request was invalid for unknown reason.")

        return self._translate_hit(hit)

    def extend_hit(self, hit_id, number, duration_hours):
        """Extend an existing HIT and return an updated description"""
        duration_as_secs = int(duration_hours * 3600)
        try:
            self.mturk.extend_hit(hit_id, expiration_increment=duration_as_secs)
        except MTurkRequestError:
            logger.exception("Failed to extend time until expiration of HIT")

        try:
            self.mturk.extend_hit(hit_id, assignments_increment=number)
        except MTurkRequestError:
            logger.exception("Error: failed to add {} assignments to HIT".format(number))

        updated_hit = self.mturk.get_hit(hit_id)[0]

        return self._translate_hit(updated_hit)

    def disable_hit(self, hit_id):
        return self._is_ok(self.mturk.disable_hit(hit_id))

    def get_hits(self, hit_filter=lambda x: True):
        for hit in self.mturk.get_all_hits():
            translated = self._translate_hit(hit)
            if hit_filter(translated):
                yield translated

    def grant_bonus(self, assignment_id, amount, reason):
        """Grant a bonus to the MTurk Worker.
        Issues a payment of money from your account to a Worker.  To
        be eligible for a bonus, the Worker must have submitted
        results for one of your HITs, and have had those results
        approved or rejected. This payment happens separately from the
        reward you pay to the Worker when you approve the Worker's
        assignment.
        """
        amount = Price(amount)
        assignment = self.mturk.get_assignment(assignment_id)[0]
        worker_id = assignment.WorkerId
        try:
            return self._is_ok(
                self.mturk.grant_bonus(worker_id, assignment_id, amount, reason)
            )
        except MTurkRequestError:
            logger.exception("Failed to pay assignment {} bonus of {}".format(
                assignment_id,
                amount
            ))

    def _translate_hit(self, hit):
        translated = {
            'id': hit.HITId,
            'type_id': hit.HITTypeId,
            'created': timestr_to_dt(hit.CreationTime),
            'expiration': timestr_to_dt(hit.Expiration),
            'max_assignments': int(hit.MaxAssignments),
            'title': hit.Title,
            'description': hit.Description,
            'keywords': hit.Keywords.split(', '),
            'reward': float(hit.Amount),
            'review_status': hit.HITReviewStatus,
            'status': hit.HITStatus,
        }

        return translated

    def _is_ok(self, mturk_response):
        return mturk_response == []

    def approve_assignment(self, assignment_id):
        try:
            self.mturk.approve_assignment(assignment_id, feedback=None)
        except MTurkRequestError:
            logger.exception(
                "Failed to approve assignment {}".format(assignment_id))
        return True
