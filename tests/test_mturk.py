import datetime
import mock
import os
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
from dallinger.mturk import MTurkService
from dallinger.mturk import MTurkServiceException
from dallinger.utils import generate_random_id


TEST_HIT_DESCRIPTION = '***TEST SUITE HIT***'
TEST_QUALIFICATION_DESCRIPTION = '***TEST SUITE QUALIFICATION***'


class FixtureConfigurationError(Exception):
    """To clarify that the error is with test configuration,
    not production code.
    """


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
        'QualificationTypeId': generate_random_id(size=32),
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
        'QualificationTypeId': generate_random_id(size=32),
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
        'description': TEST_HIT_DESCRIPTION + str(os.getpid()),
        'keywords': ['testkw1', 'testkw1'],
        'reward': .01,
        'duration_hours': .25
    }
    defaults.update(**kwargs)

    return defaults


@pytest.fixture
def mturk(aws_creds):
    service = MTurkService(**aws_creds)
    return service


@pytest.fixture
def with_cleanup(aws_creds, request):

    # tear-down: clean up all specially-marked HITs:
    def test_hits_only(hit):
        return hit['description'] == TEST_HIT_DESCRIPTION + str(os.getpid())

    service = MTurkService(**aws_creds)
    request.instance._qtypes_to_purge = []
    try:
        yield service
    except Exception as e:
        raise e
    finally:
        try:
            for hit in service.get_hits(test_hits_only):
                service.disable_hit(hit['id'])

            # remove QualificationTypes we may have added:
            for qtype_id in request.instance._qtypes_to_purge:
                service.dispose_qualification_type(qtype_id)
        except Exception:
            # Broad exception so we don't leak credentials in Travis CI logs
            pass


@pytest.fixture
def worker_id():
    # Get a worker ID from the environment or tests/config.py
    import os
    workerid = os.getenv('mturk_worker_id')
    if not workerid:
        try:
            from . import config
            workerid = config.mturk_worker_id
        except Exception:
            pass
    if not workerid:
        raise FixtureConfigurationError(
            'No "mturk_worker_id" value found. '
            'Either set this value or skip these tests with '
            '`pytest -m "not mturkworker"`'
        )
    return workerid


class MTurkTestBase(object):

    def _make_qtype(self, mturk, name=None):
        if name is None:
            name = generate_random_id(size=32)

        qtype = mturk.create_qualification_type(
            name=name,
            description=TEST_QUALIFICATION_DESCRIPTION,
            status='Active',
        )
        self._qtypes_to_purge.append(qtype['id'])
        return qtype


