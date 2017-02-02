import datetime
import mock
import pytest
from boto.resultset import ResultSet
from boto.mturk.price import Price
from boto.mturk.connection import Assignment
from boto.mturk.connection import HITTypeId
from boto.mturk.connection import HIT
from boto.mturk.connection import Qualification
from boto.mturk.connection import QualificationType
from boto.mturk.connection import MTurkConnection
from boto.mturk.connection import MTurkRequestError
from .conftest import skip_if_not_mturk_requestor
from .conftest import skip_if_not_mturk_requestor_and_worker
from dallinger.mturk import MTurkService
from dallinger.mturk import MTurkServiceException


TEST_HIT_DESCRIPTION = '***TEST SUITE HIT***'
TEST_QUALIFICATION_DESCRIPTION = '***TEST SUITE QUALIFICATION***'


def as_resultset(things):
    if not isinstance(things, (list, tuple)):
        things = [things]
    result = ResultSet()
    for thing in things:
        result.append(thing)
    return result


def fake_balance_response():
    return as_resultset(Price(1.00))


def fake_hit_type_response():
    htid = HITTypeId(None)
    htid.HITTypeId = u'fake HITTypeId'
    return as_resultset(htid)


def fake_hit_response(**kwargs):
    canned_response = {
        'Amount': u'0.01',
        'AssignmentDurationInSeconds': u'900',
        'AutoApprovalDelayInSeconds': u'2592000',
        'CreationTime': u'2017-01-06T01:58:45Z',
        'CurrencyCode': u'USD',
        'Description': u'Fake Description',
        'Expiration': u'2017-01-07T01:58:45Z',
        'FormattedPrice': u'$0.01',
        'HIT': '',
        'HITGroupId': u'fake HIT group ID',
        'HITId': u'fake HIT ID',
        'HITReviewStatus': u'NotReviewed',
        'HITStatus': u'Assignable',
        'HITTypeId': u'fake HITTypeId',
        'IsValid': u'True',
        'Keywords': u'testkw1, testkw2',
        'MaxAssignments': u'1',
        'NumberOfAssignmentsAvailable': u'1',
        'NumberOfAssignmentsCompleted': u'0',
        'NumberOfAssignmentsPending': u'0',
        'Question': (
            u'<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/'
            u'AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">'
            u'<ExternalURL>https://url-of-ad-route</ExternalURL>'
            u'<FrameHeight>600</FrameHeight></ExternalQuestion>'
        ),
        'Request': '',
        'Reward': '',
        'Title': u'Fake Title',
    }
    canned_response.update(**kwargs)
    hit = HIT(None)
    for k, v in canned_response.items():
        hit.endElement(k, v, None)

    return as_resultset(hit)


def fake_qualification_response():
    canned_response = {
        'Status': u'Granted',
        'QualificationTypeId': u'3J48J1M4J7MXEAEO66XD9Q4JQ851VA',
        'SubjectId': u'A2ZTO3X61UKR1G',
        'Qualification': '',
        'GrantTime': u'2017-02-02T13:06:13.000-08:00',
        'IntegerValue': u'2'
    }
    qtype = Qualification(None)
    for k, v in canned_response.items():
        qtype.endElement(k, v, None)

    return as_resultset(qtype)


def fake_qualification_type_response():
    canned_response = {
        'AutoGranted': u'0',
        'QualificationType': '',
        'Description': u'***TEST SUITE QUALIFICATION***',
        'QualificationTypeId': u'37RZXPVRUD8UI52US2V7MH6HZA2L1A',
        'IsValid': u'True',
        'Request': '',
        'QualificationTypeStatus': u'Active',
        'CreationTime': u'2017-02-02T17:36:03Z',
        'Name': u'Test Qualifiction'
    }

    qtype = QualificationType(None)
    for k, v in canned_response.items():
        qtype.endElement(k, v, None)

    return as_resultset(qtype)


def standard_hit_config(**kwargs):
    defaults = {
        'ad_url': 'https://url-of-ad-route',
        'approve_requirement': 95,
        'us_only': True,
        'lifetime_days': 0.1,
        'max_assignments': 1,
        'notification_url': 'https://url-of-notification-route',
        'title': 'Test Title',
        'description': TEST_HIT_DESCRIPTION,
        'keywords': ['testkw1', 'testkw1'],
        'reward': .01,
        'duration_hours': .25
    }
    defaults.update(**kwargs)

    return defaults


