import mock
import pytest
from dallinger.models import Participant
from dallinger.experiment import Experiment


class TestRecruiters(object):

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

    def test_for_experiment(self):
        from dallinger.recruiters import Recruiter
        mock_exp = mock.MagicMock(spec=Experiment)
        Recruiter.for_experiment(mock_exp)

        mock_exp.recruiter.assert_called()

    def test_notify_recruited(self, recruiter):
        dummy = mock.NonCallableMock()
        recruiter.notify_recruited(participant=dummy)


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
        assert len(result) == 1

    def test_open_recruitment_multiple(self, recruiter):
        result = recruiter.open_recruitment(n=3)
        assert len(result) == 3

    def test_open_recruitment_results_are_urls(self, recruiter):
        assert '/ad?assignmentId=' in recruiter.open_recruitment()[0]

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_approve_hit(self, recruiter):
        assert recruiter.approve_hit('any assignment id')

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus('any assignment id', 0.01, "You're great!")

    def test_open_recruitment_uses_configured_mode(self, recruiter, active_config):
        active_config.extend({'mode': u'new_mode'})
        assert 'mode=new_mode' in recruiter.open_recruitment()[0]


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
        assert len(result) == 1

    def test_open_recruitment_multiple(self, recruiter):
        result = recruiter.open_recruitment(n=3)
        assert len(result) == 3

    def test_open_recruitment_results_are_urls(self, recruiter):
        assert '/ad?assignmentId=' in recruiter.open_recruitment()[0]

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_approve_hit(self, recruiter):
        assert recruiter.approve_hit('any assignment id')

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus('any assignment id', 0.01, "You're great!")

    def test_open_recruitment_ignores_configured_mode(self, recruiter, active_config):
        active_config.extend({'mode': u'new_mode'})
        assert 'mode=debug' in recruiter.open_recruitment()[0]


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
        assert recruiter.open_recruitment() == []

    def test_open_recruitment_multiple_returns_empty_result(self, recruiter):
        assert recruiter.open_recruitment(n=3) == []


class TestBotRecruiter(object):

    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import BotRecruiter
        with mock.patch.multiple('dallinger.recruiters',
                                 q=mock.DEFAULT,
                                 get_base_url=mock.DEFAULT) as mocks:
            mocks['get_base_url'].return_value = 'fake_base_url'
            r = BotRecruiter(config={})
            r._get_bot_class = mock.Mock()
            yield r

    def test_recruit_returns_list(self, recruiter):
        result = recruiter.recruit(n=2)
        assert len(result) == 2

    def test_recruit_returns_urls(self, recruiter):
        result = recruiter.recruit()
        assert result[0].startswith('fake_base_url')

    def test_open_recruitment_returns_list(self, recruiter):
        result = recruiter.open_recruitment(n=2)
        assert len(result) == 2

    def test_open_recruitment_returns_urls(self, recruiter):
        result = recruiter.open_recruitment()
        assert result[0].startswith('fake_base_url')

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus('any assignment id', 0.01, "You're great!")


@pytest.mark.usefixtures('experiment_dir')
class TestMTurkRecruiterAssumesConfigFileInCWD(object):

    def test_instantiation_from_current_config(self):
        from dallinger.recruiters import MTurkRecruiter
        recruiter = MTurkRecruiter.from_current_config()
        assert recruiter.config.get('title') == 'Stroop task'


class TestMTurkRecruiter(object):

    @pytest.fixture
    def recruiter(self, stub_config):
        from dallinger.mturk import MTurkService
        from dallinger.recruiters import MTurkRecruiter
        mockservice = mock.create_autospec(MTurkService)
        r = MTurkRecruiter(
            config=stub_config,
            hit_domain='fake-domain',
            ad_url='http://fake-domain/ad'
        )
        r.mturkservice = mockservice('fake key', 'fake secret')
        r.mturkservice.check_credentials = mock.Mock(return_value=True)
        r.mturkservice.create_hit = mock.Mock(return_value={
            'type_id': 'fake type id'
        })
        return r

    def test_config_passed_to_constructor(self, recruiter):
        assert recruiter.config.get('title') == 'fake experiment title'

    def test_open_recruitment_returns_one_item_list(self, recruiter):
        result = recruiter.open_recruitment(n=2)
        assert len(result) == 1

    def test_open_recruitment_returns_urls(self, recruiter):
        result = recruiter.open_recruitment(n=1)
        assert result[0] == 'https://workersandbox.mturk.com/mturk/preview?groupId=fake type id'

    def test_open_recruitment_raises_if_no_external_hit_domain_configured(self, recruiter):
        from dallinger.recruiters import MTurkRecruiterException
        recruiter.hit_domain = None
        with pytest.raises(MTurkRecruiterException):
            recruiter.open_recruitment(n=1)

    def test_open_recruitment_raises_in_debug_mode(self, recruiter):
        from dallinger.recruiters import MTurkRecruiterException
        recruiter.config.set('mode', u'debug')
        with pytest.raises(MTurkRecruiterException):
            recruiter.open_recruitment()

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

    def test_open_recruitment_is_noop_if_experiment_in_progress(self, recruiter, db_session):
        from dallinger.models import Participant
        participant = Participant(
            worker_id='1', hit_id='1', assignment_id='1', mode="test")
        db_session.add(participant)
        recruiter.open_recruitment()

        recruiter.mturkservice.check_credentials.assert_not_called()

    def test_current_hit_id_with_active_experiment(self, recruiter, db_session):
        from dallinger.models import Participant
        participant = Participant(
            worker_id='1', hit_id='the hit!', assignment_id='1', mode="test")
        db_session.add(participant)

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
