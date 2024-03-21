import datetime
import hmac
import os
import socket
import time
from hashlib import sha1
from unittest import mock

import pytest
import six
from botocore.exceptions import ClientError
from six.moves import input
from tzlocal import get_localzone

from dallinger.mturk import (
    DuplicateQualificationNameError,
    MTurkQualificationRequirements,
    MTurkQuestions,
    MTurkService,
    MTurkServiceException,
    QualificationNotFoundException,
    RevokedQualification,
    SNSService,
    WorkerLacksQualification,
)
from dallinger.utils import generate_random_id

TEST_HIT_DESCRIPTION = "***TEST SUITE HIT***"
TEST_QUALIFICATION_DESCRIPTION = "***TEST SUITE QUALIFICATION***"
STANDARD_WAIT_SECS = 15
MAX_MTURK_RERUNS = 1
if os.environ.get("CI"):
    MAX_MTURK_RERUNS = 3


class FixtureConfigurationError(Exception):
    """To clarify that the error is with test configuration,
    not production code.
    """


@pytest.fixture(scope="session")
def test_session_desc():
    # Create a string key at the beginning of a test session that can
    # be used to mark all HITs created during the session. This allows
    # test cleanup to remove just the HITs it created, in case CI (or
    # another developer) is running another tests session at the same time
    identifier = datetime.datetime.now().isoformat().encode("utf-8")
    key = hmac.new(identifier, digestmod=sha1).hexdigest()

    return ":".join([TEST_HIT_DESCRIPTION, key])


def name_with_hostname_prefix():
    # Including the hostname in content created in the MTurk sandbox helps
    # identify its source when reviewing records there.
    hostname = socket.gethostname()
    name = "{}:{}".format(hostname, generate_random_id(size=32))
    return name


def response_metadata():
    # Most successful requests return an element like this in the JSON.
    # In cases where there is no real return value, this is likely the only
    # content in the response.
    return {
        "ResponseMetadata": {
            "HTTPHeaders": {
                "content-length": "123",
                "content-type": "application/x-amz-json-1.1",
                "date": "Thu, 08 Feb 2018 01:00:48 GMT",
                "x-amzn-requestid": "806337c8-0c6b-11e8-9668-91a85782438a",
            },
            "HTTPStatusCode": 200,
            "RequestId": "806337c8-0c6b-11e8-9668-91a85782438a",
            "RetryAttempts": 0,
        }
    }


def as_batch_responses(key, things):
    # Several MTurk calls return results in batches, with a "NextToken"
    # indicating there is more content to be retrieved with a subsequent call.
    if not isinstance(things, (list, tuple)):
        things = [things]

    canned_response = [
        {
            "NextToken": "FAKE_NEXT_TOKEN",
            "NumResults": len(things),
            key: things,
            "ResponseMetadata": response_metadata()["ResponseMetadata"],
        },
        {
            "NumResults": 0,
            key: [],
            "ResponseMetadata": response_metadata()["ResponseMetadata"],
        },
    ]

    return canned_response


def fake_balance_response():
    return {
        "AvailableBalance": "10000.00",
        "ResponseMetadata": response_metadata()["ResponseMetadata"],
    }


def fake_hit_type_response():
    return {
        "HITTypeId": six.text_type(generate_random_id(size=32)),
        "ResponseMetadata": response_metadata()["ResponseMetadata"],
    }


def fake_hit_response(**kwargs):
    tz = get_localzone()
    canned_response = {
        "HIT": {
            "AssignmentDurationInSeconds": 900,
            "AutoApprovalDelayInSeconds": 0,
            "CreationTime": datetime.datetime(2018, 1, 1, 1, 26, 52, 54000).replace(
                tzinfo=tz
            ),
            "Description": "***TEST SUITE HIT***43683",
            "Expiration": datetime.datetime(2018, 1, 1, 1, 27, 26, 54000).replace(
                tzinfo=tz
            ),
            "HITGroupId": "36IAL8HYPYM1MDNBSTAEZW89WH74RJ",
            "HITId": "3X7837UUADRXYCA1K7JAJLKC66DJ60",
            "HITReviewStatus": "NotReviewed",
            "HITStatus": "Assignable",
            "HITTypeId": "3V76OXST9SAE3THKN85FUPK7730050",
            "Keywords": "testkw1,testkw2",
            "MaxAssignments": 1,
            "NumberOfAssignmentsAvailable": 1,
            "NumberOfAssignmentsCompleted": 0,
            "NumberOfAssignmentsPending": 0,
            "QualificationRequirements": [
                {
                    "Comparator": "GreaterThanOrEqualTo",
                    "IntegerValues": [95],
                    "QualificationTypeId": "000000000000000000L0",
                    "RequiredToPreview": True,
                },
                {
                    "Comparator": "EqualTo",
                    "LocaleValues": [{"Country": "US"}],
                    "QualificationTypeId": "00000000000000000071",
                    "RequiredToPreview": True,
                },
            ],
            "Question": (
                '<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/'
                'AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">'
                "<ExternalURL>https://www.example.com/ad</ExternalURL>"
                "<FrameHeight>600</FrameHeight>"
                "</ExternalQuestion>"
            ),
            "Reward": "0.01",
            "Title": "Test Title",
        },
        "ResponseMetadata": response_metadata()["ResponseMetadata"],
    }
    canned_response["HIT"].update(kwargs)

    return canned_response


def fake_list_hits_responses(hits=None):
    if hits is None:
        hits = [fake_hit_response()]

    return as_batch_responses(key="HITs", things=[h["HIT"] for h in hits])


def fake_worker_qualification_response():
    tz = get_localzone()
    canned_response = {
        "Qualification": {
            "GrantTime": datetime.datetime(2018, 1, 1).replace(tzinfo=tz),
            "IntegerValue": 2,
            "QualificationTypeId": six.text_type(generate_random_id(size=32)),
            "Status": "Granted",
            "WorkerId": "FAKE_WORKER_ID",
        },
        "ResponseMetadata": response_metadata()["ResponseMetadata"],
    }

    return canned_response


