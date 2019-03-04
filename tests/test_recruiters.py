import mock
import pytest
from datetime import datetime
from dallinger.models import Participant
from dallinger.experiment import Experiment


class TestModuleFunctions(object):
    @pytest.fixture
    def mod(self):
        from dallinger import recruiters

        return recruiters

    def test__get_queue(self, mod):
        from rq import Queue

        assert isinstance(mod._get_queue(), Queue)

    def test_for_experiment(self, mod):
        mock_exp = mock.MagicMock(spec=Experiment)
        mock_exp.recruiter = mock.sentinel.some_object
        assert mod.for_experiment(mock_exp) is mock_exp.recruiter

    def test_by_name_with_valid_name(self, mod):
        assert isinstance(mod.by_name("CLIRecruiter"), mod.CLIRecruiter)

    def test_by_name_with_valid_nickname(self, mod):
        assert isinstance(mod.by_name("bots"), mod.BotRecruiter)

    def test_by_name_with_invalid_name(self, mod):
        assert mod.by_name("blah") is None

    def test_for_debug_mode(self, mod, stub_config):
        r = mod.from_config(stub_config)
        assert isinstance(r, mod.HotAirRecruiter)

    def test_recruiter_config_value_used_if_not_debug(self, mod, stub_config):
        stub_config.extend({"mode": u"sandbox", "recruiter": u"CLIRecruiter"})
        r = mod.from_config(stub_config)
        assert isinstance(r, mod.CLIRecruiter)

    def test_debug_mode_trumps_recruiter_config_value(self, mod, stub_config):
        stub_config.extend({"recruiter": u"CLIRecruiter"})
        r = mod.from_config(stub_config)
        assert isinstance(r, mod.HotAirRecruiter)

    def test_bot_recruiter_trumps_debug_mode(self, mod, stub_config):
        stub_config.extend({"recruiter": u"bots"})
        r = mod.from_config(stub_config)
        assert isinstance(r, mod.BotRecruiter)

    def test_default_is_mturk_recruiter_if_not_debug(self, mod, active_config):
        active_config.extend({"mode": u"sandbox"})
        r = mod.from_config(active_config)
        assert isinstance(r, mod.MTurkRecruiter)

    def test_replay_setting_dictates_recruiter(self, mod, active_config):
        active_config.extend(
            {"replay": True, "mode": u"sandbox", "recruiter": u"CLIRecruiter"}
        )
        r = mod.from_config(active_config)
        assert isinstance(r, mod.HotAirRecruiter)

    def test_unknown_recruiter_name_raises(self, mod, stub_config):
        stub_config.extend({"mode": u"sandbox", "recruiter": u"bogus"})
        with pytest.raises(NotImplementedError):
            mod.from_config(stub_config)


class TestRecruiter(object):
    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import Recruiter

        return Recruiter()

    def test_open_recruitment(self, recruiter):
        with pytest.raises(NotImplementedError):
            recruiter.open_recruitment()

    def test_recruit(self, recruiter):
        with pytest.raises(NotImplementedError):
            recruiter.recruit()

    def test_close_recruitment(self, recruiter):
        with pytest.raises(NotImplementedError):
            recruiter.close_recruitment()

    def test_reward_bonus(self, recruiter):
        with pytest.raises(NotImplementedError):
            recruiter.reward_bonus("any assignment id", 0.01, "You're great!")

    def test_external_submission_url(self, recruiter):
        assert recruiter.external_submission_url is None

    def test_rejects_questionnaire_from_returns_none(self, recruiter):
        dummy = mock.NonCallableMock()
        assert recruiter.rejects_questionnaire_from(participant=dummy) is None

    def test_notify_duration_exceeded_logs_only(self, recruiter):
        recruiter.notify_duration_exceeded(participants=[], reference_time=None)

    def test_backward_compat(self, recruiter):
        assert recruiter() is recruiter


