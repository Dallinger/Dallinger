#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import mock
import pytest
import dallinger.db
import datetime
import signal
from dallinger.config import get_config
from dallinger.heroku import app_name
from dallinger.heroku.messages import EmailingHITMessager
from dallinger.heroku.messages import NullHITMessager
from dallinger.models import Participant


@pytest.fixture
def run_check():
    db = dallinger.db.init_db(drop_all=True)
    os.chdir('tests/experiment')
    config = get_config()
    if not config.ready:
        config.load()
    # Import the FUT here, after config load, and return it
    from dallinger.heroku.clock import run_check
    yield run_check
    db.rollback()
    db.close()
    os.chdir('../..')


class TestHeroku(object):

    def test_heroku_app_name(self):
        id = "8fbe62f5-2e33-4274-8aeb-40fc3dd621a0"
        assert(len(app_name(id)) < 30)


class TestClockScheduler(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        os.chdir('tests/experiment')
        config = get_config()
        config.ready = False
        from dallinger.heroku import clock
        self.clock = clock

    def teardown(self):
        os.chdir("../..")

    def test_scheduler_has_job(self):
        jobs = self.clock.scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].func_ref == 'dallinger.heroku.clock:check_db_for_missing_notifications'

    def test_clock_expects_config_to_be_ready(self):
        assert not get_config().ready
        jobs = self.clock.scheduler.get_jobs()
        with pytest.raises(RuntimeError) as excinfo:
            jobs[0].func()
        assert excinfo.match('Config not loaded')

    def test_launch_loads_config(self):
        original_start = self.clock.scheduler.start
        data = {'launched': False}

        def start():
            data['launched'] = True

        try:
            self.clock.scheduler.start = start
            self.clock.launch()
            assert data['launched']
            assert get_config().ready
        finally:
            self.clock.scheduler.start = original_start