def fake_list_worker_qualification_responses(quals=None):
    if quals is None:
        quals = [fake_worker_qualification_response()]

    return as_batch_responses(
        key="Qualifications", things=[q["Qualification"] for q in quals]
    )


def fake_qualification_type_response():
    tz = get_localzone()
    canned_response = {
        "QualificationType": {
            "AutoGranted": False,
            "CreationTime": datetime.datetime(2018, 1, 1).replace(tzinfo=tz),
            "Description": "***TEST SUITE QUALIFICATION***",
            "IsRequestable": True,
            "Name": "Test Qualification",
            "QualificationTypeId": generate_random_id(size=32),
            "QualificationTypeStatus": "Active",
        }
    }
    return canned_response


def fake_list_qualification_types_responses(qtypes=None):
    if qtypes is None:
        qtypes = [fake_qualification_type_response()]

    return as_batch_responses(
        key="QualificationTypes", things=[q["QualificationType"] for q in qtypes]
    )


def fake_get_assignment_response():
    tz = get_localzone()
    hit = fake_hit_response()["HIT"]
    return {
        "Assignment": {
            "AssignmentId": "FAKE_ASSIGNMENT_ID",
            "WorkerId": "FAKE_WORKER_ID",
            "HITId": hit["HITId"],
            "AssignmentStatus": "Approved",
            "AutoApprovalTime": datetime.datetime(2018, 1, 1).replace(tzinfo=tz),
            "AcceptTime": datetime.datetime(2018, 1, 1).replace(tzinfo=tz),
            "SubmitTime": datetime.datetime(2018, 1, 1).replace(tzinfo=tz),
            "ApprovalTime": datetime.datetime(2018, 1, 1).replace(tzinfo=tz),
            "RejectionTime": datetime.datetime(2018, 1, 1).replace(tzinfo=tz),
            "Deadline": datetime.datetime(2018, 1, 1).replace(tzinfo=tz),
            "Answer": "",
            "RequesterFeedback": "",
        },
        "HIT": hit,
    }


@pytest.fixture
def hit_config(test_session_desc):
    def configmaker(**kw):
        defaults = {
            "experiment_id": "some-experiment-id",
            "lifetime_days": 0.0004,  # 34 seconds (30 is minimum)
            "max_assignments": 1,
            "notification_url": "https://www.example.com/notifications",
            "title": "Test Title",
            "keywords": ["testkw1", "testkw2"],
            "reward": 0.01,
            "question": MTurkQuestions.external(ad_url="https://www.example.com/ad"),
            "duration_hours": 0.25,
            "qualifications": [
                MTurkQualificationRequirements.min_approval(95),
                MTurkQualificationRequirements.restrict_to_countries(["US"]),
            ],
            "do_subscribe": False,
        }
        defaults.update(**kw)
        # Use fixed description, since this is how we clean up:
        defaults["description"] = test_session_desc

        return defaults

    return configmaker


@pytest.fixture
def mturk(aws_creds):
    params = {"region_name": "us-east-1"}
    params.update(aws_creds)
    service = MTurkService(**params)

    return service


@pytest.fixture
def with_cleanup(aws_creds, request, test_session_desc):
    # tear-down: clean up all specially-marked HITs:
    def test_hits_only(hit):
        return hit["description"] == test_session_desc

    # In tests we do a lot of querying of Qualifications we only just created,
    # so we need a long time-out
    params = {"region_name": "us-east-1", "max_wait_secs": 60}
    params.update(aws_creds)
    service = MTurkService(**params)
    service.sns = mock.Mock(spec=SNSService)
    service.sns.create_subscription.return_value = None

    try:
        yield service
    except Exception as e:
        raise e
    finally:
        try:
            for hit in service.get_hits(test_hits_only):
                service.mturk.delete_hit(HITId=hit["id"])
        except Exception:
            # Broad exception so we don't leak credentials in Travis CI logs
            print("Something went wrong in test HIT cleanup!!!")


@pytest.fixture(scope="class")
def worker_id():
    # Get a worker ID from the environment or tests/config.py
    import os

    workerid = os.getenv("mturk_worker_id")
    if not workerid:
        try:
            from . import config

            workerid = config.mturk_worker_id
        except Exception:
            pass
    if not workerid:
        raise FixtureConfigurationError(
            'No "mturk_worker_id" value found. '
            "Either set this value or skip these tests with "
            '`pytest -m "not mturkworker"`'
        )
    return workerid


@pytest.fixture
def qtype(mturk):
    # build
    name = name_with_hostname_prefix()
    qtype = mturk.create_qualification_type(
        name=name, description=TEST_QUALIFICATION_DESCRIPTION, status="Active"
    )

    yield qtype

    # clean up
    mturk.dispose_qualification_type(qtype["id"])


@pytest.fixture
def sns(aws_creds):
    params = {"region_name": "us-east-1", "confirm": False}
    params.update(aws_creds)
    service = SNSService(**params)

    return service


@pytest.fixture
def sns_iso(sns):
    mocked_sns = mock.Mock(spec=sns._sns)
    mocked_sns.create_topic.return_value = {"TopicArn": "fake-topic-arn"}
    mocked_sns.subscribe.return_value = {"SubscriptionArn": "fake-subscription-arn"}
    mocked_sns.get_subscription_attributes.return_value = {
        "Attributes": {"PendingConfirmation": "false"}
    }
    mocked_sns.list_topics.return_value = {
        "Topics": [{"TopicArn": "long-prefix:some-experiment-id"}]
    }
    sns._sns = mocked_sns

    return sns


@pytest.mark.mturk
@pytest.mark.usefixtures("check_mturkfull")
class TestSNSService(object):
    def test_creates_and_cancel_subscription(self, sns):
        always_returns_200OK = "https://www.example.com/makebelieve-endpoint"
        topic_arn = sns.create_subscription("some-exp", always_returns_200OK)

        assert topic_arn.endswith(":some-exp")
        assert sns.cancel_subscription("some-exp")

    def test_cancel_nonexistent_subscription_raises(self, sns):
        from dallinger.mturk import NonExistentSubscription

        with pytest.raises(NonExistentSubscription):
            sns.cancel_subscription("some-exp")


