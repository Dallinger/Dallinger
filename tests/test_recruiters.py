import mock
import pytest
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
        assert mod.by_name('CLIRecruiter') == mod.CLIRecruiter

    def test_by_name_with_valid_nickname(self, mod):
        assert mod.by_name('bots') == mod.BotRecruiter

    def test_by_name_with_invalid_name(self, mod):
        assert mod.by_name('blah') is None

    def test_for_debug_mode(self, mod, stub_config):
        r = mod.from_config(stub_config)
        assert isinstance(r, mod.HotAirRecruiter)

    def test_recruiter_config_value_used_if_not_debug(self, mod, stub_config):
        stub_config.extend({'mode': u'sandbox', 'recruiter': u'CLIRecruiter'})
        r = mod.from_config(stub_config)
        assert isinstance(r, mod.CLIRecruiter)

    def test_debug_mode_trumps_recruiter_config_value(self, mod, stub_config):
        stub_config.extend({'recruiter': u'CLIRecruiter'})
        r = mod.from_config(stub_config)
        assert isinstance(r, mod.HotAirRecruiter)

    def test_bot_recruiter_trumps_debug_mode(self, mod, stub_config):
        stub_config.extend({'recruiter': u'bots'})
        r = mod.from_config(stub_config)
        assert isinstance(r, mod.BotRecruiter)

    def test_default_is_mturk_recruiter_if_not_debug(self, mod, active_config):
        active_config.extend({'mode': u'sandbox'})
        r = mod.from_config(active_config)
        assert isinstance(r, mod.MTurkRecruiter)

    def test_replay_setting_dictates_recruiter(self, mod, active_config):
        active_config.extend(
            {'replay': True, 'mode': u'sandbox', 'recruiter': u'CLIRecruiter'}
        )
        r = mod.from_config(active_config)
        assert isinstance(r, mod.HotAirRecruiter)

    def test_unknown_recruiter_name_raises(self, mod, stub_config):
        stub_config.extend({'mode': u'sandbox', 'recruiter': u'bogus'})
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
            recruiter.reward_bonus('any assignment id', 0.01, "You're great!")

    def test_notify_recruited(self, recruiter):
        dummy = mock.NonCallableMock()
        recruiter.notify_recruited(participant=dummy)

    def test_external_submission_url(self, recruiter):
        assert recruiter.external_submission_url is None

    def test_rejects_questionnaire_from_returns_none(self, recruiter):
        dummy = mock.NonCallableMock()
        assert recruiter.rejects_questionnaire_from(participant=dummy) is None

    def test_backward_compat(self, recruiter):
        assert recruiter() is recruiter


@pytest.mark.usefixtures('active_config')
class TestCLIRecruiter(object):

    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import CLIRecruiter
        yield CLIRecruiter()

    def test_recruit_recruits_one_by_default(self, recruiter):
        result = recruiter.recruit()
        assert len(result) == 1

    def test_recruit_results_are_urls(self, recruiter):
        assert '/ad?assignmentId=' in recruiter.recruit()[0]

    def test_recruit_multiple(self, recruiter):
        assert len(recruiter.recruit(n=3)) == 3

    def test_open_recruitment_recruits_one_by_default(self, recruiter):
        result = recruiter.open_recruitment()
        assert len(result['items']) == 1

    def test_open_recruitment_describes_how_it_works(self, recruiter):
        result = recruiter.open_recruitment()
        assert 'Search for "New participant requested:"' in result['message']

    def test_open_recruitment_multiple(self, recruiter):
        result = recruiter.open_recruitment(n=3)
        assert len(result['items']) == 3

    def test_open_recruitment_results_are_urls(self, recruiter):
        result = recruiter.open_recruitment()
        assert '/ad?assignmentId=' in result['items'][0]

    def test_open_recruitment_with_zero(self, recruiter):
        result = recruiter.open_recruitment(n=0)
        assert result['items'] == []

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_approve_hit(self, recruiter):
        assert recruiter.approve_hit('any assignment id')

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus('any assignment id', 0.01, "You're great!")

    def test_open_recruitment_uses_configured_mode(self, recruiter, active_config):
        active_config.extend({'mode': u'new_mode'})
        result = recruiter.open_recruitment()
        assert 'mode=new_mode' in result['items'][0]

    def test_returns_standard_submission_event_type(self, recruiter):
        assert recruiter.submitted_event() is 'AssignmentSubmitted'