class TestHerokuClockTasks(object):

    class a(object):

        @staticmethod
        def participant(**kwargs):
            defaults = {
                'worker_id': '1',
                'hit_id': '1',
                'assignment_id': '1',
                'mode': 'test',
            }
            defaults.update(kwargs)
            part = Participant(**defaults)
            part.creation_time = datetime.datetime.now()

            return part

    def test_check_db_for_missing_notifications_assembles_resources(self, run_check):
        # Can't import until after config is loaded:
        from dallinger.heroku.clock import check_db_for_missing_notifications
        with mock.patch.multiple('dallinger.heroku.clock',
                                 run_check=mock.DEFAULT,
                                 MTurkConnection=mock.DEFAULT) as mocks:
            mocks['MTurkConnection'].return_value = 'fake connection'
            check_db_for_missing_notifications()

            mocks['run_check'].assert_called()

    def test_does_nothing_if_assignment_still_current(self, run_check):
        config = {'duration': 1.0}
        mturk = mock.Mock(**{'get_assignment.return_value': ['fake']})
        participants = [self.a.participant()]
        session = None
        reference_time = datetime.datetime.now()
        run_check(config, mturk, participants, session, reference_time)

        mturk.get_assignment.assert_not_called()

    def test_sets_participant_status_if_mturk_reports_approved(self, run_check):
        config = {'duration': 1.0}
        fake_assignment = mock.Mock(AssignmentStatus='Approved')
        mturk = mock.Mock(**{'get_assignment.return_value': [fake_assignment]})
        participants = [self.a.participant()]
        session = mock.Mock()
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        run_check(config, mturk, participants, session, reference_time)

        assert participants[0].status == 'approved'
        session.commit.assert_called()

    def test_sets_participant_status_if_mturk_reports_rejected(self, run_check):
        config = {'duration': 1.0}
        fake_assignment = mock.Mock(AssignmentStatus='Rejected')
        mturk = mock.Mock(**{'get_assignment.return_value': [fake_assignment]})
        participants = [self.a.participant()]
        session = mock.Mock()
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        run_check(config, mturk, participants, session, reference_time)

        assert participants[0].status == 'rejected'
        session.commit.assert_called()

    def test_resubmits_notification_if_mturk_reports_submitted(self, run_check):
        # Include whimsical set to True to avoid error in the False code branch:
        config = {
            'duration': 1.0,
            'host': 'fakehost.herokuapp.com',
            'whimsical': True
        }
        fake_assignment = mock.Mock(AssignmentStatus='Submitted')
        mturk = mock.Mock(**{'get_assignment.return_value': [fake_assignment]})
        participants = [self.a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        with mock.patch('dallinger.heroku.clock.requests') as mock_requests:
            run_check(config, mturk, participants, session, reference_time)

            mock_requests.post.assert_called_once_with(
                'http://fakehost.herokuapp.com/notifications',
                data={
                    'Event.1.EventType': 'AssignmentSubmitted',
                    'Event.1.AssignmentId': participants[0].assignment_id
                }
            )

    def test_sends_notification_if_resubmitted(self, run_check):
        # Include whimsical set to True to avoid error in the False code branch:
        config = {
            'duration': 1.0,
            'host': 'fakehost.herokuapp.com',
            'whimsical': False
        }
        fake_assignment = mock.Mock(AssignmentStatus='Submitted')
        mturk = mock.Mock(**{'get_assignment.return_value': [fake_assignment]})
        participants = [self.a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        mock_messager = mock.Mock(spec=NullHITMessager)
        with mock.patch.multiple('dallinger.heroku.clock',
                                 requests=mock.DEFAULT,
                                 NullHITMessager=mock.DEFAULT) as mocks:
            mocks['NullHITMessager'].return_value = mock_messager
            run_check(config, mturk, participants, session, reference_time)
            mock_messager.send_resubmitted_msg.assert_called()

    def test_no_assignment_on_mturk_shuts_down_hit(self, run_check):
        # Include whimsical set to True to avoid error in the False code branch:
        config = {
            'duration': 1.0,
            'host': 'fakehost.herokuapp.com',
            'whimsical': True
        }
        mturk = mock.Mock(**{'get_assignment.return_value': []})
        participants = [self.a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        os_env_heroku_auth = None
        with mock.patch('dallinger.heroku.clock.requests') as mock_requests:
            run_check(config, mturk, participants, session, reference_time)

            mock_requests.patch.assert_called_once_with(
                'https://api.heroku.com/apps/fakehost/config-vars',
                data='{"auto_recruit": "false"}',
                headers={
                    "Accept": "application/vnd.heroku+json; version=3",
                    "Content-Type": "application/json",
                    "Authorization": "Bearer {}".format(os_env_heroku_auth),
                }
            )

            mock_requests.post.assert_called_once_with(
                'http://fakehost.herokuapp.com/notifications',
                data={
                    'Event.1.EventType': 'NotificationMissing',
                    'Event.1.AssignmentId': participants[0].assignment_id
                }
            )

    def test_no_assignement_on_mturk_sends_hit_cancelled_message(self, run_check):
        # Include whimsical set to True to avoid error in the False code branch:
        config = {
            'duration': 1.0,
            'host': 'fakehost.herokuapp.com',
            'whimsical': False
        }
        mturk = mock.Mock(**{'get_assignment.return_value': []})
        participants = [self.a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        mock_messager = mock.Mock(spec=NullHITMessager)
        with mock.patch.multiple('dallinger.heroku.clock',
                                 requests=mock.DEFAULT,
                                 NullHITMessager=mock.DEFAULT) as mocks:
            mocks['NullHITMessager'].return_value = mock_messager
            run_check(config, mturk, participants, session, reference_time)
            mock_messager.send_hit_cancelled_msg.assert_called()


def emailing_messager(whimsical):
    from smtplib import SMTP
    config = {
        'whimsical': whimsical,
        'dallinger_email_username': 'test',
        'contact_email_on_error': 'contact@example.com',
        'dallinger_email_key': 'email secret key'
    }
    mock_smtp = mock.create_autospec(SMTP)
    messager = EmailingHITMessager(
        when='the time',
        assignment_id='some assignment id',
        hit_duration=60,
        time_active=120,
        config=config,
        server=mock_smtp
    )

    return messager


@pytest.fixture
def whimsical():
    return emailing_messager(whimsical=True)


@pytest.fixture
def nonwhimsical():
    return emailing_messager(whimsical=False)


class TestEmailingHITMessager(object):

    def test_send_resubmitted_msg_whimsical(self, whimsical):
        data = whimsical.send_resubmitted_msg()

        whimsical.server.starttls.assert_called()
        whimsical.server.login.assert_called_once_with('test', 'email secret key')
        whimsical.server.sendmail.assert_called()
        whimsical.server.quit.assert_called()
        assert data['subject'] == 'A matter of minor concern.'
        assert 'a full 1.0 minutes over' in data['message']

    def test_send_resubmitted_msg_nonwhimsical(self, nonwhimsical):
        data = nonwhimsical.send_resubmitted_msg()

        nonwhimsical.server.starttls.assert_called()
        nonwhimsical.server.login.assert_called_once_with('test', 'email secret key')
        nonwhimsical.server.sendmail.assert_called()
        nonwhimsical.server.quit.assert_called()
        assert data['subject'] == 'Dallinger automated email - minor error.'
        assert 'Allowed time: 1.0' in data['message']

    def test_send_hit_cancelled_msg_whimsical(self, whimsical):
        data = whimsical.send_hit_cancelled_msg()

        whimsical.server.starttls.assert_called()
        whimsical.server.login.assert_called_once_with('test', 'email secret key')
        whimsical.server.sendmail.assert_called()
        whimsical.server.quit.assert_called()
        assert data['subject'] == 'Most troubling news.'
        assert 'a full 1.0 minutes over' in data['message']

    def test_send_hit_cancelled_msg_nonwhimsical(self, nonwhimsical):
        data = nonwhimsical.send_hit_cancelled_msg()

        nonwhimsical.server.starttls.assert_called()
        nonwhimsical.server.login.assert_called_once_with('test', 'email secret key')
        nonwhimsical.server.sendmail.assert_called()
        nonwhimsical.server.quit.assert_called()
        assert data['subject'] == 'Dallinger automated email - major error.'
        assert 'Allowed time: 1.0' in data['message']


@pytest.mark.usefixtures('bartlett_dir')
class TestHerokuLocalWrapper(object):

    @pytest.fixture
    def config(self):
        from dallinger.command_line import setup_experiment
        cwd = os.getcwd()
        config = get_config()
        if not config.ready:
            config.load()

        (id, tmp) = setup_experiment(verbose=True, exp_config={})

        os.chdir(tmp)
        yield config
        os.chdir(cwd)

    @pytest.fixture
    def output(self):

        class Output(object):

            def __init__(self):
                self.log = mock.Mock()
                self.error = mock.Mock()
                self.blather = mock.Mock()

        return Output()

    @pytest.fixture
    def heroku(self, config, env, output):
        from dallinger.heroku.tools import HerokuLocalWrapper
        wrapper = HerokuLocalWrapper(config, output, env=env)
        yield wrapper
        try:
            print "Calling stop() on {}".format(wrapper)
            wrapper.stop(signal.SIGKILL)
        except:
            pass

    def test_start(self, heroku):
        assert heroku.start()
        assert heroku.is_running

    def test_gives_up_after_timeout(self, heroku):
        from dallinger.heroku.tools import HerokuTimeoutError
        with pytest.raises(HerokuTimeoutError):
            heroku.start(timeout_secs=1)

    def test_quits_on_gunicorn_startup_error(self, heroku):
        from dallinger.heroku.tools import HerokuStartupError
        heroku.verbose = False  # more coverage
        heroku._stream = mock.Mock(return_value=['[DONE] Killing all processes'])
        with pytest.raises(HerokuStartupError):
            heroku.start()

    def test_start_fails_if_stream_ends_without_matching_success_regex(self, heroku):
        from dallinger.heroku.tools import HerokuStartupError
        heroku._stream = mock.Mock(
            return_value=['apple', 'orange', heroku.STREAM_SENTINEL]
        )
        heroku.success_regex = 'not going to match anything'
        with pytest.raises(HerokuStartupError):
            heroku.start()
        assert not heroku.is_running

    def test_stop(self, heroku):
        heroku.start()
        heroku.stop(signal.SIGKILL)
        heroku.out.log.assert_called_with('Local Heroku process terminated.')

    def test_stop_on_killed_process_no_error(self, heroku):
        heroku.start()
        heroku._process.terminate()
        heroku.stop()
        mock.call("Local Heroku was already terminated.") in heroku.out.log.mock_calls

    def test_start_when_shell_command_fails(self, heroku):
        heroku.shell_command = 'nonsense'
        with pytest.raises(OSError):
            heroku.start()
            heroku.out.error.assert_called_with(
                "Couldn't start Heroku for local debugging.")

    def test_stop_before_start_is_noop(self, heroku):
        heroku.stop()
        heroku.out.log.assert_called_with("No local Heroku process was running.")

    def test_start_when_already_started_is_noop(self, heroku):
        heroku.start()
        heroku.start()
        heroku.out.log.assert_called_with("Local Heroku is already running.")

    def test_monitor(self, heroku):
        heroku._stream = mock.Mock(return_value=['apple', 'orange'])
        listener = mock.Mock()
        heroku.monitor(listener)
        listener.assert_has_calls([
            mock.call('apple'),
            mock.call('orange'),
        ])

    def test_monitor_stops_iterating_when_told(self, heroku):
        heroku._stream = mock.Mock(return_value=['apple', 'orange'])
        listener = mock.Mock()
        listener.return_value = heroku.MONITOR_STOP
        heroku.monitor(listener)
        listener.assert_has_calls([
            mock.call('apple'),
        ])

    def test_as_context_manager(self, config, env, output):
        from dallinger.heroku.tools import HerokuLocalWrapper
        with HerokuLocalWrapper(config, output, env=env) as heroku:
            assert heroku.is_running
        assert not heroku.is_running