@pytest.mark.usefixtures("active_config")
class TestCLIRecruiter(object):
    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import CLIRecruiter

        yield CLIRecruiter()

    def test_recruit_recruits_one_by_default(self, recruiter):
        result = recruiter.recruit()
        assert len(result) == 1

    def test_recruit_results_are_urls(self, recruiter):
        assert "/ad?recruiter=cli&assignmentId=" in recruiter.recruit()[0]

    def test_recruit_multiple(self, recruiter):
        assert len(recruiter.recruit(n=3)) == 3

    def test_open_recruitment_recruits_one_by_default(self, recruiter):
        result = recruiter.open_recruitment()
        assert len(result["items"]) == 1

    def test_open_recruitment_describes_how_it_works(self, recruiter):
        result = recruiter.open_recruitment()
        assert 'Search for "New participant requested:"' in result["message"]

    def test_open_recruitment_multiple(self, recruiter):
        result = recruiter.open_recruitment(n=3)
        assert len(result["items"]) == 3

    def test_open_recruitment_results_are_urls(self, recruiter):
        result = recruiter.open_recruitment()
        assert "/ad?recruiter=cli&assignmentId=" in result["items"][0]

    def test_open_recruitment_with_zero(self, recruiter):
        result = recruiter.open_recruitment(n=0)
        assert result["items"] == []

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_approve_hit(self, recruiter):
        assert recruiter.approve_hit("any assignment id")

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus("any assignment id", 0.01, "You're great!")

    def test_open_recruitment_uses_configured_mode(self, recruiter, active_config):
        active_config.extend({"mode": u"new_mode"})
        result = recruiter.open_recruitment()
        assert "mode=new_mode" in result["items"][0]

    def test_returns_standard_submission_event_type(self, recruiter):
        assert recruiter.submitted_event() == "AssignmentSubmitted"


@pytest.mark.usefixtures("active_config")
class TestHotAirRecruiter(object):
    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import HotAirRecruiter

        yield HotAirRecruiter()

    def test_recruit_recruits_one_by_default(self, recruiter):
        result = recruiter.recruit()
        assert len(result) == 1

    def test_recruit_results_are_urls(self, recruiter):
        assert "/ad?recruiter=hotair&assignmentId=" in recruiter.recruit()[0]

    def test_recruit_multiple(self, recruiter):
        assert len(recruiter.recruit(n=3)) == 3

    def test_open_recruitment_recruits_one_by_default(self, recruiter):
        result = recruiter.open_recruitment()
        assert len(result["items"]) == 1

    def test_open_recruitment_describes_how_it_works(self, recruiter):
        result = recruiter.open_recruitment()
        assert "requests will open browser windows" in result["message"]

    def test_open_recruitment_multiple(self, recruiter):
        result = recruiter.open_recruitment(n=3)
        assert len(result["items"]) == 3

    def test_open_recruitment_results_are_urls(self, recruiter):
        result = recruiter.open_recruitment()
        assert "/ad?recruiter=hotair&assignmentId=" in result["items"][0]

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_approve_hit(self, recruiter):
        assert recruiter.approve_hit("any assignment id")

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus("any assignment id", 0.01, "You're great!")

    def test_open_recruitment_ignores_configured_mode(self, recruiter, active_config):
        active_config.extend({"mode": u"new_mode"})
        result = recruiter.open_recruitment()
        assert "mode=debug" in result["items"][0]

    def test_returns_standard_submission_event_type(self, recruiter):
        assert recruiter.submitted_event() == "AssignmentSubmitted"


class TestSimulatedRecruiter(object):
    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import SimulatedRecruiter

        return SimulatedRecruiter()

    def test_recruit_returns_empty_result(self, recruiter):
        assert recruiter.recruit() == []

    def test_recruit_multiple_returns_empty_result(self, recruiter):
        assert recruiter.recruit(n=3) == []

    def test_open_recruitment_returns_empty_result(self, recruiter):
        assert recruiter.open_recruitment()["items"] == []

    def test_open_recruitment_multiple_returns_empty_result(self, recruiter):
        assert recruiter.open_recruitment(n=3)["items"] == []

    def test_returns_standard_submission_event_type(self, recruiter):
        assert recruiter.submitted_event() == "AssignmentSubmitted"

    def test_close_recruitment(self, recruiter):
        assert recruiter.close_recruitment() is None


