import mock
import os
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


class TestHotAirRecruiter(object):

    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import HotAirRecruiter
        from dallinger.config import get_config
        os.chdir('tests/experiment')
        config = get_config()
        if not config.ready:
            config.load()
        yield HotAirRecruiter()
        os.chdir('../..')

    def test_open_recruitment(self, recruiter):
        recruiter.open_recruitment()

    def test_recruit(self, recruiter):
        recruiter.recruit()

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()

    def test_approve_hit(self, recruiter):
        assert recruiter.approve_hit('any assignment id')

    def test_reward_bonus(self, recruiter):
        recruiter.reward_bonus('any assignment id', 0.01, "You're great!")


class TestBotRecruiter(object):

    @pytest.fixture
    def recruiter(self):
        from dallinger.recruiters import BotRecruiter
        return BotRecruiter(config={})

    @pytest.mark.xfail
    def test_open_recruitment(self, recruiter):
        recruiter.open_recruitment()

    @pytest.mark.xfail
    def test_recruit(self, recruiter):
        recruiter.recruit()

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

    def test_open_recruitment_single_recruitee(self, recruiter):
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url='http://fake-domain/ad',
            approve_requirement=95,
            description=u'fake HIT description',
            duration_hours=1.0,
            keywords=(u'kw1', u'kw2', u'kw3'),
            lifetime_days=1,
            max_assignments=1,
            notification_url=u'https://url-of-notification-route',
            reward=0.01,
            title=u'fake experiment title',
            us_only=True,
            blacklist=(),
            blacklist_experience_limit=None,
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

    def test_open_recruitment_with_blacklist(self, recruiter):
        recruiter.config.set('qualification_blacklist', u'foo, bar')
        recruiter.config.set('qualification_blacklist_experience_limit', 0)
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url='http://fake-domain/ad',
            approve_requirement=95,
            description='fake HIT description',
            duration_hours=1.0,
            lifetime_days=1,
            keywords=(u'kw1', u'kw2', u'kw3'),
            max_assignments=1,
            notification_url='https://url-of-notification-route',
            reward=0.01,
            title='fake experiment title',
            us_only=True,
            blacklist=('foo', 'bar'),
            blacklist_experience_limit=0,
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

    def test_approve_hit(self, recruiter):
        fake_id = 'fake assignment id'
        recruiter.approve_hit(fake_id)

        recruiter.mturkservice.approve_assignment.assert_called_once_with(fake_id)

    def test_close_recruitment(self, recruiter):
        recruiter.close_recruitment()
        # This test is for coverage; the method doesn't do anything.

    def test_notify_recruited_when_group_name_not_specified(self, recruiter):
        participant = mock.Mock(spec=Participant, worker_id='some worker id')
        recruiter.notify_recruited(participant)

        recruiter.mturkservice.increment_qualification_score.assert_called_once_with(
            'some experiment uid',
            'some worker id',
            notify=False,
        )

    def test_notify_recruited_when_group_name_specified(self, recruiter):
        participant = mock.Mock(spec=Participant, worker_id='some worker id')
        recruiter.config.set('group_name', u'some existing group_name')
        recruiter.notify_recruited(participant)

        recruiter.mturkservice.increment_qualification_score.assert_has_calls([
            mock.call('some experiment uid', 'some worker id', notify=False),
            mock.call('some existing group_name', 'some worker id', notify=False)
        ], any_order=True)

    def test_notify_recruited_nonexistent_qualification(self, recruiter):
        from dallinger.mturk import QualificationNotFoundException
        participant = mock.Mock(spec=Participant, worker_id='some worker id')
        error = QualificationNotFoundException("Ouch!")
        recruiter.mturkservice.increment_qualification_score.side_effect = error

        # logs, but does not raise:
        recruiter.notify_recruited(participant)
