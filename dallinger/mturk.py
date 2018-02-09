import base64
import boto3
import datetime
import hmac
import logging
import requests
import time
import urllib

from hashlib import sha1
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError

from boto.mturk.connection import MTurkConnection
from boto.mturk.connection import MTurkRequestError
from boto.mturk.price import Price
from boto.mturk.qualification import LocaleRequirement
from boto.mturk.qualification import PercentAssignmentsApprovedRequirement
from boto.mturk.qualification import Qualifications
from boto.mturk.qualification import Requirement
from boto.mturk.question import ExternalQuestion
from cached_property import cached_property

logger = logging.getLogger(__file__)
PERCENTAGE_APPROVED_REQUIREMENT_ID = '000000000000000000L0'
LOCALE_REQUIREMENT_ID = '00000000000000000071'


def timestr_to_dt(timestr):
    return datetime.datetime.strptime(timestr, '%Y-%m-%dT%H:%M:%SZ')


class MTurkServiceException(Exception):
    """Custom exception type"""


class DuplicateQualificationNameError(MTurkServiceException):
    """A Qualification with the given name already exists"""


class QualificationNotFoundException(MTurkServiceException):
    """A Qualification searched for by name does not exist"""


class MTurkService(object):
    """Facade for Amazon Mechanical Turk services provided via the boto
       library.
    """
    production_mturk_server = 'mechanicalturk.amazonaws.com'
    sandbox_mturk_server = 'mechanicalturk.sandbox.amazonaws.com'
    production_mturk_server3 = u'https://mturk-requester.us-east-1.amazonaws.com'
    sandbox_mturk_server3 = u'https://mturk-requester-sandbox.us-east-1.amazonaws.com'

    max_wait_secs = 0

    def __init__(self, aws_access_key_id, aws_secret_access_key, region_name, sandbox=True):
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.region_name = region_name
        self.is_sandbox = sandbox

    # @cached_property
    @property
    def session(self):
        from boto3.session import Session
        return Session(
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.region_name
        )

    @cached_property
    def mturk(self):
        return self.session.client(
            'mturk',
            endpoint_url=self.host,
            region_name=self.region_name,
        )

    @cached_property
    def mturk2(self):
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
            return self.sandbox_mturk_server3
        return self.production_mturk_server3

    @property
    def host2(self):
        if self.is_sandbox:
            return self.sandbox_mturk_server
        return self.production_mturk_server

    def check_credentials(self):
        """Verifies key/secret/host combination by making a balance inquiry"""
        try:
            return bool(self.mturk.get_account_balance())
        except NoCredentialsError:
            raise MTurkServiceException("No AWS credentials set!")
        except ClientError:
            raise MTurkServiceException("Invalid AWS credentials!")

    def set_rest_notification(self, url, hit_type_id):
        """Set a REST endpoint to recieve notifications about the HIT"""
        ISO8601 = '%Y-%m-%dT%H:%M:%SZ'
        data = {
            'AWSAccessKeyId': self.aws_access_key_id,
            'HITTypeId': hit_type_id,
            'Notification.1.Active': 'True',
            'Notification.1.Destination': url,
            'Notification.1.EventType.1': 'AssignmentAccepted',
            'Notification.1.EventType.2': 'AssignmentAbandoned',
            'Notification.1.EventType.3': 'AssignmentReturned',
            'Notification.1.EventType.4': 'AssignmentSubmitted',
            'Notification.1.EventType.5': 'HITReviewable',
            'Notification.1.EventType.6': 'HITExpired',
            'Notification.1.Transport': 'REST',
            'Notification.1.Version': '2006-05-05',
            'Operation': 'SetHITTypeNotification',
            'SignatureVersion': '1',
            'Timestamp': time.strftime(ISO8601, time.gmtime()),
            'Version': '2014-08-15',
        }
        qs, sig = self._calc_old_api_signature(data)
        body = qs + '&Signature=' + urllib.quote_plus(sig)
        data['Signature'] = sig
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Content-Length': str(len(body)),
            'Host': 'mechanicalturk.sandbox.amazonaws.com',
            'User-Agent': 'Boto/2.48.0 Python/2.7.13 Darwin/15.6.0'
        }
        resp = requests.post(
            'https://mechanicalturk.sandbox.amazonaws.com',
            headers=headers,
            data=body
        )
        return '<IsValid>True</IsValid>' in resp.text

    def register_hit_type(self,
                          title,
                          description,
                          reward,
                          duration_hours,
                          keywords,
                          qualifications):
        """Register HIT Type for this HIT and return the type's ID, which
        is required for creating a HIT.
        """
        reward = str(reward)
        duration_secs = datetime.timedelta(hours=duration_hours).seconds
        hit_type = self.mturk.create_hit_type(
            Title=title,
            Description=description,
            Reward=reward,
            AssignmentDurationInSeconds=duration_secs,
            Keywords=','.join(keywords),
            AutoApprovalDelayInSeconds=0,
            QualificationRequirements=qualifications)

        return hit_type['HITTypeId']

    def build_hit_qualifications(self,
                                 approve_requirement,
                                 restrict_to_usa,
                                 blacklist):
        """Translate restrictions/qualifications to boto Qualifications objects

        @blacklist is a list of names for Qualifications workers must
        not already hold in order to see and accept the HIT.
        """
        quals = [
            {
                'QualificationTypeId': PERCENTAGE_APPROVED_REQUIREMENT_ID,
                'Comparator': 'GreaterThanOrEqualTo',
                'IntegerValues': [95],
                'RequiredToPreview': True,
            }
        ]
        if restrict_to_usa:
            quals.append(
                {
                    'QualificationTypeId': LOCALE_REQUIREMENT_ID,
                    'Comparator': 'EqualTo',
                    'LocaleValues': [{'Country': 'US'}],
                    'RequiredToPreview': True,
                }
            )
        if blacklist is not None:
            for item in blacklist:
                qtype = self.get_qualification_type_by_name(item)
                if qtype:
                    quals.append(
                        {
                            'QualificationTypeId': qtype['id'],
                            'Comparator': 'DoesNotExist',
                            'RequiredToPreview': True,
                        }
                    )
        return quals

    def create_qualification_type(self, name, description, status='Active'):
        """Create a new qualification Workers can be scored for.
        """
        try:
            response = self.mturk.create_qualification_type(
                Name=name,
                Description=description,
                QualificationTypeStatus=status
            )
        except Exception as ex:
            if u'already created a QualificationType with this name' in ex.message:
                raise DuplicateQualificationNameError(ex.message)

        return self._translate_qtype(response['QualificationType'])

    def get_qualification_type_by_name(self, name):
        """Return a Qualification Type by name. If the provided name matches
        more than one Qualification, check to see if any of the results
        match the provided name exactly. If there's an exact match, return
        that Qualification. Otherwise, raise an exception.
        """
        query = name.upper()
        start = time.time()
        args = {
            'Query': query,
            'MustBeRequestable': False,
            'MustBeOwnedByCaller': True,
            'MaxResults': 2,
        }
        results = self.mturk.list_qualification_types(**args)['QualificationTypes']

        # This loop is largely for tests, because there's some indexing that
        # needs to happen on MTurk for search to work:
        while not results and time.time() - start < self.max_wait_secs:
            time.sleep(1)
            results = self.mturk.list_qualification_types(**args)['QualificationTypes']

        if not results:
            return None

        qualifications = [self._translate_qtype(r) for r in results]
        if len(qualifications) > 1:
            for qualification in qualifications:
                if qualification['name'].upper() == query:
                    return qualification

            raise MTurkServiceException("{} was not a unique name".format(query))

        return qualifications[0]

    def assign_qualification(self, qualification_id, worker_id, score, notify=False):
        """Score a worker for a specific qualification"""
        return self._is_ok(self.mturk.associate_qualification_with_worker(
            QualificationTypeId=qualification_id,
            WorkerId=worker_id,
            IntegerValue=score,
            SendNotification=notify
        ))

    def revoke_qualification(self, qualification_id, worker_id, reason=''):
        return self._is_ok(self.mturk.disassociate_qualification_from_worker(
            QualificationTypeId=qualification_id,
            WorkerId=worker_id,
            Reason=reason
        ))

    def get_qualification_score(self, qualification_id, worker_id):
        """Return a worker's qualification score as an iteger.
        """
        try:
            response = self.mturk.get_qualification_score(
                QualificationTypeId=qualification_id,
                WorkerId=worker_id
            )
        except ClientError as ex:
            raise MTurkServiceException(ex.message)
        return response['Qualification']['IntegerValue']

    def get_current_qualification_score(self, name, worker_id):
        """Return the current score for a worker, on a qualification with the
        provided name.
        """
        qtype = self.get_qualification_type_by_name(name)
        if qtype is None:
            raise QualificationNotFoundException(
                'No Qualification exists with name "{}"'.format(name)
            )
        try:
            score = self.get_qualification_score(qtype['id'], worker_id)
        except MTurkServiceException:
            score = None
        return {
            'qtype': qtype,
            'score': score
        }

    def increment_qualification_score(self, name, worker_id, notify=False):
        """Increment the current qualification score for a worker, on a
        qualification with the provided name.
        """
        result = self.get_current_qualification_score(name, worker_id)
        current_score = result['score'] or 0
        new_score = current_score + 1
        qtype_id = result['qtype']['id']
        self.update_qualification_score(qtype_id, worker_id, new_score)

        return {
            'qtype': result['qtype'],
            'score': new_score
        }

    def update_qualification_score(self, qualification_id, worker_id, score):
        """Score a worker for a specific qualification"""
        return self.assign_qualification(qualification_id, worker_id, score)

    def dispose_qualification_type(self, qualification_id):
        """Remove a qualification type we created"""
        return self.mturk.delete_qualification_type(
            QualificationTypeId=qualification_id
        )

    def get_workers_with_qualification(self, qualification_id):
        """Get workers with the given qualification."""
        done = False
        next_token = None
        while not done:
            if next_token is not None:
                response = self.mturk.list_workers_with_qualification_type(
                    QualificationTypeId=qualification_id,
                    MaxResults=100,
                    Status='Granted',
                    NextToken=next_token
                )
            else:
                response = self.mturk.list_workers_with_qualification_type(
                    QualificationTypeId=qualification_id,
                    MaxResults=100,
                    Status='Granted',
                )
            if response:
                for r in response['Qualifications']:
                    yield {'id': r['WorkerId'], 'score': r['IntegerValue']}
            if 'NextToken' in response:
                next_token = response['NextToken']
            else:
                done = True

    def set_qualification_score(self, qualification_id, worker_id, score, notify=False):
        """Convenience method will set a qualification score regardless of
        whether the worker already has a score for the specified qualification.
        """
        return self.assign_qualification(qualification_id, worker_id, score, notify)

    def create_hit(self, title, description, keywords, reward, duration_hours,
                   lifetime_days, ad_url, notification_url, approve_requirement,
                   max_assignments, us_only, blacklist=None):
        """Create the actual HIT and return a dict with its useful properties."""
        frame_height = 600
        mturk_question = self._external_question(ad_url, frame_height)
        qualifications = self.build_hit_qualifications(
            approve_requirement, us_only, blacklist
        )
        # We need a HIT_Type in order to register for REST notifications
        hit_type_id = self.register_hit_type(
            title, description, reward, duration_hours, keywords, qualifications
        )
        self.set_rest_notification(notification_url, hit_type_id)

        params = {
            'HITTypeId': hit_type_id,
            'Question': mturk_question,
            'LifetimeInSeconds': datetime.timedelta(days=lifetime_days).seconds,
            'MaxAssignments': max_assignments,
            'UniqueRequestToken': self._request_token()
        }
        response = self.mturk.create_hit_with_hit_type(**params)
        if 'HIT' not in response:
            raise MTurkServiceException("HIT request was invalid for unknown reason.")
        return self._translate_hit(response['HIT'])

    def extend_hit(self, hit_id, number, duration_hours=None):
        """Extend an existing HIT and return an updated description"""
        self.create_additional_assignments_for_hit(hit_id, number)

        if duration_hours is not None:
            self.update_expiration_for_hit(hit_id, duration_hours)

        return self.get_hit(hit_id)

    def create_additional_assignments_for_hit(self, hit_id, number):
        try:
            response = self.mturk.create_additional_assignments_for_hit(
                HITId=hit_id,
                NumberOfAdditionalAssignments=number,
                UniqueRequestToken=self._request_token()
            )
        except Exception as ex:
            raise MTurkServiceException(
                "Error: failed to add {} assignments to HIT: {}".format(
                    number, ex.message
                )
            )
        return self._is_ok(response)

    def update_expiration_for_hit(self, hit_id, hours):
        hit = self.get_hit(hit_id)
        expiration = datetime.timedelta(hours=hours) + hit['expiration']
        try:
            response = self.mturk.update_expiration_for_hit(
                HITId=hit_id,
                ExpireAt=expiration,
            )
        except Exception as ex:
            raise MTurkServiceException(
                "Failed to extend time until expiration of HIT: {}".format(
                    expiration, ex.message
                )
            )
        return self._is_ok(response)

    def disable_hit(self, hit_id):
        self.expire_hit(hit_id)
        return self.mturk.delete_hit(HITId=hit_id)

    def get_hit(self, hit_id):
        return self._translate_hit(self.mturk.get_hit(HITId=hit_id)['HIT'])

    def get_hits(self, hit_filter=lambda x: True):
        done = False
        next_token = None
        while not done:
            if next_token is not None:
                response = self.mturk.list_hits(
                    MaxResults=100, NextToken=next_token
                )
            else:
                response = self.mturk.list_hits(MaxResults=100)
            for hit in response['HITs']:
                translated = self._translate_hit(hit)
                if hit_filter(translated):
                    yield translated
            if 'NextToken' in response:
                next_token = response['NextToken']
            else:
                done = True

    def grant_bonus(self, assignment_id, amount, reason):
        """Grant a bonus to the MTurk Worker.
        Issues a payment of money from your account to a Worker.  To
        be eligible for a bonus, the Worker must have submitted
        results for one of your HITs, and have had those results
        approved or rejected. This payment happens separately from the
        reward you pay to the Worker when you approve the Worker's
        assignment.
        """
        assignment = self.mturk.get_assignment(assignment_id)
        worker_id = assignment['Assignment']['WorkerId']

        try:
            return self._is_ok(self.mturk.send_bonus(
                WorkerId=worker_id,
                BonusAmount=str(amount),
                AssignmentId=assignment_id,
                Reason=reason,
                UniqueRequestToken=self._request_token()
            ))
        except ClientError as ex:
            error = "Failed to pay assignment {} bonus of {}: {}".format(
                assignment_id,
                amount,
                ex.message
            )
            raise MTurkServiceException(error)

    def approve_assignment(self, assignment_id):
        """Approving an assignment initiates two payments from the
        Requester's Amazon.com account:
            1. The Worker who submitted the results is paid
               the reward specified in the HIT.
            2. Amazon Mechanical Turk fees are debited.
        """
        try:
            return self._is_ok(
                self.mturk.approve_assignment(AssignmentId=assignment_id)
            )
        except ClientError as ex:
            raise MTurkServiceException(
                "Failed to approve assignment {}: {}".format(
                    assignment_id, ex.message)
            )

    def expire_hit(self, hit_id):
        """Expire a HIT, which will change its status to "Reviewable",
        allowing it to be deleted.
        """
        try:
            self.mturk.update_expiration_for_hit(HITId=hit_id, ExpireAt=0)
        except Exception as ex:
            raise MTurkServiceException(
                "Failed to expire HIT {}: {}".format(hit_id, ex.message))
        return True

    def _calc_old_api_signature(self, params, *args):
        sig = hmac.new(
            self.aws_secret_access_key.encode('utf-8'),
            digestmod=sha1
        )
        keys = list(params.keys())
        keys.sort(key=lambda x: x.lower())
        pairs = []
        for key in keys:
            sig.update(key.encode('utf-8'))
            val = params[key].encode('utf-8')
            sig.update(val)
            pairs.append(key + '=' + urllib.quote(val))
        qs = '&'.join(pairs)
        return (qs, base64.b64encode(sig.digest()))

    def _external_question(self, url, frame_height):
        q = ('<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">'
             '<ExternalURL>{}</ExternalURL>'
             '<FrameHeight>{}</FrameHeight></ExternalQuestion>')
        return q.format(url, frame_height)

    def _request_token(self):
        return str(time.time())

    def _translate_hit(self, hit):
        translated = {
            'id': hit['HITId'],
            'type_id': hit['HITTypeId'],
            'created': hit['CreationTime'],
            'expiration': hit['Expiration'],
            'max_assignments': hit['MaxAssignments'],
            'title': hit['Title'],
            'description': hit['Description'],
            'keywords': [w.strip() for w in hit['Keywords'].split(',')],
            'qualification_type_ids': [
                q['QualificationTypeId'] for q in hit['QualificationRequirements']
            ],
            'reward': float(hit['Reward']),
            'review_status': hit['HITReviewStatus'],
            'status': hit['HITStatus'],
        }

        return translated

    def _translate_qtype(self, qtype):
        return {
            'id': qtype['QualificationTypeId'],
            'created': qtype['CreationTime'],
            'name': qtype['Name'],
            'description': qtype['Description'],
            'status': qtype['QualificationTypeStatus'],
        }

    def _is_ok(self, response):
        return response == {} or response.keys() == ['ResponseMetadata']