class TestBotRecruiter(object):
    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import BotRecruiter

        with mock.patch.multiple(
            "dallinger.recruiters", _get_queue=mock.DEFAULT, get_base_url=mock.DEFAULT
        ) as mocks:
            mocks["get_base_url"].return_value = "fake_base_url"
            r = BotRecruiter()
            r._get_bot_factory = mock.Mock()
            yield r

    def test_recruit_returns_list(self, recruiter):
        result = recruiter.recruit(n=2)
        assert len(result) == 2

    def test_recruit_returns_urls(self, recruiter):
        result = recruiter.recruit()
        assert result[0].startswith("fake_base_url")

    def test_open_recruitment_returns_list(self, recruiter):
        result = recruiter.open_recruitment(n=2)
        assert len(result["items"]) == 2

    def test_open_recruitment_returns_urls(self, recruiter):
        result = recruiter.open_recruitment()
        assert result["items"][0].startswith("fake_base_url")

    def test_open_recruitment_describes_how_it_works(self, recruiter):
        result = recruiter.open_recruitment()
        assert "recruitment started using Mock" in result["message"]

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_approve_hit(self, recruiter):
        assert recruiter.approve_hit("any assignment id")

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus("any assignment id", 0.01, "You're great!")

    def test_returns_specific_submission_event_type(self, recruiter):
        assert recruiter.submitted_event() == "BotAssignmentSubmitted"

    def test_notify_duration_exceeded_rejects_participants(self, a, recruiter):
        bot = a.participant(recruiter_id="bots")

        recruiter.notify_duration_exceeded([bot], datetime.now())

        assert bot.status == "rejected"


class TestMTurkRecruiterMessages(object):
    @pytest.fixture
    def summary(self, a, stub_config):
        from datetime import timedelta
        from dallinger.recruiters import ParticipationTime

        p = a.participant()
        one_min_over = 60 * stub_config.get("duration") + 1
        return ParticipationTime(
            participant=p,
            reference_time=p.creation_time + timedelta(minutes=one_min_over),
            config=stub_config,
        )

    @pytest.fixture
    def whimsical(self, summary, stub_config):
        from dallinger.recruiters import WhimsicalMTurkHITMessages

        return WhimsicalMTurkHITMessages(summary)

    @pytest.fixture
    def nonwhimsical(self, summary, stub_config):
        from dallinger.recruiters import MTurkHITMessages

        return MTurkHITMessages(summary)

    def test_resubmitted_msg_whimsical(self, whimsical):
        data = whimsical.resubmitted_msg()
        body = data["body"].replace("\n", " ")
        assert data["subject"] == "A matter of minor concern."
        assert "a full 1 minutes over" in body

    def test_resubmitted_msg_nonwhimsical(self, nonwhimsical):
        data = nonwhimsical.resubmitted_msg()
        body = data["body"].replace("\n", " ")
        assert data["subject"] == "Dallinger automated email - minor error."
        assert "Dallinger has auto-corrected the problem" in body

    def test_hit_cancelled_msg_whimsical(self, whimsical):
        data = whimsical.hit_cancelled_msg()
        body = data["body"].replace("\n", " ")
        assert data["subject"] == "Most troubling news."
        assert "a full 1 minutes over" in body

    def test_hit_cancelled_msg_nonwhimsical(self, nonwhimsical):
        data = nonwhimsical.hit_cancelled_msg()
        body = data["body"].replace("\n", " ")
        assert data["subject"] == "Dallinger automated email - major error."
        assert "Dallinger has paused the experiment" in body


