import datetime
import mock
import pytest
from boto.resultset import ResultSet
from boto.mturk.price import Price
from boto.mturk.connection import HITTypeId
from boto.mturk.connection import HIT
from boto.mturk.connection import MTurkRequestError
from .conftest import skip_if_no_mturk_requestor
from dallinger.mturk import MTurkService
from dallinger.mturk import MTurkServiceException


TEST_HIT_DESCRIPTION = '***TEST SUITE HIT***'


def fake_balance_response():
    result = ResultSet()
    result.append(Price(1.00))
    return result


def fake_hit_type_response():
    result = ResultSet()
    htid = HITTypeId(None)
    htid.HITTypeId = u'fake HITTypeId'
    result.append(htid)
    return result


def fake_hit_response():
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
    hit = HIT(None)
    for k, v in canned_response.items():
        hit.endElement(k, v, None)
    result = ResultSet()
    result.append(hit)
    return result


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
def mturk_with_cleanup(creds_from_environment):
    creds = creds_from_environment
    service = MTurkService(**creds)
    yield service

    # tear-down: clean up all specially-marked HITs:
    def test_hits_only(hit):
        return hit['description'] == TEST_HIT_DESCRIPTION

    for hit in service.get_hits(test_hits_only):
        service.disable_hit(hit['id'])


@skip_if_no_mturk_requestor
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


class TestMTurkServiceWithFakeConnection(object):

    def test_is_sandbox_by_default(self, mturk_fake_creds):
        assert mturk_fake_creds.is_sandbox

    def test_host_server_is_sandbox_by_default(self, mturk_fake_creds):
        assert 'sandbox' in mturk_fake_creds.host

    def test_check_credentials_converts_response_to_boolean_true(self, mturk_fake_creds):
        mock_mtc = mock.Mock(
            **{'get_account_balance.return_value': fake_balance_response()}
        )
        mturk_fake_creds.mturk = mock_mtc
        assert mturk_fake_creds.check_credentials() is True

    def test_check_credentials_calls_get_account_balance(self, mturk_fake_creds):
        mock_mtc = mock.Mock(
            **{'get_account_balance.return_value': fake_balance_response()}
        )
        mturk_fake_creds.mturk = mock_mtc
        mturk_fake_creds.check_credentials()
        mturk_fake_creds.mturk.get_account_balance.assert_called_once()

    def test_check_credentials_bad_credentials(self, mturk_fake_creds):
        mock_mtc = mock.Mock(
            **{'get_account_balance.side_effect': MTurkRequestError(1, 'ouch')}
        )
        mturk_fake_creds.mturk = mock_mtc
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
        mock_config = {
            'get_account_balance.return_value': fake_balance_response(),
            'register_hit_type.return_value': fake_hit_type_response(),
        }
        mock_mtc = mock.Mock(**mock_config)
        mturk_fake_creds.mturk = mock_mtc
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
        mock_config = {
            'set_rest_notification.return_value': ResultSet(),
        }
        mock_mtc = mock.Mock(**mock_config)
        mturk_fake_creds.mturk = mock_mtc

        mturk_fake_creds.set_rest_notification(url, hit_type_id)

        mturk_fake_creds.mturk.set_rest_notification.assert_called_once()

    def test_create_hit_calls_underlying_mturk_method(self, mturk_fake_creds):
        mock_config = {
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response()
        }
        mock_mtc = mock.Mock(**mock_config)
        mturk_fake_creds.mturk = mock_mtc
        mturk_fake_creds.create_hit(**standard_hit_config())

        mturk_fake_creds.mturk.create_hit.assert_called_once()

    def test_create_hit_translates_response_back_from_mturk(self, mturk_fake_creds):
        mock_config = {
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response()
        }
        mock_mtc = mock.Mock(**mock_config)
        mturk_fake_creds.mturk = mock_mtc
        hit = mturk_fake_creds.create_hit(**standard_hit_config())
        assert hit['max_assignments'] == 1
        assert hit['reward'] == .01
        assert hit['keywords'] == ['testkw1', 'testkw2']
        assert isinstance(hit['created'], datetime.datetime)
        assert isinstance(hit['expiration'], datetime.datetime)

    def test_approve_assignment(self):
        service = self.make_one()
        mock_config = {
            'approve_assignment.returns': ResultSet(),
        }
        service._connection = mock.Mock(**mock_config)
        assert service.approve_assignment('fake id') is True