@pytest.mark.usefixtures('active_config')
class TestHotAirRecruiter(object):

    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import HotAirRecruiter
        yield HotAirRecruiter()

    def test_recruit_recruits_one_by_default(self, recruiter):
        result = recruiter.recruit()
        assert len(result) == 1

    def test_recruit_results_are_urls(self, recruiter):
        assert '/ad?assignmentId=' in recruiter.recruit()[0]

    def test_recruit_multiple(self, recruiter):
        assert len(recruiter.recruit(n=3)) == 3

    def test_open_recruitment_recruits_one_by_default(self, recruiter):
        result = recruiter.open_recruitment()
        assert len(result['items']) == 1

    def test_open_recruitment_describes_how_it_works(self, recruiter):
        result = recruiter.open_recruitment()
        assert 'requests will open browser windows' in result['message']

    def test_open_recruitment_multiple(self, recruiter):
        result = recruiter.open_recruitment(n=3)
        assert len(result['items']) == 3

    def test_open_recruitment_results_are_urls(self, recruiter):
        result = recruiter.open_recruitment()
        assert '/ad?assignmentId=' in result['items'][0]

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_approve_hit(self, recruiter):
        assert recruiter.approve_hit('any assignment id')

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus('any assignment id', 0.01, "You're great!")

    def test_open_recruitment_ignores_configured_mode(self, recruiter, active_config):
        active_config.extend({'mode': u'new_mode'})
        result = recruiter.open_recruitment()
        assert 'mode=debug' in result['items'][0]

    def test_returns_standard_submission_event_type(self, recruiter):
        assert recruiter.submitted_event() is 'AssignmentSubmitted'


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
        assert recruiter.open_recruitment()['items'] == []

    def test_open_recruitment_multiple_returns_empty_result(self, recruiter):
        assert recruiter.open_recruitment(n=3)['items'] == []

    def test_returns_standard_submission_event_type(self, recruiter):
        assert recruiter.submitted_event() is 'AssignmentSubmitted'


class TestBotRecruiter(object):

    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import BotRecruiter
        with mock.patch.multiple('dallinger.recruiters',
                                 _get_queue=mock.DEFAULT,
                                 get_base_url=mock.DEFAULT) as mocks:
            mocks['get_base_url'].return_value = 'fake_base_url'
            r = BotRecruiter()
            r._get_bot_factory = mock.Mock()
            yield r

    def test_recruit_returns_list(self, recruiter):
        result = recruiter.recruit(n=2)
        assert len(result) == 2

    def test_recruit_returns_urls(self, recruiter):
        result = recruiter.recruit()
        assert result[0].startswith('fake_base_url')

    def test_open_recruitment_returns_list(self, recruiter):
        result = recruiter.open_recruitment(n=2)
        assert len(result['items']) == 2

    def test_open_recruitment_returns_urls(self, recruiter):
        result = recruiter.open_recruitment()
        assert result['items'][0].startswith('fake_base_url')

    def test_open_recruitment_describes_how_it_works(self, recruiter):
        result = recruiter.open_recruitment()
        assert "recruitment started using Mock" in result['message']

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus('any assignment id', 0.01, "You're great!")

    def test_returns_specific_submission_event_type(self, recruiter):
        assert recruiter.submitted_event() is 'BotAssignmentSubmitted'