@pytest.mark.usefixtures("active_config")
class TestMTurkRecruiter(object):
    @pytest.fixture
    def requests(self):
        with mock.patch(
            "dallinger.recruiters.requests", autospec=True
        ) as mock_requests:
            yield mock_requests

    @pytest.fixture
    def messenger(self):
        from dallinger.notifications import DebugMessenger

        mock_messenger = mock.create_autospec(DebugMessenger)
        yield mock_messenger

    @pytest.fixture
    def recruiter(self, active_config, messenger):
        from dallinger.mturk import MTurkService
        from dallinger.recruiters import MTurkRecruiter

        with mock.patch.multiple(
            "dallinger.recruiters", os=mock.DEFAULT, get_base_url=mock.DEFAULT
        ) as mocks:
            mocks["get_base_url"].return_value = "http://fake-domain"
            mocks["os"].getenv.return_value = "fake-host-domain"
            mockservice = mock.create_autospec(MTurkService)
            active_config.extend({"mode": u"sandbox"})
            r = MTurkRecruiter()
            r.messenger = messenger
            r.mturkservice = mockservice("fake key", "fake secret", "fake_region")
            r.mturkservice.check_credentials.return_value = True
            r.mturkservice.create_hit.return_value = {"type_id": "fake type id"}
            return r

    def test_instantiation_fails_with_invalid_mode(self, active_config):
        from dallinger.recruiters import MTurkRecruiter
        from dallinger.recruiters import MTurkRecruiterException

        active_config.extend({"mode": u"nonsense"})
        with pytest.raises(MTurkRecruiterException) as ex_info:
            MTurkRecruiter()
        assert ex_info.match('"nonsense" is not a valid mode')

    def test_config_passed_to_constructor_sandbox(self, recruiter):
        assert recruiter.config.get("title") == "fake experiment title"

    def test_external_submission_url_sandbox(self, recruiter):
        assert "workersandbox.mturk.com" in recruiter.external_submission_url

    def test_external_submission_url_live(self, recruiter):
        recruiter.config.set("mode", u"live")
        assert "www.mturk.com" in recruiter.external_submission_url

    def test_open_recruitment_returns_one_item_recruitments_list(self, recruiter):
        result = recruiter.open_recruitment(n=2)
        assert len(result["items"]) == 1

    def test_open_recruitment_describes_how_it_works(self, recruiter):
        result = recruiter.open_recruitment()
        assert "HIT now published to Amazon Mechanical Turk" in result["message"]

    def test_open_recruitment_returns_urls(self, recruiter):
        url = recruiter.open_recruitment(n=1)["items"][0]
        assert (
            url == "https://workersandbox.mturk.com/mturk/preview?groupId=fake type id"
        )

    def test_open_recruitment_raises_if_no_external_hit_domain_configured(
        self, recruiter
    ):
        from dallinger.recruiters import MTurkRecruiterException

        recruiter.hit_domain = None
        with pytest.raises(MTurkRecruiterException):
            recruiter.open_recruitment(n=1)

    def test_open_recruitment_check_creds_before_calling_create_hit(self, recruiter):
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.check_credentials.assert_called_once()

    def test_open_recruitment_single_recruitee_builds_hit(self, recruiter):
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url="http://fake-domain/ad?recruiter=mturk",
            approve_requirement=95,
            description=u"fake HIT description",
            duration_hours=1.0,
            keywords=[u"kw1", u"kw2", u"kw3"],
            lifetime_days=1,
            max_assignments=1,
            notification_url=u"https://url-of-notification-route",
            reward=0.01,
            title=u"fake experiment title",
            us_only=True,
            blacklist=[],
            annotation="some experiment uid",
        )

    def test_open_recruitment_creates_qualifications_for_experiment_app_id(
        self, recruiter
    ):
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_qualification_type.assert_called_once_with(
            u"some experiment uid", "Experiment-specific qualification"
        )

    def test_open_recruitment_creates_qualifications_for_exp_with_group_name(
        self, recruiter
    ):
        recruiter.config.set("group_name", u"some group name")
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_qualification_type.assert_has_calls(
            [
                mock.call(u"some experiment uid", "Experiment-specific qualification"),
                mock.call(u"some group name", "Experiment group qualification"),
            ],
            any_order=True,
        )

    def test_open_recruitment_creates_no_qualifications_if_so_configured(
        self, recruiter
    ):
        recruiter.config.set("group_name", u"some group name")
        recruiter.config.set("assign_qualifications", False)
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_qualification_type.assert_not_called()

    def test_open_recruitment_when_qualification_already_exists(self, recruiter):
        from dallinger.mturk import DuplicateQualificationNameError

        mturk = recruiter.mturkservice
        mturk.create_qualification_type.side_effect = DuplicateQualificationNameError

        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once()

    def test_open_recruitment_with_blacklist(self, recruiter):
        recruiter.config.set("qualification_blacklist", u"foo, bar")
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url="http://fake-domain/ad?recruiter=mturk",
            approve_requirement=95,
            description="fake HIT description",
            duration_hours=1.0,
            lifetime_days=1,
            keywords=[u"kw1", u"kw2", u"kw3"],
            max_assignments=1,
            notification_url="https://url-of-notification-route",
            reward=0.01,
            title="fake experiment title",
            us_only=True,
            blacklist=["foo", "bar"],
            annotation="some experiment uid",
        )

    def test_open_recruitment_raises_error_if_recruitment_in_progress(
        self, a, recruiter
    ):
        from dallinger.recruiters import MTurkRecruiterException

        a.participant(recruiter_id="mturk")
        with pytest.raises(MTurkRecruiterException):
            recruiter.open_recruitment()

        recruiter.mturkservice.check_credentials.assert_not_called()

    def test_open_recruitment_ignores_participants_from_other_recruiters(
        self, a, recruiter
    ):
        a.participant(recruiter_id="bot")
        result = recruiter.open_recruitment(n=1)
        assert len(result["items"]) == 1
        recruiter.mturkservice.check_credentials.assert_called_once()

    def test_supresses_assignment_submitted(self, recruiter):
        assert recruiter.submitted_event() is None

    def test_current_hit_id_with_active_experiment(self, a, recruiter):
        # Does not find hits associated with other recruiters
        a.participant(hit_id=u"the hit!", recruiter_id="hotair")
        assert recruiter.current_hit_id() is None

        # Finds its own hits
        a.participant(hit_id=u"the hit!", recruiter_id="mturk")
        assert recruiter.current_hit_id() == "the hit!"

    def test_current_hit_id_with_no_active_experiment(self, recruiter):
        assert recruiter.current_hit_id() is None

    def test_recruit_auto_recruit_on_recruits_for_current_hit(self, recruiter):
        fake_hit_id = "fake HIT id"
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.recruit()

        recruiter.mturkservice.extend_hit.assert_called_once_with(
            fake_hit_id, number=1, duration_hours=1.0
        )

    def test_recruit_auto_recruit_off_does_not_extend_hit(self, recruiter):
        recruiter.config["auto_recruit"] = False
        fake_hit_id = "fake HIT id"
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.recruit()

        assert not recruiter.mturkservice.extend_hit.called

    def test_recruit_no_current_hit_does_not_extend_hit(self, recruiter):
        recruiter.current_hit_id = mock.Mock(return_value=None)
        recruiter.recruit()

        assert not recruiter.mturkservice.extend_hit.called

    def test_recruit_extend_hit_error_is_logged_politely(self, recruiter):
        from dallinger.mturk import MTurkServiceException

        fake_hit_id = "fake HIT id"
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.mturkservice.extend_hit.side_effect = MTurkServiceException("Boom!")
        with mock.patch("dallinger.recruiters.logger") as mock_logger:
            recruiter.recruit()

        mock_logger.exception.assert_called_once_with("Boom!")

    def test_reward_bonus_is_simple_passthrough(self, recruiter):
        recruiter.reward_bonus(
            assignment_id="fake assignment id", amount=2.99, reason="well done!"
        )

        recruiter.mturkservice.grant_bonus.assert_called_once_with(
            assignment_id="fake assignment id", amount=2.99, reason="well done!"
        )

    def test_reward_bonus_logs_exception(self, recruiter):
        from dallinger.mturk import MTurkServiceException

        recruiter.mturkservice.grant_bonus.side_effect = MTurkServiceException("Boom!")
        with mock.patch("dallinger.recruiters.logger") as mock_logger:
            recruiter.reward_bonus("fake-assignment", 2.99, "fake reason")

        mock_logger.exception.assert_called_once_with("Boom!")

    def test_approve_hit(self, recruiter):
        fake_id = "fake assignment id"
        recruiter.approve_hit(fake_id)

        recruiter.mturkservice.approve_assignment.assert_called_once_with(fake_id)

    def test_approve_hit_logs_exception(self, recruiter):
        from dallinger.mturk import MTurkServiceException

        recruiter.mturkservice.approve_assignment.side_effect = MTurkServiceException(
            "Boom!"
        )
        with mock.patch("dallinger.recruiters.logger") as mock_logger:
            recruiter.approve_hit("fake-hit-id")

        mock_logger.exception.assert_called_once_with("Boom!")

    @pytest.mark.xfail
    def test_close_recruitment(self, recruiter):
        fake_hit_id = "fake HIT id"
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.close_recruitment()
        recruiter.mturkservice.expire_hit.assert_called_once_with(fake_hit_id)

    def test_notify_completed_assigns_exp_qualification(self, recruiter):
        participant = mock.Mock(spec=Participant, worker_id="some worker id")
        recruiter.notify_completed(participant)

        recruiter.mturkservice.increment_qualification_score.assert_called_once_with(
            "some experiment uid", "some worker id"
        )

    def test_notify_completed_adds_group_qualification_if_group(self, recruiter):
        participant = mock.Mock(spec=Participant, worker_id="some worker id")
        recruiter.config.set("group_name", u"some existing group_name")
        recruiter.notify_completed(participant)

        recruiter.mturkservice.increment_qualification_score.assert_has_calls(
            [
                mock.call("some experiment uid", "some worker id"),
                mock.call("some existing group_name", "some worker id"),
            ],
            any_order=True,
        )

    def test_notify_completed_catches_nonexistent_qualification(self, recruiter):
        from dallinger.mturk import QualificationNotFoundException

        participant = mock.Mock(spec=Participant, worker_id="some worker id")
        error = QualificationNotFoundException("Ouch!")
        recruiter.mturkservice.increment_qualification_score.side_effect = error

        # logs, but does not raise:
        recruiter.notify_completed(participant)

    def test_notify_completed_skips_assigning_qualification_if_so_configured(
        self, recruiter
    ):
        participant = mock.Mock(spec=Participant, worker_id="some worker id")
        recruiter.config.set("group_name", u"some existing group_name")
        recruiter.config.set("assign_qualifications", False)
        recruiter.notify_completed(participant)

        recruiter.mturkservice.increment_qualification_score.assert_not_called()

    def test_notify_completed_skips_assigning_qualification_if_overrecruited(
        self, recruiter
    ):
        participant = mock.Mock(
            spec=Participant, worker_id="some worker id", status="overrecruited"
        )
        recruiter.notify_completed(participant)

        recruiter.mturkservice.increment_qualification_score.assert_not_called()

    def test_rejects_questionnaire_from_returns_none_if_working(self, recruiter):
        participant = mock.Mock(spec=Participant, status="working")
        assert recruiter.rejects_questionnaire_from(participant) is None

    def test_rejects_questionnaire_from_returns_error_if_already_submitted(
        self, recruiter
    ):
        participant = mock.Mock(spec=Participant, status="submitted")
        rejection = recruiter.rejects_questionnaire_from(participant)
        assert "already sumbitted their HIT" in rejection

    #
    # Begin notify_duration_exceeded tests
    #

    def test_sets_participant_status_if_approved(self, a, recruiter):
        recruiter.mturkservice.get_assignment.return_value = {"status": "Approved"}
        participants = [a.participant()]

        recruiter.notify_duration_exceeded(participants, datetime.now())

        assert participants[0].status == "approved"

    def test_sets_participant_status_if_rejected(self, a, recruiter):
        recruiter.mturkservice.get_assignment.return_value = {"status": "Rejected"}
        participants = [a.participant()]

        recruiter.notify_duration_exceeded(participants, datetime.now())

        assert participants[0].status == "rejected"

    def test_sends_replacement_mturk_notification_if_resubmitted(
        self, a, recruiter, requests
    ):
        recruiter.mturkservice.get_assignment.return_value = {"status": "Submitted"}
        participants = [a.participant()]

        recruiter.notify_duration_exceeded(participants, datetime.now())

        requests.post.assert_called_once_with(
            "https://url-of-notification-route",
            data={
                "Event.1.EventType": "AssignmentSubmitted",
                "Event.1.AssignmentId": participants[0].assignment_id,
            },
        )
        recruiter.messenger.send.assert_called_once()

    def test_notifies_researcher_if_resubmitted(self, a, recruiter, requests):
        recruiter.mturkservice.get_assignment.return_value = {"status": "Submitted"}
        participants = [a.participant()]

        recruiter.notify_duration_exceeded(participants, datetime.now())

        recruiter.messenger.send.assert_called_once()

    def test_shuts_down_recruitment_if_no_status_from_mturk(
        self, a, recruiter, requests
    ):
        recruiter.mturkservice.get_assignment.return_value = {"status": None}
        participants = [a.participant()]

        recruiter.notify_duration_exceeded(participants, datetime.now())

        assert requests.patch.call_args[1]["data"] == '{"auto_recruit": "false"}'

    def test_treats_mturk_exception_as_status_none(self, a, recruiter):
        recruiter.mturkservice.get_assignment.side_effect = Exception("Boom!")

        assert recruiter._mturk_status_for(mock.Mock()) is None

    def test_sends_notification_missing_if_no_status_from_mturk(
        self, a, recruiter, requests
    ):
        recruiter.mturkservice.get_assignment.return_value = {"status": None}
        participants = [a.participant()]

        recruiter.notify_duration_exceeded(participants, datetime.now())

        requests.post.assert_called_once_with(
            "https://url-of-notification-route",
            data={
                "Event.1.EventType": "NotificationMissing",
                "Event.1.AssignmentId": participants[0].assignment_id,
            },
        )

    def test_notifies_researcher_when_hit_cancelled(self, a, recruiter, requests):
        recruiter.mturkservice.get_assignment.return_value = {"status": None}
        participants = [a.participant()]

        recruiter.notify_duration_exceeded(participants, datetime.now())

        recruiter.messenger.send.assert_called_once()

    def test_no_assignment_on_mturk_expires_hit(self, a, recruiter, requests):
        recruiter.mturkservice.get_assignment.return_value = {"status": None}
        participants = [a.participant()]

        recruiter.notify_duration_exceeded(participants, datetime.now())

        recruiter.mturkservice.expire_hit.assert_called_once_with(
            participants[0].hit_id
        )