@pytest.mark.mturk
class TestMTurkService(MTurkTestBase):

    def test_check_credentials_good_credentials(self, mturk):
        is_authenticated = mturk.check_credentials()
        assert is_authenticated

    def test_check_credentials_bad_credentials(self, mturk):
        mturk.aws_access_key_id = 'fake key id'
        mturk.aws_secret_access_key = 'fake secret'
        with pytest.raises(MTurkRequestError):
            mturk.check_credentials()

    def test_check_credentials_no_creds_set_raises(self, mturk):
        mturk.aws_access_key_id = ''
        mturk.aws_secret_access_key = ''
        with pytest.raises(MTurkServiceException):
            mturk.check_credentials()

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

    def test_create_hit(self, with_cleanup):
        hit = with_cleanup.create_hit(**standard_hit_config())
        assert hit['status'] == 'Assignable'
        assert hit['max_assignments'] == 1

    def test_create_hit_two_assignments(self, with_cleanup):
        hit = with_cleanup.create_hit(**standard_hit_config(max_assignments=2))
        assert hit['status'] == 'Assignable'
        assert hit['max_assignments'] == 2

    def test_create_hit_with_valid_blacklist(self, with_cleanup):
        qtype = self._make_qtype(with_cleanup)
        hit = with_cleanup.create_hit(
            **standard_hit_config(blacklist=[qtype['name']])
        )
        assert hit['status'] == 'Assignable'

    def test_extend_hit_with_valid_hit_id(self, with_cleanup):
        hit = with_cleanup.create_hit(**standard_hit_config())

        updated = with_cleanup.extend_hit(hit['id'], number=1, duration_hours=.25)

        assert updated['max_assignments'] == 2
        clock_skew = .01
        expected_extension = datetime.timedelta(hours=.25 - clock_skew)
        assert updated['expiration'] >= hit['expiration'] + expected_extension

    def test_extend_hit_with_invalid_hit_id_raises(self, mturk):
        with pytest.raises(MTurkRequestError):
            mturk.extend_hit('dud', number=1, duration_hours=.25)

    def test_disable_hit_with_valid_hit_id(self, with_cleanup):
        hit = with_cleanup.create_hit(**standard_hit_config())
        assert with_cleanup.disable_hit(hit['id'])

    def test_disable_hit_with_invalid_hit_id_raises(self, mturk):
        with pytest.raises(MTurkRequestError):
            mturk.disable_hit('dud')

    def test_get_hits_returns_all_by_default(self, with_cleanup):
        hit = with_cleanup.create_hit(**standard_hit_config())

        assert hit in with_cleanup.get_hits()

    def test_get_hits_excludes_based_on_filter(self, with_cleanup):
        hit1 = with_cleanup.create_hit(**standard_hit_config())
        hit2 = with_cleanup.create_hit(**standard_hit_config(title='HIT Two'))
        hits = list(with_cleanup.get_hits(lambda h: 'Two' in h['title']))

        assert hit1 not in hits
        assert hit2 in hits

    def test_create_and_dispose_qualification_type(self, with_cleanup):
        result = with_cleanup.create_qualification_type(
            name=generate_random_id(size=32),
            description=TEST_QUALIFICATION_DESCRIPTION,
            status='Active',
        )

        assert isinstance(result['id'], unicode)
        assert result['status'] == u'Active'
        assert with_cleanup.dispose_qualification_type(result['id'])

    def test_create_qualification_type_with_existing_name_raises(self, with_cleanup):
        qtype = self._make_qtype(with_cleanup)
        with pytest.raises(MTurkRequestError):
            self._make_qtype(with_cleanup, qtype['name'])

    def test_get_qualification_type_by_name_with_valid_name(self, with_cleanup):
        name = generate_random_id(size=32)
        qtype = self._make_qtype(with_cleanup, name=name)
        result = with_cleanup.get_qualification_type_by_name(name)
        assert qtype == result


@pytest.mark.mturk
@pytest.mark.mturkworker
class TestMTurkServiceWithRequesterAndWorker(MTurkTestBase):

    def test_assign_qualification(self, with_cleanup, worker_id):
        qtype = self._make_qtype(with_cleanup)
        assert with_cleanup.assign_qualification(
            qtype['id'], worker_id, score=2, notify=False)

    def test_assign_already_granted_qualification_raises(self, with_cleanup, worker_id):
        qtype = self._make_qtype(with_cleanup)
        with_cleanup.assign_qualification(
            qtype['id'], worker_id, score=2, notify=False
        )

        with pytest.raises(MTurkRequestError):
            with_cleanup.assign_qualification(
                qtype['id'], worker_id, score=2, notify=False)

    def test_update_qualification_score(self, with_cleanup, worker_id):
        qtype = self._make_qtype(with_cleanup)
        with_cleanup.assign_qualification(
            qtype['id'], worker_id, score=2, notify=False)

        with_cleanup.update_qualification_score(
            qtype['id'], worker_id, score=3)

        new_score = with_cleanup.mturk.get_qualification_score(
            qtype['id'], worker_id)[0].IntegerValue
        assert new_score == '3'

    def test_get_workers_with_qualification(self, with_cleanup, worker_id):
        qtype = self._make_qtype(with_cleanup)
        with_cleanup.assign_qualification(
            qtype['id'], worker_id, score=2, notify=False)

        workers = with_cleanup.get_workers_with_qualification(qtype['id'])

        assert worker_id in [w['id'] for w in workers]

    def test_set_qualification_score_with_new_qualification(self, with_cleanup, worker_id):
        qtype = self._make_qtype(with_cleanup)

        with_cleanup.set_qualification_score(
            qtype['id'], worker_id, score=2, notify=False)

        new_score = with_cleanup.mturk.get_qualification_score(
            qtype['id'], worker_id)[0].IntegerValue
        assert new_score == '2'

    def test_set_qualification_score_with_existing_qualification(self, with_cleanup, worker_id):
        qtype = self._make_qtype(with_cleanup)
        with_cleanup.assign_qualification(
            qtype['id'], worker_id, score=2, notify=False)

        with_cleanup.set_qualification_score(
            qtype['id'], worker_id, score=3, notify=False)

        new_score = with_cleanup.mturk.get_qualification_score(
            qtype['id'], worker_id)[0].IntegerValue
        assert new_score == '3'

    def test_assign_qualification_by_name_with_existing_name(self, with_cleanup, worker_id):
        qtype = self._make_qtype(with_cleanup)
        assert with_cleanup.assign_qualification_by_name(
            qtype['name'], worker_id, score=1, notify=False
        )

    def test_assign_qualification_by_name_with_new_name(self, with_cleanup, worker_id):
        name = generate_random_id(size=32)
        assert with_cleanup.assign_qualification_by_name(
            name, worker_id, score=1, notify=False
        )


