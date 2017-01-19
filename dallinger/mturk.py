import datetime
from boto.mturk.connection import MTurkConnection
from boto.mturk.price import Price
from boto.mturk.qualification import LocaleRequirement
from boto.mturk.qualification import PercentAssignmentsApprovedRequirement
from boto.mturk.qualification import Qualifications
from boto.mturk.question import ExternalQuestion
from dallinger.utils import reify


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

    @reify
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

        result = self.mturk.set_rest_notification(
            hit_type_id, url, event_types=all_events
        )
        # An empty ResultSet is the return value when all goes well.
        return result == []

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
        self.mturk.extend_hit(hit_id, assignments_increment=number)
        self.mturk.extend_hit(hit_id, expiration_increment=duration_as_secs)

        updated_hit = self.mturk.get_hit(hit_id)[0]

        return self._translate_hit(updated_hit)

    def disable_hit(self, hit_id):
        turk = self.mturk
        # Empty ResultSet marks success
        return turk.disable_hit(hit_id) == []

    def get_hits(self, hit_filter=lambda x: True):
        for hit in self.mturk.get_all_hits():
            translated = self._translate_hit(hit)
            if hit_filter(translated):
                yield translated

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