@pytest.fixture
def mturk(creds_from_environment):
    creds = creds_from_environment
    service = MTurkService(**creds)
    return service


@pytest.fixture
def mturk_fake_creds():
    creds = {
        'aws_access_key_id': 'fake key id',
        'aws_secret_access_key': 'fake secret'
    }
    service = MTurkService(**creds)
    return service


@pytest.fixture
def mturk_empty_creds():
    service = MTurkService(aws_access_key_id='', aws_secret_access_key='')
    return service


@pytest.fixture
def mturk_with_cleanup(creds_from_environment, request):
    creds = creds_from_environment
    service = MTurkService(**creds)
    request.instance._qtypes_to_purge = []
    yield service

    # tear-down: clean up all specially-marked HITs:
    def test_hits_only(hit):
        return hit['description'] == TEST_HIT_DESCRIPTION

    for hit in service.get_hits(test_hits_only):
        service.disable_hit(hit['id'])

    for qtype_id in request.instance._qtypes_to_purge:
        service.dispose_qualification_type(qtype_id)


@skip_if_not_mturk_requestor
class TestMTurkService(object):

    def test_check_credentials_good_credentials(self, mturk):
        is_authenticated = mturk.check_credentials()
        assert is_authenticated

    def test_check_credentials_bad_credentials(self, mturk_fake_creds):
        with pytest.raises(MTurkRequestError):
            mturk_fake_creds.check_credentials()

    def test_check_credentials_no_creds_set_raises(self, mturk_empty_creds):
        with pytest.raises(MTurkServiceException):
            mturk_empty_creds.check_credentials()

    def test_register_hit_type(self, mturk):
        config = {
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw1'],
            'reward': .01,
            'duration_hours': .25
        }
        hit_type_id = mturk.register_hit_type(**config)

        assert isinstance(hit_type_id, unicode)

    def test_register_notification_url(self, mturk):
        config = {
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw1'],
            'reward': .01,
            'duration_hours': .25
        }
        url = 'https://url-of-notification-route'
        hit_type_id = mturk.register_hit_type(**config)

        assert mturk.set_rest_notification(url, hit_type_id) is True

    def test_create_hit(self, mturk_with_cleanup):
        service = mturk_with_cleanup
        hit = service.create_hit(**standard_hit_config())
        assert hit['status'] == 'Assignable'
        assert hit['max_assignments'] == 1

    def test_create_hit_two_assignments(self, mturk_with_cleanup):
        service = mturk_with_cleanup
        hit = service.create_hit(**standard_hit_config(max_assignments=2))
        assert hit['status'] == 'Assignable'
        assert hit['max_assignments'] == 2

    def test_extend_hit_with_valid_hit_id(self, mturk_with_cleanup):
        service = mturk_with_cleanup
        hit = service.create_hit(**standard_hit_config())

        updated = service.extend_hit(hit['id'], number=1, duration_hours=.25)

        assert updated['max_assignments'] == 2
        clock_skew = .01
        expected_extension = datetime.timedelta(hours=.25 - clock_skew)
        assert updated['expiration'] >= hit['expiration'] + expected_extension

    def test_extend_hit_with_invalid_hit_id_raises(self, mturk):
        service = mturk
        with pytest.raises(MTurkRequestError):
            service.extend_hit('dud', number=1, duration_hours=.25)

    def test_disable_hit_with_valid_hit_id(self, mturk_with_cleanup):
        service = mturk_with_cleanup
        hit = service.create_hit(**standard_hit_config())
        assert service.disable_hit(hit['id'])

    def test_disable_hit_with_invalid_hit_id_raises(self, mturk):
        service = mturk
        with pytest.raises(MTurkRequestError):
            service.disable_hit('dud')

    def test_get_hits_returns_all_by_default(self, mturk_with_cleanup):
        service = mturk_with_cleanup
        hit = service.create_hit(**standard_hit_config())
        hits = service.get_hits()

        assert hit in hits

    def test_get_hits_excludes_based_on_filter(self, mturk_with_cleanup):
        service = mturk_with_cleanup
        hit1 = service.create_hit(**standard_hit_config())
        hit2 = service.create_hit(**standard_hit_config(title='HIT Two'))
        hits = list(service.get_hits(lambda h: 'Two' in h['title']))

        assert hit1 not in hits
        assert hit2 in hits

    def test_create_and_dispose_qualification_type(self, mturk_with_cleanup):
        result = mturk_with_cleanup.create_qualification_type(
            name='Test Qualifiction',
            description=TEST_QUALIFICATION_DESCRIPTION,
            status='Active',
        )

        assert isinstance(result['id'], unicode)
        assert result['status'] == u'Active'
        assert mturk_with_cleanup.dispose_qualification_type(result['id'])