class TestRedisTally(object):
    @pytest.fixture
    def redis_tally(self):
        from dallinger.recruiters import RedisTally

        return RedisTally()

    def test_that_its_a_counter(self, redis_tally):
        assert redis_tally.current == 0
        redis_tally.increment(3)
        assert redis_tally.current == 3


@pytest.mark.usefixtures("active_config")
class TestMTurkLargeRecruiter(object):
    @pytest.fixture
    def counter(self):
        # We don't want to depend on redis in these tests.
        class PrimitiveCounter(object):

            _count = 0

            def increment(self, count):
                self._count += count

            @property
            def current(self):
                return self._count

        return PrimitiveCounter()

    @pytest.fixture
    def recruiter(self, active_config, counter):
        from dallinger.mturk import MTurkService
        from dallinger.recruiters import MTurkLargeRecruiter

        with mock.patch.multiple(
            "dallinger.recruiters", os=mock.DEFAULT, get_base_url=mock.DEFAULT
        ) as mocks:
            mocks["get_base_url"].return_value = "http://fake-domain"
            mocks["os"].getenv.return_value = "fake-host-domain"
            mockservice = mock.create_autospec(MTurkService)
            active_config.extend({"mode": u"sandbox"})
            r = MTurkLargeRecruiter(counter=counter)
            r.mturkservice = mockservice("fake key", "fake secret", "fake_region")
            r.mturkservice.check_credentials.return_value = True
            r.mturkservice.create_hit.return_value = {"type_id": "fake type id"}
            r.current_hit_id = mock.Mock(return_value="fake HIT id")
            return r

    def test_open_recruitment_raises_error_if_experiment_in_progress(
        self, a, recruiter
    ):
        from dallinger.recruiters import MTurkRecruiterException

        a.participant(recruiter_id="mturklarge")
        with pytest.raises(MTurkRecruiterException):
            recruiter.open_recruitment()

        recruiter.mturkservice.check_credentials.assert_not_called()

    def test_open_recruitment_ignores_participants_from_other_recruiters(
        self, a, recruiter
    ):
        a.participant(recruiter_id="bot")
        result = recruiter.open_recruitment(n=1)
        assert len(result["items"]) == 1
        recruiter.mturkservice.check_credentials.assert_called_once()

    def test_open_recruitment_single_recruitee_actually_overrecruits(self, recruiter):
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url="http://fake-domain/ad?recruiter=mturklarge",
            approve_requirement=95,
            description="fake HIT description",
            duration_hours=1.0,
            keywords=["kw1", "kw2", "kw3"],
            lifetime_days=1,
            max_assignments=10,
            notification_url="https://url-of-notification-route",
            reward=0.01,
            title="fake experiment title",
            us_only=True,
            blacklist=[],
            annotation="some experiment uid",
        )

    def test_open_recruitment_with_more_than_pool_size_uses_requested_count(
        self, recruiter
    ):
        num_recruits = recruiter.pool_size + 1
        recruiter.open_recruitment(n=num_recruits)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url="http://fake-domain/ad?recruiter=mturklarge",
            approve_requirement=95,
            description="fake HIT description",
            duration_hours=1.0,
            keywords=["kw1", "kw2", "kw3"],
            lifetime_days=1,
            max_assignments=num_recruits,
            notification_url="https://url-of-notification-route",
            reward=0.01,
            title="fake experiment title",
            us_only=True,
            blacklist=[],
            annotation="some experiment uid",
        )

    def test_recruit_draws_on_initial_pool_before_extending_hit(self, recruiter):
        recruiter.open_recruitment(n=recruiter.pool_size - 1)
        recruiter.recruit(n=1)

        recruiter.mturkservice.extend_hit.assert_not_called()

        recruiter.recruit(n=1)

        recruiter.mturkservice.extend_hit.assert_called_once_with(
            "fake HIT id", duration_hours=1.0, number=1
        )

    def test_recruits_more_immediately_if_initial_recruitment_exceeds_pool_size(
        self, recruiter
    ):
        recruiter.open_recruitment(n=recruiter.pool_size + 1)
        recruiter.recruit(n=5)

        recruiter.mturkservice.extend_hit.assert_called_once_with(
            "fake HIT id", duration_hours=1.0, number=5
        )

    def test_recruit_auto_recruit_off_does_not_extend_hit(self, recruiter):
        recruiter.config["auto_recruit"] = False

        recruiter.recruit()

        assert not recruiter.mturkservice.extend_hit.called