@pytest.mark.usefixtures('active_config')
class TestMTurkRecruiter(object):

    @pytest.fixture
    def recruiter(self, active_config):
        from dallinger.mturk import MTurkService
        from dallinger.recruiters import MTurkRecruiter
        with mock.patch.multiple('dallinger.recruiters',
                                 os=mock.DEFAULT,
                                 get_base_url=mock.DEFAULT) as mocks:
            mocks['get_base_url'].return_value = 'http://fake-domain'
            mocks['os'].getenv.return_value = 'fake-host-domain'
            mockservice = mock.create_autospec(MTurkService)
            active_config.extend({'mode': u'sandbox'})
            r = MTurkRecruiter()
            r.mturkservice = mockservice('fake key', 'fake secret')
            r.mturkservice.check_credentials.return_value = True
            r.mturkservice.create_hit.return_value = {'type_id': 'fake type id'}
            return r

    def test_config_passed_to_constructor_sandbox(self, recruiter):
        assert recruiter.config.get('title') == 'fake experiment title'

    def test_external_submission_url_sandbox(self, recruiter):
        assert 'workersandbox.mturk.com' in recruiter.external_submission_url

    def test_external_submission_url_live(self, recruiter):
        recruiter.config.set('mode', u'live')
        assert 'www.mturk.com' in recruiter.external_submission_url

    def test_open_recruitment_returns_one_item_recruitments_list(self, recruiter):
        result = recruiter.open_recruitment(n=2)
        assert len(result['items']) == 1

    def test_open_recruitment_describes_how_it_works(self, recruiter):
        result = recruiter.open_recruitment()
        assert 'HIT now published to Amazon Mechanical Turk' in result['message']

    def test_open_recruitment_returns_urls(self, recruiter):
        url = recruiter.open_recruitment(n=1)['items'][0]
        assert url == 'https://workersandbox.mturk.com/mturk/preview?groupId=fake type id'

    def test_open_recruitment_raises_if_no_external_hit_domain_configured(self, recruiter):
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
            ad_url='http://fake-domain/ad',
            approve_requirement=95,
            description=u'fake HIT description',
            duration_hours=1.0,
            keywords=[u'kw1', u'kw2', u'kw3'],
            lifetime_days=1,
            max_assignments=1,
            notification_url=u'https://url-of-notification-route',
            reward=0.01,
            title=u'fake experiment title',
            us_only=True,
            blacklist=[],
        )

    def test_open_recruitment_creates_qualifications_for_experiment_app_id(self, recruiter):
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_qualification_type.assert_called_once_with(
            u'some experiment uid', 'Experiment-specific qualification'
        )

    def test_open_recruitment_creates_qualifications_for_exp_with_group_name(self, recruiter):
        recruiter.config.set('group_name', u'some group name')
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_qualification_type.assert_has_calls([
            mock.call(u'some experiment uid', 'Experiment-specific qualification'),
            mock.call(u'some group name', 'Experiment group qualification')
        ], any_order=True)

    def test_open_recruitment_when_qualification_already_exists(self, recruiter):
        from dallinger.mturk import DuplicateQualificationNameError
        mturk = recruiter.mturkservice
        mturk.create_qualification_type.side_effect = DuplicateQualificationNameError

        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once()

    def test_open_recruitment_with_blacklist(self, recruiter):
        recruiter.config.set('qualification_blacklist', u'foo, bar')
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url='http://fake-domain/ad',
            approve_requirement=95,
            description='fake HIT description',
            duration_hours=1.0,
            lifetime_days=1,
            keywords=[u'kw1', u'kw2', u'kw3'],
            max_assignments=1,
            notification_url='https://url-of-notification-route',
            reward=0.01,
            title='fake experiment title',
            us_only=True,
            blacklist=['foo', 'bar'],
        )

    def test_open_recruitment_is_noop_if_experiment_in_progress(self, a, recruiter):
        a.participant()
        recruiter.open_recruitment()

        recruiter.mturkservice.check_credentials.assert_not_called()

    def test_supresses_assignment_submitted(self, recruiter):
        assert recruiter.submitted_event() is None

    def test_current_hit_id_with_active_experiment(self, a, recruiter):
        a.participant(hit_id=u'the hit!')

        assert recruiter.current_hit_id() == 'the hit!'

    def test_current_hit_id_with_no_active_experiment(self, recruiter):
        assert recruiter.current_hit_id() is None

    def test_recruit_auto_recruit_on_recruits_for_current_hit(self, recruiter):
        fake_hit_id = 'fake HIT id'
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.recruit()

        recruiter.mturkservice.extend_hit.assert_called_once_with(
            fake_hit_id,
            number=1,
            duration_hours=1.0
        )

    def test_recruit_auto_recruit_off_does_not_extend_hit(self, recruiter):
        recruiter.config['auto_recruit'] = False
        fake_hit_id = 'fake HIT id'
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.recruit()

        assert not recruiter.mturkservice.extend_hit.called

    def test_recruit_no_current_hit_does_not_extend_hit(self, recruiter):
        recruiter.current_hit_id = mock.Mock(return_value=None)
        recruiter.recruit()

        assert not recruiter.mturkservice.extend_hit.called

    def test_recruit_extend_hit_error_is_logged_politely(self, recruiter):
        from dallinger.mturk import MTurkServiceException
        fake_hit_id = 'fake HIT id'
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.mturkservice.extend_hit.side_effect = MTurkServiceException("Boom!")
        with mock.patch('dallinger.recruiters.logger') as mock_logger:
            recruiter.recruit()

        mock_logger.exception.assert_called_once_with("Boom!")

    def test_reward_bonus_is_simple_passthrough(self, recruiter):
        recruiter.reward_bonus(
            assignment_id='fake assignment id',
            amount=2.99,
            reason='well done!'
        )

        recruiter.mturkservice.grant_bonus.assert_called_once_with(
            assignment_id='fake assignment id',
            amount=2.99,
            reason='well done!'
        )

    def test_reward_bonus_logs_exception(self, recruiter):
        from dallinger.mturk import MTurkServiceException
        recruiter.mturkservice.grant_bonus.side_effect = MTurkServiceException("Boom!")
        with mock.patch('dallinger.recruiters.logger') as mock_logger:
            recruiter.reward_bonus('fake-assignment', 2.99, 'fake reason')

        mock_logger.exception.assert_called_once_with("Boom!")

    def test_approve_hit(self, recruiter):
        fake_id = 'fake assignment id'
        recruiter.approve_hit(fake_id)

        recruiter.mturkservice.approve_assignment.assert_called_once_with(fake_id)

    def test_approve_hit_logs_exception(self, recruiter):
        from dallinger.mturk import MTurkServiceException
        recruiter.mturkservice.approve_assignment.side_effect = MTurkServiceException("Boom!")
        with mock.patch('dallinger.recruiters.logger') as mock_logger:
            recruiter.approve_hit('fake-hit-id')

        mock_logger.exception.assert_called_once_with("Boom!")

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()
        # This test is for coverage; the method doesn't do anything.

    def test_notify_recruited_when_group_name_not_specified(self, recruiter):
        participant = mock.Mock(spec=Participant, worker_id='some worker id')
        recruiter.notify_recruited(participant)

        recruiter.mturkservice.increment_qualification_score.assert_called_once_with(
            'some experiment uid',
            'some worker id',
        )

    def test_notify_recruited_when_group_name_specified(self, recruiter):
        participant = mock.Mock(spec=Participant, worker_id='some worker id')
        recruiter.config.set('group_name', u'some existing group_name')
        recruiter.notify_recruited(participant)

        recruiter.mturkservice.increment_qualification_score.assert_has_calls([
            mock.call('some experiment uid', 'some worker id'),
            mock.call('some existing group_name', 'some worker id')
        ], any_order=True)

    def test_notify_recruited_nonexistent_qualification(self, recruiter):
        from dallinger.mturk import QualificationNotFoundException
        participant = mock.Mock(spec=Participant, worker_id='some worker id')
        error = QualificationNotFoundException("Ouch!")
        recruiter.mturkservice.increment_qualification_score.side_effect = error

        # logs, but does not raise:
        recruiter.notify_recruited(participant)

    def test_rejects_questionnaire_from_returns_none_if_working(self, recruiter):
        participant = mock.Mock(spec=Participant, status="working")
        assert recruiter.rejects_questionnaire_from(participant) is None

    def test_rejects_questionnaire_from_returns_error_if_already_submitted(self, recruiter):
        participant = mock.Mock(spec=Participant, status="submitted")
        rejection = recruiter.rejects_questionnaire_from(participant)
        assert "already sumbitted their HIT" in rejection