@skip_if_not_mturk_requestor_and_worker
class TestMTurkServiceWithRequestorAndWorker(object):

    def _make_qtype(self, mturk):
        qtype = mturk.create_qualification_type(
            name='Test Qualifiction',
            description=TEST_QUALIFICATION_DESCRIPTION,
            status='Active',
        )
        self._qtypes_to_purge.append(qtype['id'])
        return qtype

    @property
    def worker_id(self):
        import os
        return os.getenv('mturk_worker_id')

    def test_assign_and_revoke_qualification(self, mturk_with_cleanup):
        qtype = mturk_with_cleanup.create_qualification_type(
            name='Test Qualifiction',
            description=TEST_QUALIFICATION_DESCRIPTION,
            status='Active',
        )

        assert mturk_with_cleanup.assign_qualification(
            qtype['id'], self.worker_id, score=2, notify=False)
        assert mturk_with_cleanup.dispose_qualification_type(qtype['id'])

    def test_assign_already_granted_qualification_raises(self, mturk_with_cleanup):
        service = mturk_with_cleanup
        qtype = self._make_qtype(service)
        service.assign_qualification(qtype['id'], self.worker_id, score=2, notify=False)

        with pytest.raises(MTurkRequestError):
            service.assign_qualification(qtype['id'], self.worker_id, score=2, notify=False)

    def test_update_qualification_score(self, mturk_with_cleanup):
        qtype = self._make_qtype(mturk_with_cleanup)
        mturk_with_cleanup.assign_qualification(
            qtype['id'], self.worker_id, score=2, notify=False)

        mturk_with_cleanup.update_qualification_score(qtype['id'], self.worker_id, score=3)
        new_score = mturk_with_cleanup.mturk.get_qualification_score(
            qtype['id'], self.worker_id)[0].IntegerValue

        assert new_score == '3'

    def test_get_workers_with_qualification(self, mturk_with_cleanup):
        qtype = self._make_qtype(mturk_with_cleanup)
        mturk_with_cleanup.assign_qualification(
            qtype['id'], self.worker_id, score=2, notify=False)

        workers = mturk_with_cleanup.get_workers_with_qualification(qtype['id'])
        assert self.worker_id in [w['id'] for w in workers]

    def test_set_qualification_score_with_new_qualification(self, mturk_with_cleanup):
        service = mturk_with_cleanup
        qtype = self._make_qtype(service)

        service.set_qualification_score(qtype['id'], self.worker_id, score=2, notify=False)
        new_score = mturk_with_cleanup.mturk.get_qualification_score(
            qtype['id'], self.worker_id)[0].IntegerValue

        assert new_score == '2'

    def test_set_qualification_score_with_existing_qualification(self, mturk_with_cleanup):
        service = mturk_with_cleanup
        qtype = self._make_qtype(service)
        mturk_with_cleanup.assign_qualification(
            qtype['id'], self.worker_id, score=2, notify=False)

        service.set_qualification_score(qtype['id'], self.worker_id, score=3, notify=False)
        new_score = mturk_with_cleanup.mturk.get_qualification_score(
            qtype['id'], self.worker_id)[0].IntegerValue

        assert new_score == '3'


def mock_mtc(**kwargs):
    mock_config = {
        'spec': MTurkConnection,
    }
    mock_config.update(**kwargs)
    return mock.Mock(**mock_config)


