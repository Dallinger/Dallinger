import datetime
import mock
import pytest
from boto.resultset import ResultSet
from boto.mturk.price import Price
from boto.mturk.connection import HITTypeId
from boto.mturk.connection import HIT
from .conftest import creds_from_environment
from .conftest import skip_if_no_mturk_requestor


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
        'description': 'Test Description',
        'keywords': ['testkw1', 'testkw1'],
        'reward': .01,
        'duration_hours': .25
    }
    defaults.update(**kwargs)

    return defaults


@skip_if_no_mturk_requestor
class TestMTurkService(object):

    def make_one(self, **kwargs):
        from dallinger.mturk import MTurkService
        creds = creds_from_environment()
        creds.update(kwargs)
        return MTurkService(**creds)

    def test_check_credentials_good_credentials(self):
        service = self.make_one()
        is_authenticated = service.check_credentials()

        assert is_authenticated

    def test_check_credentials_bad_credentials(self):
        from boto.mturk.connection import MTurkRequestError
        service = self.make_one(aws_access_key_id='bad', aws_secret_access_key='bad')
        with pytest.raises(MTurkRequestError):
            service.check_credentials()

    def test_check_credentials_no_creds_set_raises(self):
        from dallinger.mturk import MTurkServiceException
        empty_creds = {
            'aws_access_key_id': '',
            'aws_secret_access_key': ''
        }
        service = self.make_one(**empty_creds)

        with pytest.raises(MTurkServiceException):
            service.check_credentials()

    def test_register_hit_type(self):
        config = {
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw1'],
            'reward': .01,
            'duration_hours': .25
        }
        service = self.make_one()
        hit_type_id = service.register_hit_type(**config)

        assert isinstance(hit_type_id, unicode)

    def test_register_notification_url(self):
        config = {
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw1'],
            'reward': .01,
            'duration_hours': .25
        }
        url = 'https://url-of-notification-route'
        service = self.make_one()
        hit_type_id = service.register_hit_type(**config)

        assert service.set_rest_notification(url, hit_type_id) is True

    def test_create_hit(self):
        service = self.make_one()
        hit = service.create_hit(**standard_hit_config())
        assert hit['status'] == 'Assignable'
        assert hit['max_assignments'] == 1

    def test_create_hit_two_assignments(self):
        service = self.make_one()
        hit = service.create_hit(**standard_hit_config(max_assignments=2))
        assert hit['status'] == 'Assignable'
        assert hit['max_assignments'] == 2

    def test_extend_hit_with_valid_hit_id(self):
        service = self.make_one()
        hit = service.create_hit(**standard_hit_config())

        updated = service.extend_hit(hit['id'], number=1, duration_hours=.25)

        assert updated['max_assignments'] == 2
        clock_skew = .01
        expected_extension = datetime.timedelta(hours=.25 - clock_skew)
        assert updated['expiration'] >= hit['expiration'] + expected_extension

    def test_extend_hit_with_invalid_hit_id_raises(self):
        from boto.mturk.connection import MTurkRequestError
        service = self.make_one()
        with pytest.raises(MTurkRequestError):
            service.extend_hit('dud', number=1, duration_hours=.25)



class TestMTurkServiceWithFakeConnection(object):

    def make_one(self, **kwargs):
        from dallinger.mturk import MTurkService
        creds = {
            'aws_access_key_id': 'fake key id',
            'aws_secret_access_key': 'fake secret'
        }
        creds.update(kwargs)
        service = MTurkService(**creds)
        return service

    def test_is_sandbox_by_default(self):
        service = self.make_one()
        assert service.is_sandbox

    def test_host_server_is_sandbox_by_default(self):
        service = self.make_one()
        assert 'sandbox' in service.host

    def test_check_credentials_converts_response_to_boolean_true(self):
        service = self.make_one()
        mock_mtc = mock.Mock(
            **{'get_account_balance.return_value': fake_balance_response()}
        )
        service._connection = mock_mtc
        assert service.check_credentials() is True

    def test_check_credentials_calls_get_account_balance(self):
        service = self.make_one()
        mock_mtc = mock.Mock(
            **{'get_account_balance.return_value': fake_balance_response()}
        )
        service._connection = mock_mtc
        service.check_credentials()
        service._connection.get_account_balance.assert_called_once()

    def test_check_credentials_bad_credentials(self):
        from boto.mturk.connection import MTurkRequestError
        service = self.make_one()
        mock_mtc = mock.Mock(
            **{'get_account_balance.side_effect': MTurkRequestError(1, 'ouch')}
        )
        service._connection = mock_mtc
        with pytest.raises(MTurkRequestError):
            service.check_credentials()

    def test_check_credentials_no_creds_set_raises(self):
        from dallinger.mturk import MTurkServiceException
        empty_creds = {
            'aws_access_key_id': '',
            'aws_secret_access_key': ''
        }
        service = self.make_one(**empty_creds)

        with pytest.raises(MTurkServiceException):
            service.check_credentials()

    def test_register_hit_type(self):
        config = {
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw2'],
            'reward': .01,
            'duration_hours': .25
        }
        service = self.make_one()
        mock_config = {
            'get_account_balance.return_value': fake_balance_response(),
            'register_hit_type.return_value': fake_hit_type_response(),
        }
        mock_mtc = mock.Mock(**mock_config)
        service._connection = mock_mtc
        service.register_hit_type(**config)

        service._connection.register_hit_type.assert_called_once_with(
            'Test Title',
            'Test Description',
            .01,
            datetime.timedelta(hours=.25),
            keywords=['testkw1', 'testkw2'],
            approval_delay=None,
            qual_req=None
        )

    def test_set_rest_notification(self):
        url = 'https://url-of-notification-route'
        hit_type_id = 'fake hittype id'
        service = self.make_one()
        mock_config = {
            'set_rest_notification.return_value': ResultSet(),
        }
        mock_mtc = mock.Mock(**mock_config)
        service._connection = mock_mtc

        service.set_rest_notification(url, hit_type_id)

        service._connection.set_rest_notification.assert_called_once()

    def test_create_hit_calls_underlying_mturk_method(self):
        service = self.make_one()
        mock_config = {
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response()
        }
        mock_mtc = mock.Mock(**mock_config)
        service._connection = mock_mtc
        service.create_hit(**standard_hit_config())

        service._connection.create_hit.assert_called_once()

    def test_create_hit_translates_response_back_from_mturk(self):
        service = self.make_one()
        mock_config = {
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response()
        }
        mock_mtc = mock.Mock(**mock_config)
        service._connection = mock_mtc
        hit = service.create_hit(**standard_hit_config())
        assert hit['max_assignments'] == 1
        assert hit['reward'] == .01
        assert hit['keywords'] == ['testkw1', 'testkw2']
        assert isinstance(hit['created'], datetime.datetime)
        assert isinstance(hit['expiration'], datetime.datetime)