@pytest.mark.usefixtures('active_config')
class TestMTurkLargeRecruiter(object):

    @pytest.fixture
    def recruiter(self, active_config):
        from dallinger.mturk import MTurkService
        from dallinger.recruiters import MTurkLargeRecruiter
        with mock.patch.multiple('dallinger.recruiters',
                                 os=mock.DEFAULT,
                                 get_base_url=mock.DEFAULT) as mocks:
            mocks['get_base_url'].return_value = 'http://fake-domain'
            mocks['os'].getenv.return_value = 'fake-host-domain'
            mockservice = mock.create_autospec(MTurkService)
            active_config.extend({'mode': u'sandbox'})
            r = MTurkLargeRecruiter()
            r.mturkservice = mockservice('fake key', 'fake secret')
            r.mturkservice.check_credentials.return_value = True
            r.mturkservice.create_hit.return_value = {'type_id': 'fake type id'}
            return r

    def test_open_recruitment_single_recruitee(self, recruiter):
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url='http://fake-domain/ad',
            approve_requirement=95,
            description='fake HIT description',
            duration_hours=1.0,
            keywords=['kw1', 'kw2', 'kw3'],
            lifetime_days=1,
            max_assignments=10,
            notification_url='https://url-of-notification-route',
            reward=0.01,
            title='fake experiment title',
            us_only=True,
            blacklist=[],
        )

    def test_more_than_ten_can_be_recruited_on_open(self, recruiter):
        recruiter.open_recruitment(n=20)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url='http://fake-domain/ad',
            approve_requirement=95,
            description='fake HIT description',
            duration_hours=1.0,
            keywords=['kw1', 'kw2', 'kw3'],
            lifetime_days=1,
            max_assignments=20,
            notification_url='https://url-of-notification-route',
            reward=0.01,
            title='fake experiment title',
            us_only=True,
            blacklist=[],
        )

    def test_recruit_participants_auto_recruit_on_recruits_for_current_hit(self, recruiter):
        fake_hit_id = 'fake HIT id'
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.open_recruitment(n=1)
        recruiter.recruit(n=9)
        recruiter.mturkservice.extend_hit.assert_not_called()
        recruiter.recruit(n=1)
        recruiter.mturkservice.extend_hit.assert_called_once_with(
            'fake HIT id',
            duration_hours=1.0,
            number=1
        )

    def test_recruiting_partially_from_preallocated_pool(self, recruiter):
        fake_hit_id = 'fake HIT id'
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.open_recruitment(n=1)
        recruiter.recruit(n=5)
        recruiter.mturkservice.extend_hit.assert_not_called()
        recruiter.recruit(n=10)
        recruiter.mturkservice.extend_hit.assert_called_once_with(
            'fake HIT id',
            duration_hours=1.0,
            number=6
        )

    def test_recruit_auto_recruit_off_does_not_extend_hit(self, recruiter):
        recruiter.config['auto_recruit'] = False
        fake_hit_id = 'fake HIT id'
        recruiter.current_hit_id = mock.Mock(return_value=fake_hit_id)
        recruiter.recruit()

        assert not recruiter.mturkservice.extend_hit.called