class TestMTurkServiceWithFakeConnection(object):

    def test_is_sandbox_by_default(self, mturk_fake_creds):
        assert mturk_fake_creds.is_sandbox

    def test_host_server_is_sandbox_by_default(self, mturk_fake_creds):
        assert 'sandbox' in mturk_fake_creds.host

    def test_host_server_is_production_if_sandbox_false(self, mturk_fake_creds):
        mturk_fake_creds.is_sandbox = False
        assert 'sandbox' not in mturk_fake_creds.host

    def test_check_credentials_converts_response_to_boolean_true(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(
            **{'get_account_balance.return_value': fake_balance_response()}
        )
        assert mturk_fake_creds.check_credentials() is True

    def test_check_credentials_calls_get_account_balance(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(
            **{'get_account_balance.return_value': fake_balance_response()}
        )
        mturk_fake_creds.check_credentials()
        mturk_fake_creds.mturk.get_account_balance.assert_called_once()

    def test_check_credentials_bad_credentials(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(
            **{'get_account_balance.side_effect': MTurkRequestError(1, 'ouch')}
        )
        with pytest.raises(MTurkRequestError):
            mturk_fake_creds.check_credentials()

    def test_check_credentials_no_creds_set_raises(self, mturk_empty_creds):
        with pytest.raises(MTurkServiceException):
            mturk_empty_creds.check_credentials()

    def test_register_hit_type(self, mturk_fake_creds):
        config = {
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw2'],
            'reward': .01,
            'duration_hours': .25
        }
        mturk_fake_creds.mturk = mock_mtc(**{
            'get_account_balance.return_value': fake_balance_response(),
            'register_hit_type.return_value': fake_hit_type_response(),
        })

        mturk_fake_creds.register_hit_type(**config)

        mturk_fake_creds.mturk.register_hit_type.assert_called_once_with(
            'Test Title',
            'Test Description',
            .01,
            datetime.timedelta(hours=.25),
            keywords=['testkw1', 'testkw2'],
            approval_delay=None,
            qual_req=None
        )

    def test_set_rest_notification(self, mturk_fake_creds):
        url = 'https://url-of-notification-route'
        hit_type_id = 'fake hittype id'
        mturk_fake_creds.mturk = mock_mtc(**{
            'set_rest_notification.return_value': ResultSet(),
        })

        mturk_fake_creds.set_rest_notification(url, hit_type_id)

        mturk_fake_creds.mturk.set_rest_notification.assert_called_once()

    def test_create_hit_calls_underlying_mturk_method(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response(),
        })

        mturk_fake_creds.create_hit(**standard_hit_config())

        mturk_fake_creds.mturk.create_hit.assert_called_once()

    def test_create_hit_translates_response_back_from_mturk(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response(),
        })

        hit = mturk_fake_creds.create_hit(**standard_hit_config())

        assert hit['max_assignments'] == 1
        assert hit['reward'] == .01
        assert hit['keywords'] == ['testkw1', 'testkw2']
        assert isinstance(hit['created'], datetime.datetime)
        assert isinstance(hit['expiration'], datetime.datetime)

    def test_create_hit_raises_if_returned_hit_not_valid(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response(IsValid='False'),
        })
        with pytest.raises(MTurkServiceException):
            mturk_fake_creds.create_hit(**standard_hit_config())

    def test_extend_hit(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'extend_hit.return_value': None,
            'get_hit.return_value': fake_hit_response(),
        })

        mturk_fake_creds.extend_hit(hit_id='hit1', number=2, duration_hours=1.0)

        mturk_fake_creds.mturk.extend_hit.assert_has_calls([
            mock.call('hit1', assignments_increment=2),
            mock.call('hit1', expiration_increment=3600)
        ])

    def test_disable_hit_simple_passthrough(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'disable_hit.return_value': ResultSet(),
        })

        mturk_fake_creds.disable_hit('some hit')

        mturk_fake_creds.mturk.disable_hit.assert_called_once_with('some hit')

    def test_get_hits_returns_all_by_default(self, mturk_fake_creds):
        hr1 = fake_hit_response(Title='One')[0]
        ht2 = fake_hit_response(Title='Two')[0]

        mturk_fake_creds.mturk = mock_mtc(**{
            'get_all_hits.return_value': as_resultset([hr1, ht2]),
        })

        assert len(list(mturk_fake_creds.get_hits())) == 2

    def test_get_hits_excludes_based_on_filter(self, mturk_fake_creds):
        hr1 = fake_hit_response(Title='HIT One')[0]
        ht2 = fake_hit_response(Title='HIT Two')[0]
        mturk_fake_creds.mturk = mock_mtc(**{
            'get_all_hits.return_value': as_resultset([hr1, ht2]),
        })

        hits = list(mturk_fake_creds.get_hits(lambda h: 'Two' in h['title']))

        assert len(hits) == 1
        assert hits[0]['title'] == 'HIT Two'

    def test_grant_bonus_translates_values_and_calls_wrapped_mturk(self, mturk_fake_creds):
        fake_assignment = Assignment(None)
        fake_assignment.WorkerId = 'some worker id'
        mturk_fake_creds.mturk = mock_mtc(**{
            'grant_bonus.return_value': ResultSet(),
            'get_assignment.return_value': as_resultset(fake_assignment),
        })

        mturk_fake_creds.grant_bonus(
            assignment_id='some assignment id',
            amount=2.99,
            reason='above and beyond'
        )

        mturk_fake_creds.mturk.grant_bonus.assert_called_once_with(
            'some worker id',
            'some assignment id',
            mock.ANY,  # can't compare Price objects :-(
            'above and beyond'
        )

    def test_approve_assignment(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'approve_assignment.return_value': ResultSet(),
        })

        assert mturk_fake_creds.approve_assignment('fake id') is True
        mturk_fake_creds.mturk.approve_assignment.assert_called_once_with(
            'fake id', feedback=None
        )

    def test_create_qualification_type(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'create_qualification_type.return_value': fake_qualification_type_response(),
        })
        result = mturk_fake_creds.create_qualification_type('name', 'desc', 'status')
        mturk_fake_creds.mturk.create_qualification_type.assert_called_once_with(
            'name', 'desc', 'status'
        )
        assert isinstance(result['created'], datetime.datetime)

    def test_create_qualification_type_raises_if_invalid(self, mturk_fake_creds):
        response = fake_qualification_type_response()
        response[0].IsValid = 'False'
        mturk_fake_creds.mturk = mock_mtc(**{
            'create_qualification_type.return_value': response,
        })
        with pytest.raises(MTurkServiceException):
            mturk_fake_creds.create_qualification_type('name', 'desc', 'status')

    def test_assign_qualification(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'assign_qualification.return_value': ResultSet(),
        })
        assert mturk_fake_creds.assign_qualification('qid', 'worker', 'score')
        mturk_fake_creds.mturk.assign_qualification.assert_called_once_with(
            'qid', 'worker', 'score', True
        )

    def test_update_qualification_score(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'update_qualification_score.return_value': ResultSet(),
        })
        assert mturk_fake_creds.update_qualification_score('qid', 'worker', 'score')
        mturk_fake_creds.mturk.update_qualification_score.assert_called_once_with(
            'qid', 'worker', 'score'
        )

    def test_dispose_qualification_type(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'dispose_qualification_type.return_value': ResultSet(),
        })
        assert mturk_fake_creds.dispose_qualification_type('qid')
        mturk_fake_creds.mturk.dispose_qualification_type.assert_called_once_with(
            'qid'
        )

    def test_get_workers_with_qualification(self, mturk_fake_creds):
        mturk_fake_creds.mturk = mock_mtc(**{
            'get_qualifications_for_qualification_type.side_effect': [
                fake_qualification_response(), ResultSet()
            ],
        })
        expected = [
            mock.call('qid', page_number=1, page_size=100),
            mock.call('qid', page_number=2, page_size=100)
        ]
        # need to unroll the iterator:
        list(mturk_fake_creds.get_workers_with_qualification('qid'))
        calls = mturk_fake_creds.mturk.get_qualifications_for_qualification_type.call_args_list
        assert calls == expected

    def test_set_qualification_score_with_existing_qualification(self, mturk_fake_creds):
        mturk_fake_creds.get_workers_with_qualification = mock.Mock(
            return_value=[{'id': 'workerid', 'score': 2}]
        )
        mturk_fake_creds.update_qualification_score = mock.Mock(
            return_value=True
        )
        assert mturk_fake_creds.set_qualification_score('qid', 'workerid', 4)
        mturk_fake_creds.get_workers_with_qualification.assert_called_once_with('qid')
        mturk_fake_creds.update_qualification_score.assert_called_once_with(
            'qid', 'workerid', 4
        )

    def test_set_qualification_score_with_new_qualification(self, mturk_fake_creds):
        mturk_fake_creds.get_workers_with_qualification = mock.Mock(
            return_value=[]
        )
        mturk_fake_creds.assign_qualification = mock.Mock(
            return_value=True
        )
        assert mturk_fake_creds.set_qualification_score('qid', 'workerid', 4)
        mturk_fake_creds.get_workers_with_qualification.assert_called_once_with('qid')
        mturk_fake_creds.assign_qualification.assert_called_once_with(
            'qid', 'workerid', 4, True
        )