@pytest.mark.skipif(not pytest.config.getvalue("manual"),
                    reason="--manual was not specified")
class TestBlacklistsManualTesting(MTurkTestBase):

    def test_worker_can_see_hit_when_blacklist_not_in_qualifications(self, with_cleanup, worker_id):
        qtype = self._make_qtype(with_cleanup)
        with_cleanup.assign_qualification(
            qtype['id'], worker_id, score=1, notify=False)

        print 'MANUAL STEP: Check for qualification: "{}". (May be delay)'.format(qtype['name'])
        raw_input("Any key to continue...")

        hit = with_cleanup.create_hit(
            **standard_hit_config(title="Dallinger: No Blacklist"))

        print 'MANUAL STEP: Should be able to see "{}" as available HIT'.format(hit['title'])
        raw_input("Any key to continue...")

    def test_worker_cannot_see_hit_when_blacklist_in_qualifications(self, with_cleanup, worker_id):
        qtype = self._make_qtype(with_cleanup)
        with_cleanup.assign_qualification(
            qtype['id'], worker_id, score=1, notify=False)

        print 'MANUAL STEP: Check for qualification: "{}". (May be delay)'.format(qtype['name'])
        raw_input("Any key to continue...")

        hit = with_cleanup.create_hit(
            **standard_hit_config(
                title="Dallinger: Blacklist",
                blacklist=[qtype['name']]
            )
        )

        print 'MANUAL STEP: Should NOT be able to see "{}"" as available HIT'.format(hit['title'])
        raw_input("Any key to continue...")

        pass


@pytest.fixture
def with_mock():
    creds = {
        'aws_access_key_id': '',
        'aws_secret_access_key': ''
    }
    service = MTurkService(**creds)
    service.mturk = mock.Mock(spec=MTurkConnection)
    return service