class TestSNSServiceIsolation(object):
    def test_create_subscription(self, sns_iso):
        sns_iso.create_subscription("some-exp", "https://some-url")

        sns_iso._sns.create_topic.assert_called_once_with(Name="some-exp")
        sns_iso._sns.subscribe.assert_called_once_with(
            Endpoint="https://some-url",
            Protocol="https",
            ReturnSubscriptionArn=True,
            TopicArn="fake-topic-arn",
        )

    def test_cancel_subscription(self, sns_iso):
        sns_iso.cancel_subscription("some-experiment-id")

        sns_iso._sns.delete_topic.assert_called_once_with(
            TopicArn="long-prefix:some-experiment-id"
        )


@pytest.mark.mturk
@pytest.mark.mturkworker
@pytest.mark.slow
class TestMTurkServiceIntegrationSmokeTest(object):
    """Hits about 75% of the MTurkService class with actual boto.mturk network
    calls. For comprehensive system tests, run with the --mturkfull option.
    """

    @pytest.mark.flaky(reruns=MAX_MTURK_RERUNS)
    def test_create_hit_lifecycle(self, with_cleanup, qtype, hit_config, worker_id):
        result = with_cleanup.get_qualification_type_by_name(qtype["name"])
        assert qtype == result

        with_cleanup.assign_qualification(qtype["id"], worker_id, score=2)

        workers = with_cleanup.get_workers_with_qualification(qtype["id"])

        assert worker_id in [w["id"] for w in workers]

        result = with_cleanup.increment_named_qualification_score(
            qtype["name"], worker_id
        )

        assert result["score"] == 3

        qualifications = (MTurkQualificationRequirements.must_have(qtype["id"]),)

        config = hit_config(
            max_assignments=2,
            annotation="test-annotation",
            qualifications=qualifications,
        )
        hit = with_cleanup.create_hit(**config)
        assert hit["status"] == "Assignable"
        assert hit["max_assignments"] == 2
        assert hit["annotation"] == "test-annotation"

        # There is a lag before extension is possible
        sleep_secs = 2
        max_wait = 60
        time.sleep(sleep_secs)
        start = time.time()
        updated = None
        while not updated and time.time() - start < max_wait:
            try:
                updated = with_cleanup.extend_hit(
                    hit["id"], number=1, duration_hours=0.25
                )
            except MTurkServiceException:
                time.sleep(sleep_secs)

        if updated is None:
            pytest.fail("HIT was never updated")
        else:
            assert updated["max_assignments"] == 3
        assert with_cleanup.disable_hit(
            hit_id=hit["id"], experiment_id=config["experiment_id"]
        )


