import datetime
from boto.mturk.connection import MTurkConnection
from boto.mturk.price import Price
from boto.mturk.qualification import LocaleRequirement
from boto.mturk.qualification import PercentAssignmentsApprovedRequirement
from boto.mturk.qualification import Qualifications
from boto.mturk.question import ExternalQuestion


class MTurkServiceException(Exception):
    """Custom exception type"""


class MTurkService(object):
    """Facade for Amazon Mechanical Turk services provided via the boto
       library.
    """
    production_mturk_server = 'mechanicalturk.amazonaws.com'
    sandbox_mturk_server = 'mechanicalturk.sandbox.amazonaws.com'
    _connection = None

    def __init__(self, aws_access_key_id, aws_secret_access_key, sandbox=True):
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.is_sandbox = sandbox

    @property
    def mturk(self):
        """Cached MTurkConnection"""
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise MTurkServiceException('AWS access key and secret not set.')
        login_params = {
            'aws_access_key_id': self.aws_access_key_id,
            'aws_secret_access_key': self.aws_secret_access_key,
            'host': self.host
        }
        if self._connection is None:
            self._connection = MTurkConnection(**login_params)
        return self._connection

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
        # [] seems to be the return value when all goes well.
        return result == []

    def register_hit_type(self, title, description, reward, duration, keywords):
        """Register HIT Type for this HIT and return the type's ID, which
        is required for creating a HIT.
        """
        reward = Price(reward)
        duration = datetime.timedelta(hours=duration)
        hit_type = self.mturk.register_hit_type(
            title,
            description,
            reward,
            duration,
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

    def create_hit(self, title, description, keywords, reward, duration, lifetime,
                   ad_url, notification_url, approve_requirement, max_assignments,
                   us_only):
        """Create the actual HIT and return a dict with its useful properties."""
        experiment_url = ad_url
        frame_height = 600
        mturk_question = ExternalQuestion(experiment_url, frame_height)
        qualifications = self.build_hit_qualifications(
            approve_requirement, us_only
        )
        hit_type_id = self.register_hit_type(
            title, description, reward, duration, keywords
        )
        self.set_rest_notification(notification_url, hit_type_id)

        params = {
            'hit_type': hit_type_id,
            'question': mturk_question,
            'lifetime': datetime.timedelta(days=lifetime),
            'max_assignments': max_assignments,
            'title': title,
            'description': description,
            'keywords': keywords,
            'reward': Price(reward),
            'duration': datetime.timedelta(hours=duration),
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
        if not hit.IsValid == 'True':
            raise MTurkServiceException("HIT request was invalid for unknown reason.")

        translated = {
            'id': hit.HITId,
            'type_id': hit.HITTypeId,
            'expiration': hit.Expiration,
            'max_assignments': int(hit.MaxAssignments),
            'title': hit.Title,
            'description': hit.Description,
            'keywords': hit.Keywords.split(', '),
            'reward': float(hit.Amount),
            'review_status': hit.HITReviewStatus,
            'status': hit.HITStatus,
            'assignments_available': int(hit.NumberOfAssignmentsAvailable),
            'assignments_completed': int(hit.NumberOfAssignmentsCompleted),
            'assignments_pending': int(hit.NumberOfAssignmentsPending),
        }

        return translated