class TestMTurkServiceWithFakeConnection(object):

    def test_is_sandbox_by_default(self, with_mock):
        assert with_mock.is_sandbox

    def test_host_server_is_sandbox_by_default(self, with_mock):
        assert 'sandbox' in with_mock.host

    def test_host_server_is_production_if_sandbox_false(self, with_mock):
        with_mock.is_sandbox = False
        assert 'sandbox' not in with_mock.host

    def test_check_credentials_converts_response_to_boolean_true(self, with_mock):
        with_mock.mturk.configure_mock(
            **{'get_account_balance.return_value': fake_balance_response()}
        )
        assert with_mock.check_credentials() is True

    def test_check_credentials_calls_get_account_balance(self, with_mock):
        with_mock.mturk.configure_mock(
            **{'get_account_balance.return_value': fake_balance_response()}
        )
        with_mock.check_credentials()
        with_mock.mturk.get_account_balance.assert_called_once()

    def test_check_credentials_bad_credentials(self, with_mock):
        with_mock.mturk.configure_mock(
            **{'get_account_balance.side_effect': MTurkRequestError(1, 'ouch')}
        )
        with pytest.raises(MTurkRequestError):
            with_mock.check_credentials()

    def test_check_credentials_no_creds_set_raises(self, with_mock):
        creds = {
            'aws_access_key_id': '',
            'aws_secret_access_key': ''
        }
        service = MTurkService(**creds)
        with pytest.raises(MTurkServiceException):
            service.check_credentials()

    def test_register_hit_type(self, with_mock):
        config = {
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw2'],
            'reward': .01,
            'duration_hours': .25
        }
        with_mock.mturk.configure_mock(**{
            'get_account_balance.return_value': fake_balance_response(),
            'register_hit_type.return_value': fake_hit_type_response(),
        })

        with_mock.register_hit_type(**config)

        with_mock.mturk.register_hit_type.assert_called_once_with(
            'Test Title',
            'Test Description',
            .01,
            datetime.timedelta(hours=.25),
            keywords=['testkw1', 'testkw2'],
            approval_delay=None,
            qual_req=None
        )

    def test_set_rest_notification(self, with_mock):
        url = 'https://url-of-notification-route'
        hit_type_id = 'fake hittype id'
        with_mock.mturk.configure_mock(**{
            'set_rest_notification.return_value': ResultSet(),
        })

        with_mock.set_rest_notification(url, hit_type_id)

        with_mock.mturk.set_rest_notification.assert_called_once()

    def test_create_hit_calls_underlying_mturk_method(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response(),
        })

        with_mock.create_hit(**standard_hit_config())

        with_mock.mturk.create_hit.assert_called_once()

    def test_create_hit_translates_response_back_from_mturk(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response(),
        })

        hit = with_mock.create_hit(**standard_hit_config())

        assert hit['max_assignments'] == 1
        assert hit['reward'] == .01
        assert hit['keywords'] == ['testkw1', 'testkw2']
        assert isinstance(hit['created'], datetime.datetime)
        assert isinstance(hit['expiration'], datetime.datetime)

    def test_create_hit_raises_if_returned_hit_not_valid(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'register_hit_type.return_value': fake_hit_type_response(),
            'set_rest_notification.return_value': ResultSet(),
            'create_hit.return_value': fake_hit_response(IsValid='False'),
        })
        with pytest.raises(MTurkServiceException):
            with_mock.create_hit(**standard_hit_config())

    def test_extend_hit(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'extend_hit.return_value': None,
            'get_hit.return_value': fake_hit_response(),
        })

        with_mock.extend_hit(hit_id='hit1', number=2, duration_hours=1.0)

        with_mock.mturk.extend_hit.assert_has_calls([
            mock.call('hit1', expiration_increment=3600),
            mock.call('hit1', assignments_increment=2),
        ])

    def test_disable_hit_simple_passthrough(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'disable_hit.return_value': ResultSet(),
        })

        with_mock.disable_hit('some hit')

        with_mock.mturk.disable_hit.assert_called_once_with('some hit')

    def test_get_hits_returns_all_by_default(self, with_mock):
        hr1 = fake_hit_response(Title='One')[0]
        ht2 = fake_hit_response(Title='Two')[0]

        with_mock.mturk.configure_mock(**{
            'get_all_hits.return_value': as_resultset([hr1, ht2]),
        })

        assert len(list(with_mock.get_hits())) == 2

    def test_get_hits_excludes_based_on_filter(self, with_mock):
        hr1 = fake_hit_response(Title='HIT One')[0]
        ht2 = fake_hit_response(Title='HIT Two')[0]
        with_mock.mturk.configure_mock(**{
            'get_all_hits.return_value': as_resultset([hr1, ht2]),
        })

        hits = list(with_mock.get_hits(lambda h: 'Two' in h['title']))

        assert len(hits) == 1
        assert hits[0]['title'] == 'HIT Two'

    def test_grant_bonus_translates_values_and_calls_wrapped_mturk(self, with_mock):
        fake_assignment = Assignment(None)
        fake_assignment.WorkerId = 'some worker id'
        with_mock.mturk.configure_mock(**{
            'grant_bonus.return_value': ResultSet(),
            'get_assignment.return_value': as_resultset(fake_assignment),
        })

        with_mock.grant_bonus(
            assignment_id='some assignment id',
            amount=2.99,
            reason='above and beyond'
        )

        with_mock.mturk.grant_bonus.assert_called_once_with(
            'some worker id',
            'some assignment id',
            mock.ANY,  # can't compare Price objects :-(
            'above and beyond'
        )

    def test_approve_assignment(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'approve_assignment.return_value': ResultSet(),
        })

        assert with_mock.approve_assignment('fake id') is True
        with_mock.mturk.approve_assignment.assert_called_once_with(
            'fake id', feedback=None
        )

    def test_create_qualification_type(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'create_qualification_type.return_value': fake_qualification_type_response(),
        })
        result = with_mock.create_qualification_type('name', 'desc', 'status')
        with_mock.mturk.create_qualification_type.assert_called_once_with(
            'name', 'desc', 'status'
        )
        assert isinstance(result['created'], datetime.datetime)

    def test_create_qualification_type_raises_if_invalid(self, with_mock):
        response = fake_qualification_type_response()
        response[0].IsValid = 'False'
        with_mock.mturk.configure_mock(**{
            'create_qualification_type.return_value': response,
        })
        with pytest.raises(MTurkServiceException):
            with_mock.create_qualification_type('name', 'desc', 'status')

    def test_assign_qualification(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'assign_qualification.return_value': ResultSet(),
        })
        assert with_mock.assign_qualification('qid', 'worker', 'score')
        with_mock.mturk.assign_qualification.assert_called_once_with(
            'qid', 'worker', 'score', True
        )

    def test_update_qualification_score(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'update_qualification_score.return_value': ResultSet(),
        })
        assert with_mock.update_qualification_score('qid', 'worker', 'score')
        with_mock.mturk.update_qualification_score.assert_called_once_with(
            'qid', 'worker', 'score'
        )

    def test_dispose_qualification_type(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'dispose_qualification_type.return_value': ResultSet(),
        })
        assert with_mock.dispose_qualification_type('qid')
        with_mock.mturk.dispose_qualification_type.assert_called_once_with(
            'qid'
        )

    def test_get_workers_with_qualification(self, with_mock):
        with_mock.mturk.configure_mock(**{
            'get_qualifications_for_qualification_type.side_effect': [
                fake_qualification_response(), ResultSet()
            ],
        })
        expected = [
            mock.call('qid', page_number=1, page_size=100),
            mock.call('qid', page_number=2, page_size=100)
        ]
        # need to unroll the iterator:
        list(with_mock.get_workers_with_qualification('qid'))
        calls = with_mock.mturk.get_qualifications_for_qualification_type.call_args_list
        assert calls == expected

    def test_set_qualification_score_with_existing_qualification(self, with_mock):
        with_mock.get_workers_with_qualification = mock.Mock(
            return_value=[{'id': 'workerid', 'score': 2}]
        )
        with_mock.update_qualification_score = mock.Mock(return_value=True)

        assert with_mock.set_qualification_score('qid', 'workerid', 4)
        with_mock.get_workers_with_qualification.assert_called_once_with('qid')
        with_mock.update_qualification_score.assert_called_once_with(
            'qid', 'workerid', 4
        )

    def test_set_qualification_score_with_new_qualification(self, with_mock):
        with_mock.get_workers_with_qualification = mock.Mock(return_value=[])
        with_mock.assign_qualification = mock.Mock(return_value=True)

        assert with_mock.set_qualification_score('qid', 'workerid', 4)
        with_mock.get_workers_with_qualification.assert_called_once_with('qid')
        with_mock.assign_qualification.assert_called_once_with(
            'qid', 'workerid', 4, True
        )

    def test_assign_qualification_by_name_with_existing_name(self, with_mock):
        with_mock.get_qualification_type_by_name = mock.Mock(return_value={'id': 'qid'})
        with_mock.assign_qualification = mock.Mock(return_value=True)

        assert with_mock.assign_qualification_by_name('foo', 'workerid', 1, False)
        with_mock.get_qualification_type_by_name.assert_called_once_with('foo')
        with_mock.assign_qualification.assert_called_once_with(
            'qid', 'workerid', 1, False
        )

    def test_assign_qualification_by_name_with_new_name(self, with_mock):
        with_mock.get_qualification_type_by_name = mock.Mock(return_value=None)
        with_mock.assign_qualification = mock.Mock(return_value=True)
        with_mock.create_qualification_type = mock.Mock(return_value={'id': 'qid'})

        assert with_mock.assign_qualification_by_name('foo', 'workerid', 1, False)
        with_mock.get_qualification_type_by_name.assert_called_once_with('foo')
        with_mock.create_qualification_type.assert_called_once_with(
            'foo',
            'Dallinger prior experiment experience qualification',
            status='Active'
        )
        with_mock.assign_qualification.assert_called_once_with(
            'qid', 'workerid', 1, False
        )