@pytest.mark.mturk
@pytest.mark.usefixtures("check_mturkfull")
class TestMTurkService(object):
    def loop_until_2_quals(self, mturk_helper, query):
        args = {
            "Query": query,
            "MustBeRequestable": False,
            "MustBeOwnedByCaller": True,
            "MaxResults": 2,
        }
        while (
            len(
                mturk_helper.mturk.list_qualification_types(**args)[
                    "QualificationTypes"
                ]
            )
            < 2
        ):
            time.sleep(1)
        return True

    def test_account_balance(self, mturk):
        balance = mturk.account_balance()
        assert balance == 10000.0

    def test_check_credentials_good_credentials(self, mturk):
        is_authenticated = mturk.check_credentials()
        assert is_authenticated

    @pytest.mark.xfail(
        condition=bool(os.environ.get("CI", False)),
        reason="Fails on CI for unknown reason",
    )
    def test_check_credentials_no_creds_set_raises(self, mturk):
        mturk.aws_key = ""
        mturk.aws_secret = ""
        with pytest.raises(MTurkServiceException):
            mturk.check_credentials()

    def test_check_credentials_bad_credentials(self, mturk):
        mturk.aws_key = "fake key id"
        mturk.aws_secret = "fake secret"
        with pytest.raises(MTurkServiceException):
            mturk.check_credentials()

    def test_create_hit_with_annotation_and_qualification(
        self, with_cleanup, qtype, hit_config
    ):
        qual = MTurkQualificationRequirements.must_not_have(
            qualification_id=qtype["id"]
        )
        hit = with_cleanup.create_hit(
            **hit_config(annotation="test-exp-id", qualifications=[qual])
        )
        assert hit["status"] == "Assignable"
        assert hit["max_assignments"] == 1
        assert hit["annotation"] == "test-exp-id"
        assert hit["qualification_type_ids"] == [qtype["id"]]

    def test_create_hit_two_assignments(self, with_cleanup, hit_config):
        hit = with_cleanup.create_hit(**hit_config(max_assignments=2))
        assert hit["status"] == "Assignable"
        assert hit["max_assignments"] == 2

    def test_create_compensation_hit(self, with_cleanup, hit_config):
        # In practice, this would include a qualification assigned to a
        # single worker.
        hit = with_cleanup.create_hit(
            **hit_config(
                title="Compensation Immediate",
                question=MTurkQuestions.compensation(sandbox=True),
            )
        )
        assert hit["status"] == "Assignable"
        assert hit["max_assignments"] == 1

    def test_extend_hit_with_valid_hit_id(self, with_cleanup, hit_config):
        hit = with_cleanup.create_hit(**hit_config())
        time.sleep(STANDARD_WAIT_SECS)  # Time lag before HIT is available for extension
        updated = with_cleanup.extend_hit(hit["id"], number=1, duration_hours=0.25)

        assert updated["max_assignments"] == 2
        clock_skew = 0.01
        expected_extension = datetime.timedelta(hours=0.25 - clock_skew)
        assert updated["expiration"] >= hit["expiration"] + expected_extension

    def test_extend_hit_with_invalid_hit_id_raises(self, mturk):
        with pytest.raises(MTurkServiceException):
            mturk.extend_hit("dud", number=1, duration_hours=0.25)

    def test_disable_hit_with_valid_hit_ids(self, with_cleanup, hit_config):
        hit = with_cleanup.create_hit(**hit_config())
        time.sleep(STANDARD_WAIT_SECS)
        assert with_cleanup.disable_hit(hit["id"], "some-experiment-id")

    def test_disable_hit_with_invalid_hit_id_raises(self, mturk):
        with pytest.raises(MTurkServiceException):
            mturk.disable_hit("dud", "some-experiment-id")

    def test_get_hit_with_valid_hit_id(self, with_cleanup, hit_config):
        hit = with_cleanup.create_hit(**hit_config())
        retrieved = with_cleanup.get_hit(hit["id"])
        assert hit == retrieved

    def test_get_hits_returns_all_by_default(self, with_cleanup, hit_config):
        hit = with_cleanup.create_hit(**hit_config())
        time.sleep(STANDARD_WAIT_SECS)  # Indexing required...
        hit_ids = [h["id"] for h in with_cleanup.get_hits()]
        assert hit["id"] in hit_ids

    def test_get_hits_excludes_based_on_filter(self, with_cleanup, hit_config):
        hit1 = with_cleanup.create_hit(**hit_config())
        hit2 = with_cleanup.create_hit(**hit_config(title="HIT Two"))
        time.sleep(STANDARD_WAIT_SECS)  # Indexing required...
        hit_ids = [
            h["id"] for h in with_cleanup.get_hits(lambda h: "Two" in h["title"])
        ]
        assert hit1["id"] not in hit_ids
        assert hit2["id"] in hit_ids

    def test_create_and_dispose_qualification_type(self, with_cleanup):
        result = with_cleanup.create_qualification_type(
            name=generate_random_id(size=32),
            description=TEST_QUALIFICATION_DESCRIPTION,
            status="Active",
        )

        assert isinstance(result["id"], six.text_type)
        assert result["status"] == "Active"
        assert with_cleanup.dispose_qualification_type(result["id"])

    def test_create_qualification_type_with_existing_name_raises(
        self, with_cleanup, qtype
    ):
        with pytest.raises(DuplicateQualificationNameError):
            with_cleanup.create_qualification_type(qtype["name"], "desc", "Active")

    def test_get_qualification_type_by_name_with_valid_name(self, with_cleanup, qtype):
        result = with_cleanup.get_qualification_type_by_name(qtype["name"])
        assert qtype == result

    def test_get_qualification_type_by_name_no_match(self, with_cleanup, qtype):
        # First query can be very slow, since the qtype was just added:
        with_cleanup.max_wait_secs = 0
        result = with_cleanup.get_qualification_type_by_name("nonsense")
        assert result is None

    def test_get_qualification_type_by_name_returns_shortest_if_multi(
        self, with_cleanup, qtype
    ):
        substr_name = qtype["name"][:-1]  # one char shorter name
        qtype2 = with_cleanup.create_qualification_type(
            name=substr_name,
            description=TEST_QUALIFICATION_DESCRIPTION,
            status="Active",
        )
        self.loop_until_2_quals(with_cleanup, substr_name)  # wait for indexing
        result = with_cleanup.get_qualification_type_by_name(substr_name)
        assert result["id"] == qtype2["id"]
        with_cleanup.dispose_qualification_type(qtype2["id"])

    def test_get_qualification_type_by_name_must_match_exact_if_multi(
        self, with_cleanup, qtype
    ):
        substr_name = qtype["name"][:-1]  # one char shorter name
        qtype2 = with_cleanup.create_qualification_type(
            name=substr_name,
            description=TEST_QUALIFICATION_DESCRIPTION,
            status="Active",
        )
        self.loop_until_2_quals(with_cleanup, substr_name)  # wait for indexing
        not_exact = substr_name[:-1]
        with pytest.raises(MTurkServiceException):
            with_cleanup.get_qualification_type_by_name(not_exact)

        with_cleanup.dispose_qualification_type(qtype2["id"])