@pytest.mark.usefixtures("active_config", "db_session")
class TestMultiRecruiter(object):
    @pytest.fixture
    def recruiter(self, active_config):
        from dallinger.recruiters import MultiRecruiter

        active_config.extend({"recruiters": u"cli: 2, hotair: 1"})
        return MultiRecruiter()

    def test_parse_spec(self, recruiter):
        assert recruiter.spec == [("cli", 2), ("hotair", 1)]

    def test_pick_recruiter(self, recruiter):
        recruiters = list(recruiter.recruiters(3))
        assert len(recruiters) == 2

        subrecruiter, count = recruiters[0]
        assert subrecruiter.nickname == "cli"
        assert count == 2

        subrecruiter, count = recruiters[1]
        assert subrecruiter.nickname == "hotair"
        assert count == 1

    def test_open_recruitment(self, recruiter):
        result = recruiter.open_recruitment(n=3)
        assert len(result["items"]) == 3
        assert result["items"][0].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result["items"][1].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result["items"][2].startswith("http://0.0.0.0:5000/ad?recruiter=hotair")

    def test_open_recruitment_over_recruit(self, recruiter):
        result = recruiter.open_recruitment(n=5)
        assert len(result["items"]) == 3
        assert result["items"][0].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result["items"][1].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result["items"][2].startswith("http://0.0.0.0:5000/ad?recruiter=hotair")

    def test_open_recruitment_twice(self, recruiter):
        result = recruiter.open_recruitment(n=1)
        assert len(result["items"]) == 1
        assert result["items"][0].startswith("http://0.0.0.0:5000/ad?recruiter=cli")

        result2 = recruiter.open_recruitment(n=3)
        assert len(result2["items"]) == 2
        assert result2["items"][0].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result2["items"][1].startswith("http://0.0.0.0:5000/ad?recruiter=hotair")

    def test_recruit(self, recruiter):
        result = recruiter.recruit(n=3)
        assert len(result) == 3
        assert result[0].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result[1].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result[2].startswith("http://0.0.0.0:5000/ad?recruiter=hotair")

    def test_over_recruit(self, recruiter):
        result = recruiter.recruit(n=5)
        assert len(result) == 3
        assert result[0].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result[1].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result[2].startswith("http://0.0.0.0:5000/ad?recruiter=hotair")

    def test_recruit_partial(self, recruiter):
        result = recruiter.open_recruitment(n=1)
        assert len(result["items"]) == 1
        assert result["items"][0].startswith("http://0.0.0.0:5000/ad?recruiter=cli")

        result2 = recruiter.recruit(n=3)
        assert len(result2) == 2
        assert result2[0].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result2[1].startswith("http://0.0.0.0:5000/ad?recruiter=hotair")

        result3 = recruiter.recruit(n=2)
        assert len(result3) == 0

    def test_recruit_batches(self, active_config):
        from dallinger.recruiters import MultiRecruiter

        active_config.extend({"recruiters": u"cli: 2, hotair: 1, cli: 3, hotair: 2"})
        recruiter = MultiRecruiter()
        result = recruiter.recruit(n=10)
        assert len(result) == 8
        assert result[0].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result[1].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result[2].startswith("http://0.0.0.0:5000/ad?recruiter=hotair")
        assert result[3].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result[4].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result[5].startswith("http://0.0.0.0:5000/ad?recruiter=cli")
        assert result[6].startswith("http://0.0.0.0:5000/ad?recruiter=hotair")
        assert result[7].startswith("http://0.0.0.0:5000/ad?recruiter=hotair")

    def test_close_recruitment(self, recruiter):
        patch1 = mock.patch("dallinger.recruiters.CLIRecruiter.close_recruitment")
        patch2 = mock.patch("dallinger.recruiters.HotAirRecruiter.close_recruitment")
        with patch1 as f1, patch2 as f2:
            recruiter.close_recruitment()
            f1.assert_called_once()
            f2.assert_called_once()