@pytest.mark.mturk
@pytest.mark.mturkworker
@pytest.mark.usefixtures("check_mturkfull")
@pytest.mark.slow
class TestMTurkServiceWithRequesterAndWorker(object):
    def test_can_assign_new_qualification(self, with_cleanup, worker_id, qtype):
        assert with_cleanup.assign_qualification(qtype["id"], worker_id, score=2)
        assert with_cleanup.current_qualification_score(qtype["id"], worker_id) == 2

    def test_can_update_existing_qualification(self, with_cleanup, worker_id, qtype):
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=2)
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=3)

        assert with_cleanup.current_qualification_score(qtype["id"], worker_id) == 3

    def test_getting_invalid_qualification_score_raises(self, with_cleanup, worker_id):
        with pytest.raises(MTurkServiceException) as execinfo:
            with_cleanup.current_qualification_score("NONEXISTENT", worker_id)
        assert execinfo.match(
            "Worker {} does not have qualification NONEXISTENT".format(worker_id)
        )

    def test_retrieving_revoked_qualifications_raises(
        self, with_cleanup, worker_id, qtype
    ):
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=2)
        with_cleanup.revoke_qualification(qtype["id"], worker_id)

        with pytest.raises(MTurkServiceException):
            with_cleanup.current_qualification_score(qtype["id"], worker_id)

    def test_get_workers_with_qualification(self, with_cleanup, worker_id, qtype):
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=2)
        workers = with_cleanup.get_workers_with_qualification(qtype["id"])

        assert worker_id in [w["id"] for w in workers]

    def test_current_named_qualification_score(self, with_cleanup, worker_id, qtype):
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=2)

        result = with_cleanup.current_named_qualification_score(
            qtype["name"], worker_id
        )

        assert result["qtype"]["id"] == qtype["id"]
        assert result["score"] == 2

    def test_current_named_qualification_score_worker_unscored(
        self, with_cleanup, worker_id, qtype
    ):
        result = with_cleanup.current_named_qualification_score(
            qtype["name"], worker_id
        )

        assert result["qtype"]["id"] == qtype["id"]
        assert result["score"] is None

    def test_current_named_qualification_score_invalid_worker_raises(
        self, with_cleanup, qtype
    ):
        with pytest.raises(MTurkServiceException):
            with_cleanup.current_named_qualification_score(qtype["name"], "nonsense")

    def test_current_named_qualification_score_is_none_for_revoked_qualifications(
        self, with_cleanup, worker_id, qtype
    ):
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=2)
        with_cleanup.revoke_qualification(qtype["id"], worker_id)

        result = with_cleanup.current_named_qualification_score(
            qtype["name"], worker_id
        )

        assert result["qtype"]["id"] == qtype["id"]
        assert result["score"] is None

    def test_increment_named_qualification_score(self, with_cleanup, worker_id, qtype):
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=2)
        result = with_cleanup.increment_named_qualification_score(
            qtype["name"], worker_id
        )

        assert result["qtype"]["id"] == qtype["id"]
        assert result["score"] == 3

    def test_increment_named_qualification_score_worker_unscored(
        self, with_cleanup, worker_id, qtype
    ):
        result = with_cleanup.increment_named_qualification_score(
            qtype["name"], worker_id
        )

        assert result["qtype"]["id"] == qtype["id"]
        assert result["score"] == 1

    def test_increment_named_qualification_score_for_revoked_qualification(
        self, with_cleanup, worker_id, qtype
    ):
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=2)
        with_cleanup.revoke_qualification(qtype["id"], worker_id)
        result = with_cleanup.increment_named_qualification_score(
            qtype["name"], worker_id
        )

        assert result["qtype"]["id"] == qtype["id"]
        assert result["score"] == 1

    def test_increment_named_qualification_score_nonexistent_qual(
        self, with_cleanup, worker_id
    ):
        # we know the name doesn't exist, so no need to wait
        with_cleanup.max_wait_secs = 0
        with pytest.raises(QualificationNotFoundException):
            with_cleanup.increment_named_qualification_score("NONEXISTENT", worker_id)


@pytest.mark.mturk
@pytest.mark.mturkworker
@pytest.mark.usefixtures("check_manual")
@pytest.mark.slow
class TestInteractive(object):
    def test_worker_can_see_hit_when_blocklist_not_in_qualifications(
        self, with_cleanup, worker_id, qtype, hit_config
    ):
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=1)
        print(
            'MANUAL STEP: Check for qualification: "{}". (May be delay)'.format(
                qtype["name"]
            )
        )
        input("Any key to continue...")

        hit = with_cleanup.create_hit(
            **hit_config(title="Dallinger: No Blocklist", lifetime_days=0.25)
        )

        print(
            'MANUAL STEP: Should be able to see "{}" as available HIT'.format(
                hit["title"]
            )
        )
        input("Any key to continue...")

    def test_worker_cannot_see_hit_when_blocklist_in_qualifications(
        self, with_cleanup, worker_id, qtype, hit_config
    ):
        with_cleanup.assign_qualification(qtype["id"], worker_id, score=1)

        print(
            'MANUAL STEP: Check for qualification: "{}". (May be delay)'.format(
                qtype["name"]
            )
        )
        input("Any key to continue...")

        hit = with_cleanup.create_hit(
            **hit_config(
                title="Dallinger: Blocklist",
                qualifications=[
                    MTurkQualificationRequirements.must_not_have(qtype["id"])
                ],
                lifetime_days=0.25,
            )
        )

        print(
            'MANUAL STEP: Should NOT be able to see "{}"" as available HIT'.format(
                hit["title"]
            )
        )
        input("Any key to continue...")

        pass


@pytest.fixture
def with_mock(mturk):
    mocked_mturk = mock.Mock(spec=mturk.mturk)
    mocked_sns = mock.Mock(spec=mturk.sns)
    mocked_sns.create_subscription.return_value = "fake-topic-arn"

    mturk.mturk = mocked_mturk
    mturk.sns = mocked_sns

    return mturk


class TestMTurkServiceWithFakeConnection(object):
    def test_is_sandbox_by_default(self, with_mock):
        assert with_mock.is_sandbox

    def test_host_server_is_sandbox_by_default(self, with_mock):
        assert "sandbox" in with_mock.host

    def test_host_server_is_production_if_sandbox_false(self, with_mock):
        with_mock.is_sandbox = False
        assert "sandbox" not in with_mock.host

    def test_check_credentials_converts_response_to_boolean_true(self, with_mock):
        with_mock.mturk.configure_mock(
            **{"get_account_balance.return_value": fake_balance_response()}
        )
        assert with_mock.check_credentials() is True

    def test_check_credentials_calls_get_account_balance(self, with_mock):
        with_mock.mturk.configure_mock(
            **{"get_account_balance.return_value": fake_balance_response()}
        )
        with_mock.check_credentials()
        with_mock.mturk.get_account_balance.assert_called_once()

    def test_check_credentials_bad_credentials(self, with_mock):
        with_mock.mturk.configure_mock(
            **{"get_account_balance.side_effect": ClientError({}, "Boom!")}
        )
        with pytest.raises(MTurkServiceException):
            with_mock.check_credentials()

    def test_get_qualification_type_by_name_with_invalid_name_returns_none(
        self, with_mock
    ):
        with_mock.mturk.list_qualification_types.return_value = {
            "QualificationTypes": []
        }
        with_mock.max_wait_secs = 0
        assert with_mock.get_qualification_type_by_name("foo") is None

    def test_get_qualification_type_by_name_raises_if_not_unique_and_not_exact_match(
        self, with_mock
    ):
        two_quals = [
            fake_qualification_type_response(),
            fake_qualification_type_response(),
        ]
        qtypes = fake_list_qualification_types_responses(qtypes=two_quals)
        with_mock.mturk.list_qualification_types.side_effect = qtypes
        with pytest.raises(MTurkServiceException):
            with_mock.get_qualification_type_by_name(
                qtypes[0]["QualificationTypes"][0]["Name"][:6]
            )

    def test_get_qualification_type_by_name_works_if_not_unique_but_is_exact_match(
        self, with_mock
    ):
        two_quals = [
            fake_qualification_type_response(),
            fake_qualification_type_response(),
        ]
        qtypes = fake_list_qualification_types_responses(qtypes=two_quals)
        with_mock.mturk.list_qualification_types.side_effect = qtypes
        name = qtypes[0]["QualificationTypes"][0]["Name"]
        assert with_mock.get_qualification_type_by_name(name)["name"] == name

    def test_get_assignment_converts_result(self, with_mock):
        fake_response = fake_get_assignment_response()
        with_mock.mturk.get_assignment = mock.Mock(return_value=fake_response)

        response = with_mock.get_assignment("some id")

        with_mock.mturk.get_assignment.assert_called_once_with(AssignmentId="some id")
        assert response == {
            "id": fake_response["Assignment"]["AssignmentId"],
            "status": fake_response["Assignment"]["AssignmentStatus"],
            "hit_id": fake_response["Assignment"]["HITId"],
            "worker_id": fake_response["Assignment"]["WorkerId"],
        }

    def test_get_assignment_returns_none_for_invalid_assigment_id(self, with_mock):
        the_flag = "does not exist"
        with_mock.mturk.get_assignment.side_effect = ClientError(
            {}, "blah {} blah".format(the_flag)
        )
        assert with_mock.get_assignment("some id") is None

    def test_create_hit_calls_underlying_mturk_method(self, with_mock, hit_config):
        with_mock.mturk.configure_mock(
            **{
                "create_hit_type.return_value": fake_hit_type_response(),
                "create_hit_with_hit_type.return_value": fake_hit_response(),
            }
        )
        with_mock.create_hit(**hit_config())

        with_mock.mturk.create_hit_with_hit_type.assert_called_once()

    def test_create_hit_translates_response_back_from_mturk(
        self, with_mock, hit_config
    ):
        tz = get_localzone()
        with_mock.mturk.configure_mock(
            **{
                "create_hit_type.return_value": fake_hit_type_response(),
                "create_hit_with_hit_type.return_value": fake_hit_response(),
            }
        )

        hit = with_mock.create_hit(**hit_config())

        assert hit == {
            "annotation": None,
            "assignments_available": 1,
            "assignments_completed": 0,
            "assignments_pending": 0,
            "created": datetime.datetime(2018, 1, 1, 1, 26, 52, 54000).replace(
                tzinfo=tz
            ),
            "description": "***TEST SUITE HIT***43683",
            "expiration": datetime.datetime(2018, 1, 1, 1, 27, 26, 54000).replace(
                tzinfo=tz
            ),
            "id": "3X7837UUADRXYCA1K7JAJLKC66DJ60",
            "keywords": ["testkw1", "testkw2"],
            "max_assignments": 1,
            "qualification_type_ids": ["000000000000000000L0", "00000000000000000071"],
            "review_status": "NotReviewed",
            "reward": 0.01,
            "status": "Assignable",
            "title": "Test Title",
            "type_id": "3V76OXST9SAE3THKN85FUPK7730050",
            "worker_url": "https://workersandbox.mturk.com/projects/3V76OXST9SAE3THKN85FUPK7730050/tasks",
        }

    def test_create_hit_creates_no_sns_subscription_when_asked_not_to(
        self, with_mock, hit_config
    ):
        with_mock.mturk.configure_mock(
            **{
                "create_hit_type.return_value": fake_hit_type_response(),
                "create_hit_with_hit_type.return_value": fake_hit_response(),
            }
        )

        with_mock.create_hit(**hit_config(do_subscribe=False))

        with_mock.sns.create_subscription.assert_not_called()

    def test_create_hit_creates_sns_subscription_when_asked(
        self, with_mock, hit_config
    ):
        with_mock.mturk.configure_mock(
            **{
                "create_hit_type.return_value": fake_hit_type_response(),
                "create_hit_with_hit_type.return_value": fake_hit_response(),
            }
        )

        with_mock.create_hit(**hit_config(do_subscribe=True))

        with_mock.sns.create_subscription.assert_called_once_with(
            "some-experiment-id", "https://www.example.com/notifications"
        )
        with_mock.mturk.update_notification_settings.assert_called_once_with(
            Active=True,
            HITTypeId=mock.ANY,
            Notification={
                "Destination": "fake-topic-arn",
                "Transport": "SNS",
                "Version": "2014-08-15",
                "EventTypes": [
                    "AssignmentAccepted",
                    "AssignmentAbandoned",
                    "AssignmentReturned",
                    "AssignmentSubmitted",
                    "HITReviewable",
                    "HITExpired",
                ],
            },
        )

    def test_extend_hit(self, with_mock):
        with_mock.mturk.configure_mock(
            **{
                "create_additional_assignments_for_hit.return_value": {},
                "update_expiration_for_hit.return_value": {},
                "get_hit.return_value": fake_hit_response(),
            }
        )

        with_mock.extend_hit(hit_id="hit1", number=2, duration_hours=1.0)

        with_mock.mturk.create_additional_assignments_for_hit.assert_called_once()
        with_mock.mturk.update_expiration_for_hit.assert_called_once()

    def test_extend_hit_wraps_exception_helpfully(self, with_mock):
        with_mock.mturk.configure_mock(
            **{"create_additional_assignments_for_hit.side_effect": Exception("Boom!")}
        )
        with pytest.raises(MTurkServiceException) as execinfo:
            with_mock.extend_hit(hit_id="hit1", number=2, duration_hours=1.0)

        assert execinfo.match("Error: failed to add 2 assignments to HIT: Boom!")

    def test_disable_hit_deletes_hit(self, with_mock):
        with_mock.mturk.configure_mock(
            **{
                "update_expiration_for_hit.return_value": True,
                "delete_hit.return_value": {},
            }
        )

        with_mock.disable_hit(hit_id="some hit", experiment_id="some-experiment-id")

        with_mock.mturk.delete_hit.assert_called_once_with(HITId="some hit")

    def test_disable_hit_cancels_notification_subscription(self, with_mock):
        with_mock.mturk.configure_mock(
            **{
                "update_expiration_for_hit.return_value": True,
                "delete_hit.return_value": {},
            }
        )

        with_mock.disable_hit(hit_id="some hit", experiment_id="some-experiment-id")

        with_mock.sns.cancel_subscription.assert_called_once_with("some-experiment-id")

    def test_expire_hit(self, with_mock):
        with_mock.mturk.configure_mock(
            **{"update_expiration_for_hit.return_value": True}
        )

        with_mock.expire_hit("some hit")

        with_mock.mturk.update_expiration_for_hit.assert_called_once_with(
            HITId="some hit", ExpireAt=0
        )

    def test_expire_hit_wraps_exception_helpfully(self, with_mock):
        with_mock.mturk.configure_mock(
            **{"update_expiration_for_hit.side_effect": Exception("Boom!")}
        )

        with pytest.raises(MTurkServiceException) as execinfo:
            with_mock.expire_hit("some hit")

        assert execinfo.match("Failed to expire HIT some hit: Boom!")

    def test_get_hits_returns_all_by_default(self, with_mock):
        hr1 = fake_hit_response(Title="One")
        hr2 = fake_hit_response(Title="Two")
        responses = fake_list_hits_responses([hr1, hr2])

        with_mock.mturk.configure_mock(**{"list_hits.side_effect": responses})

        assert len(list(with_mock.get_hits())) == 2

    def test_get_hits_excludes_based_on_filter(self, with_mock):
        hr1 = fake_hit_response(Title="HIT One")
        hr2 = fake_hit_response(Title="HIT Two")
        responses = fake_list_hits_responses([hr1, hr2])
        with_mock.mturk.configure_mock(**{"list_hits.side_effect": responses})

        hits = list(with_mock.get_hits(lambda h: "Two" in h["title"]))

        assert len(hits) == 1
        assert hits[0]["title"] == "HIT Two"

    def test_get_hits_copes_with_no_keywords(self, with_mock):
        # HITs created directly through the MTurk web UI
        # may have no Keywords at all, so we need to account for this when
        # parsing HITs.
        hr1 = fake_hit_response(Title="One")
        del hr1["HIT"]["Keywords"]
        responses = fake_list_hits_responses([hr1])
        with_mock.mturk.configure_mock(**{"list_hits.side_effect": responses})

        hits = list(with_mock.get_hits())

        assert len(hits) == 1
        assert hits[0]["keywords"] == []

    def test_grant_bonus_translates_values_and_calls_wrapped_mturk(self, with_mock):
        with_mock.mturk.configure_mock(
            **{
                "send_bonus.return_value": response_metadata(),
                "get_assignment.return_value": fake_get_assignment_response(),
            }
        )

        with_mock.grant_bonus(
            assignment_id="some assignment id", amount=2.9857, reason="above and beyond"
        )

        with_mock.mturk.send_bonus.assert_called_once_with(
            WorkerId="FAKE_WORKER_ID",
            AssignmentId="some assignment id",
            BonusAmount="2.99",
            Reason="above and beyond",
            UniqueRequestToken=mock.ANY,
        )

    def test_grant_bonus_wraps_exception_helpfully(self, with_mock):
        with_mock.mturk.configure_mock(
            **{
                "get_assignment.return_value": fake_get_assignment_response(),
                "send_bonus.side_effect": ClientError({}, "Boom!"),
            }
        )
        with pytest.raises(MTurkServiceException) as execinfo:
            with_mock.grant_bonus(
                assignment_id="some assignment id",
                amount=2.9857,
                reason="above and beyond",
            )

            assert execinfo.match(
                "Failed to pay assignment some assignment id bonus of 2.99"
            )

    def test_approve_assignment(self, with_mock):
        with_mock.mturk.configure_mock(
            **{"approve_assignment.return_value": response_metadata()}
        )

        assert with_mock.approve_assignment("fake id") is True
        with_mock.mturk.approve_assignment.assert_called_once_with(
            AssignmentId="fake id"
        )

    def test_approve_assignment_wraps_exception_helpfully(self, with_mock):
        fake_response = fake_get_assignment_response()
        with_mock.mturk.get_assignment = mock.Mock(return_value=fake_response)
        with_mock.mturk.configure_mock(
            **{"approve_assignment.side_effect": ClientError({}, "Boom!")}
        )

        with pytest.raises(MTurkServiceException) as execinfo:
            with_mock.approve_assignment("fake_id")

        assert execinfo.match("Failed to approve assignment fake_id")

    def test_create_qualification_type(self, with_mock):
        with_mock.mturk.configure_mock(
            **{
                "create_qualification_type.return_value": fake_qualification_type_response()
            }
        )
        result = with_mock.create_qualification_type("name", "desc", "status")
        with_mock.mturk.create_qualification_type.assert_called_once_with(
            Description="desc", Name="name", QualificationTypeStatus="status"
        )
        assert isinstance(result["created"], datetime.datetime)

    def test_create_qualification_type_raises_on_duplicate_name(self, with_mock):
        error = Exception("already created a QualificationType with this name")
        with_mock.mturk.configure_mock(
            **{"create_qualification_type.side_effect": error}
        )
        with pytest.raises(DuplicateQualificationNameError):
            with_mock.create_qualification_type("name", "desc", "status")

    def test_assign_qualification(self, with_mock):
        with_mock.mturk.configure_mock(
            **{"associate_qualification_with_worker.return_value": response_metadata()}
        )
        assert with_mock.assign_qualification("qid", "worker", "score")
        with_mock.mturk.associate_qualification_with_worker.assert_called_once_with(
            IntegerValue="score",
            QualificationTypeId="qid",
            SendNotification=False,
            WorkerId="worker",
        )

    def test_dispose_qualification_type(self, with_mock):
        with_mock.mturk.configure_mock(
            **{"delete_qualification_type.return_value": response_metadata()}
        )
        assert with_mock.dispose_qualification_type("qid")
        with_mock.mturk.delete_qualification_type.assert_called_once_with(
            QualificationTypeId="qid"
        )

    def test_get_workers_with_qualification(self, with_mock):
        responses = fake_list_worker_qualification_responses()
        with_mock.mturk.configure_mock(
            **{"list_workers_with_qualification_type.side_effect": responses}
        )
        expected = [
            mock.call(MaxResults=100, QualificationTypeId="qid", Status="Granted"),
            mock.call(
                MaxResults=100,
                QualificationTypeId="qid",
                Status="Granted",
                NextToken="FAKE_NEXT_TOKEN",
            ),
        ]
        # need to unroll the iterator:
        list(with_mock.get_workers_with_qualification("qid"))
        calls = with_mock.mturk.list_workers_with_qualification_type.call_args_list
        assert calls == expected

    def test_current_qualification_score_is_passthrough(self, with_mock):
        fake_response = fake_worker_qualification_response()
        with_mock.mturk.get_qualification_score = mock.Mock(return_value=fake_response)

        score = with_mock.current_qualification_score("some qtype id", "some worker id")

        with_mock.mturk.get_qualification_score.assert_called_once_with(
            QualificationTypeId="some qtype id", WorkerId="some worker id"
        )
        assert score == fake_response["Qualification"]["IntegerValue"]

    def test_current_qualification_score_raises_for_ungranted_qualification(
        self, with_mock
    ):
        with_mock.mturk.get_qualification_score = mock.Mock(
            side_effect=ClientError({}, "blah blah ... does not exist.")
        )
        with pytest.raises(WorkerLacksQualification):
            with_mock.current_qualification_score("some qtype id", "some worker id")

    def test_current_qualification_score_raises_for_revoked_qualification(
        self, with_mock
    ):
        with_mock.mturk.get_qualification_score = mock.Mock(
            side_effect=ClientError(
                {}, "This operation can be called with a status of: Granted"
            )
        )
        with pytest.raises(RevokedQualification):
            with_mock.current_qualification_score("some qtype id", "some worker id")

    def test_current_named_qualification_score(self, with_mock):
        worker_id = "some worker id"
        with_mock.get_qualification_type_by_name = mock.Mock(return_value={"id": "qid"})
        with_mock.current_qualification_score = mock.Mock(return_value=1)

        result = with_mock.current_named_qualification_score("some name", worker_id)

        assert result["qtype"] == {"id": "qid"}
        assert result["score"] == 1

    def test_current_named_qualification_score_worker_unscored(self, with_mock):
        worker_id = "some worker id"
        with_mock.get_qualification_type_by_name = mock.Mock(return_value={"id": "qid"})
        with_mock.current_qualification_score = mock.Mock(
            side_effect=WorkerLacksQualification()
        )

        result = with_mock.current_named_qualification_score("some name", worker_id)

        assert result["qtype"] == {"id": "qid"}
        assert result["score"] is None

    def test_current_named_qualification_score_is_none_for_revoked_qualifications(
        self, with_mock
    ):
        worker_id = "some worker id"
        with_mock.get_qualification_type_by_name = mock.Mock(return_value={"id": "qid"})
        with_mock.current_qualification_score = mock.Mock(
            side_effect=RevokedQualification()
        )

        result = with_mock.current_named_qualification_score("some name", worker_id)

        assert result["qtype"] == {"id": "qid"}
        assert result["score"] is None

    def test_increment_named_qualification_score_for_worker_with_score(self, with_mock):
        worker_id = "some worker id"
        fake_score = {"qtype": {"id": "qtype_id"}, "score": 2}
        with_mock.current_named_qualification_score = mock.Mock(return_value=fake_score)
        with_mock.mturk.associate_qualification_with_worker.return_value = {}

        result = with_mock.increment_named_qualification_score("some qual", worker_id)

        assert result["score"] == 3
        with_mock.mturk.associate_qualification_with_worker.assert_called_once_with(
            IntegerValue=3,
            QualificationTypeId="qtype_id",
            SendNotification=False,
            WorkerId="some worker id",
        )

    def test_increment_named_qualification_score_for_worker_with_no_score(
        self, with_mock
    ):
        worker_id = "some worker id"
        fake_score = {"qtype": {"id": "qtype_id"}, "score": None}
        with_mock.current_named_qualification_score = mock.Mock(return_value=fake_score)
        with_mock.mturk.associate_qualification_with_worker.return_value = {}

        result = with_mock.increment_named_qualification_score("some qual", worker_id)

        assert result["score"] == 1
        with_mock.mturk.associate_qualification_with_worker.assert_called_once_with(
            IntegerValue=1,
            QualificationTypeId="qtype_id",
            SendNotification=False,
            WorkerId="some worker id",
        )

    def test_increment_named_qualification_score_nonexisting_qual_raises(
        self, with_mock
    ):
        worker_id = "some worker id"
        with_mock.get_qualification_type_by_name = mock.Mock(return_value=None)

        with pytest.raises(QualificationNotFoundException):
            with_mock.increment_named_qualification_score("some qual", worker_id)

    def test_revoke_qualification(self, with_mock):
        with_mock.disassociate_qualification_from_worker = mock.Mock(
            return_value=response_metadata()
        )
        with_mock.mturk.disassociate_qualification_from_worker.return_value = {}

        with_mock.revoke_qualification("some qtype id", "some worker id", "some reason")

        with_mock.mturk.disassociate_qualification_from_worker.assert_called_once_with(
            QualificationTypeId="some qtype id",
            WorkerId="some worker id",
            Reason="some reason",
        )
