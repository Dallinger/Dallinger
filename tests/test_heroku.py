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
from dallinger.heroku.messages import EmailingHITMessenger
from dallinger.heroku.messages import EmailConfig


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


@pytest.fixture
def check_call():
    with mock.patch('dallinger.heroku.tools.check_call') as check_call:
        yield check_call


@pytest.fixture
def check_output():
    with mock.patch('dallinger.heroku.tools.check_output') as check_output:
        yield check_output


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

    def test_check_db_for_missing_notifications_assembles_resources(self, run_check):
        # Can't import until after config is loaded:
        from dallinger.heroku.clock import check_db_for_missing_notifications
        with mock.patch.multiple('dallinger.heroku.clock',
                                 run_check=mock.DEFAULT,
                                 MTurkService=mock.DEFAULT) as mocks:
            mocks['MTurkService'].return_value = 'fake connection'
            check_db_for_missing_notifications()

            mocks['run_check'].assert_called()

    def test_does_nothing_if_assignment_still_current(self, a, stub_config, run_check):
        mturk = mock.Mock(**{'get_assignment.return_value': ['fake']})
        participants = [a.participant()]
        session = None
        reference_time = datetime.datetime.now()
        run_check(stub_config, mturk, participants, session, reference_time)

        mturk.get_assignment.assert_not_called()

    def test_rejects_bot_participants(self, a, stub_config, run_check):
        from dallinger.recruiters import BotRecruiter
        mturk = mock.Mock(**{'get_assignment.return_value': ['fake']})
        participants = [a.participant(recruiter_id=BotRecruiter.nickname)]
        session = mock.Mock()
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        run_check(stub_config, mturk, participants, session, reference_time)

        assert participants[0].status == 'rejected'
        session.commit.assert_called()

    def test_sets_participant_status_if_mturk_reports_approved(self, a, stub_config, run_check):
        fake_assignment = {'status': 'Approved'}
        mturk = mock.Mock(**{'get_assignment.return_value': fake_assignment})
        participants = [a.participant()]
        session = mock.Mock()
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        run_check(stub_config, mturk, participants, session, reference_time)

        assert participants[0].status == 'approved'
        session.commit.assert_called()

    def test_sets_participant_status_if_mturk_reports_rejected(self, a, stub_config, run_check):
        fake_assignment = {'status': 'Rejected'}
        mturk = mock.Mock(**{'get_assignment.return_value': fake_assignment})
        participants = [a.participant()]
        session = mock.Mock()
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        run_check(stub_config, mturk, participants, session, reference_time)

        assert participants[0].status == 'rejected'
        session.commit.assert_called()

    def test_resubmits_notification_if_mturk_reports_submitted(self, a, stub_config, run_check):
        # Include whimsical set to True to avoid error in the False code branch:
        stub_config.extend({'host': u'fakehost.herokuapp.com'})
        fake_assignment = {'status': 'Submitted'}
        mturk = mock.Mock(**{'get_assignment.return_value': fake_assignment})
        participants = [a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        with mock.patch('dallinger.heroku.clock.requests') as mock_requests:
            run_check(stub_config, mturk, participants, session, reference_time)

            mock_requests.post.assert_called_once_with(
                'http://fakehost.herokuapp.com/notifications',
                data={
                    'Event.1.EventType': 'AssignmentSubmitted',
                    'Event.1.AssignmentId': participants[0].assignment_id
                }
            )

    def test_sends_notification_if_resubmitted(self, a, stub_config, run_check):
        fake_assignment = {'status': 'Submitted'}
        mturk = mock.Mock(**{'get_assignment.return_value': fake_assignment})
        participants = [a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        mock_messenger = mock.Mock(spec=EmailingHITMessenger)
        with mock.patch.multiple('dallinger.heroku.clock',
                                 requests=mock.DEFAULT,
                                 get_messenger=mock.DEFAULT) as mocks:
            mocks['get_messenger'].return_value = mock_messenger
            run_check(stub_config, mturk, participants, session, reference_time)
            mock_messenger.send_resubmitted_msg.assert_called()

    def test_no_assignment_on_mturk_shuts_down_hit(self, a, stub_config, run_check):
        # Include whimsical set to True to avoid error in the False code branch:
        stub_config.extend({'host': u'fakehost.herokuapp.com'})
        mturk = mock.Mock(**{'get_assignment.return_value': None})
        participants = [a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        with mock.patch('dallinger.heroku.clock.requests') as mock_requests:
            run_check(stub_config, mturk, participants, session, reference_time)

            mock_requests.patch.assert_called_once_with(
                'https://api.heroku.com/apps/fakehost/config-vars',
                data='{"auto_recruit": "false"}',
                headers={
                    "Accept": "application/vnd.heroku+json; version=3",
                    "Content-Type": "application/json",
                    "Authorization": "Bearer {}".format('heroku secret'),
                }
            )

            mock_requests.post.assert_called_once_with(
                'http://fakehost.herokuapp.com/notifications',
                data={
                    'Event.1.EventType': 'NotificationMissing',
                    'Event.1.AssignmentId': participants[0].assignment_id
                }
            )

    def test_no_assignment_on_mturk_sends_hit_cancelled_message(self, a, stub_config, run_check):
        mturk = mock.Mock(**{'get_assignment.return_value': None})
        participants = [a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        mock_messenger = mock.Mock(spec=EmailingHITMessenger)
        with mock.patch.multiple('dallinger.heroku.clock',
                                 requests=mock.DEFAULT,
                                 get_messenger=mock.DEFAULT) as mocks:
            mocks['get_messenger'].return_value = mock_messenger
            run_check(stub_config, mturk, participants, session, reference_time)
            mock_messenger.send_hit_cancelled_msg.assert_called()


@pytest.fixture
def hit_summary():
    from dallinger.heroku.messages import HITSummary
    return HITSummary(
        assignment_id='some assignment id',
        duration=60,
        time_active=120,
        app_id='some app id',
        when='the time',
    )


class TestEmailConfig(object):

    @pytest.fixture
    def klass(self):
        from dallinger.heroku.messages import EmailConfig
        return EmailConfig

    def test_catches_missing_config_values(self, klass, stub_config):
        stub_config.extend({
            'dallinger_email_address': u'',
            'contact_email_on_error': u'',
            'smtp_username': u'???',
            'smtp_password': u'???',
        })
        econfig = klass(stub_config)
        problems = econfig.validate()
        assert problems == (
            'Missing or invalid config values: contact_email_on_error, '
            'dallinger_email_address, smtp_password, smtp_username'
        )


def emailing_messenger(summary, config):
    messenger = EmailingHITMessenger(
        hit_info=summary,
        email_settings=EmailConfig(config)
    )

    return messenger


@pytest.fixture
def whimsical(hit_summary, stub_config):
    stub_config.extend({'whimsical': True})
    return emailing_messenger(hit_summary, stub_config)


@pytest.fixture
def nonwhimsical(hit_summary, stub_config):
    stub_config.extend({'whimsical': False})
    return emailing_messenger(hit_summary, stub_config)


class TestMessengerFactory(object):

    @pytest.fixture
    def factory(self):
        from dallinger.heroku.messages import get_messenger
        return get_messenger

    def test_returns_debug_version_if_configured(self, factory, stub_config, hit_summary):
        from dallinger.heroku.messages import DebugHITMessenger
        assert isinstance(factory(hit_summary, stub_config), DebugHITMessenger)

    def test_returns_emailing_version_if_configured(self, factory, stub_config, hit_summary):
        from dallinger.heroku.messages import EmailingHITMessenger
        stub_config.extend({'mode': u'sandbox'})
        assert isinstance(factory(hit_summary, stub_config), EmailingHITMessenger)

    def test_returns_debug_version_if_email_config_invalid(self, factory, stub_config, hit_summary):
        from dallinger.heroku.messages import DebugHITMessenger
        stub_config.extend({'mode': u'sandbox', 'dallinger_email_address': u''})
        assert isinstance(factory(hit_summary, stub_config), DebugHITMessenger)


@pytest.mark.usefixtures('dummy_mailer')
class TestEmailingHITMessenger(object):

    def test_send_negotiates_email_server(self, whimsical, dummy_mailer):
        whimsical.send_resubmitted_msg()

        assert whimsical.server is dummy_mailer
        whimsical.server.starttls.assert_called()
        whimsical.server.login.assert_called_once_with(
            'fake email username', 'fake email password'
        )
        whimsical.server.sendmail.assert_called()
        whimsical.server.quit.assert_called()
        assert whimsical.server.sendmail.call_args[0][0] == u'test@example.com'
        assert whimsical.server.sendmail.call_args[0][1] == u'error_contact@test.com'

    def test_wraps_mail_server_exceptions(self, whimsical, dummy_mailer):
        import smtplib
        from dallinger.heroku.messages import MessengerError
        dummy_mailer.login.side_effect = smtplib.SMTPException("Boom!")
        with pytest.raises(MessengerError):
            whimsical.send_resubmitted_msg()

    def test_send_resubmitted_msg_whimsical(self, whimsical):
        data = whimsical.send_resubmitted_msg()
        assert data['subject'] == 'A matter of minor concern.'
        assert 'a full 1 minutes over' in data['message']

    def test_send_resubmitted_msg_nonwhimsical(self, nonwhimsical):
        data = nonwhimsical.send_resubmitted_msg()
        assert data['subject'] == 'Dallinger automated email - minor error.'
        assert 'Allowed time: 1' in data['message']

    def test_send_hit_cancelled_msg_whimsical(self, whimsical):
        data = whimsical.send_hit_cancelled_msg()
        assert data['subject'] == 'Most troubling news.'
        assert 'a full 1 minutes over' in data['message']

    def test_send_hit_cancelled_msg_nonwhimsical(self, nonwhimsical):
        data = nonwhimsical.send_hit_cancelled_msg()
        assert data['subject'] == 'Dallinger automated email - major error.'
        assert 'Allowed time: 1' in data['message']

    def test_send_idle_experiment_msg(self, nonwhimsical):
        data = nonwhimsical.send_idle_experiment_msg()
        assert data['subject'] == 'Idle Experiment.'

    def test_send_hit_error_msg(self, nonwhimsical):
        data = nonwhimsical.send_hit_error_msg()
        assert data['subject'] == 'Error during HIT.'


class TestHerokuUtilFunctions(object):

    @pytest.fixture
    def heroku(self):
        from dallinger.heroku import tools
        return tools

    def test_auth_token(self, heroku, check_output):
        check_output.return_value = b'some response '
        assert heroku.auth_token() == u'some response'

    def test_log_in_ok(self, heroku, check_output):
        check_output.return_value = b'all good'
        heroku.log_in()

    def test_log_in_fails(self, heroku, check_output):
        check_output.side_effect = Exception('boom!')
        with pytest.raises(Exception) as excinfo:
            heroku.log_in()
        assert excinfo.match('You are not logged into Heroku.')


class TestHerokuApp(object):

    @pytest.fixture
    def temp_repo(self, in_tempdir, stub_config):
        from dallinger.utils import GitClient
        stub_config.write()
        config = {'user.name': 'Test User', 'user.email': 'test@example.com'}
        git = GitClient()
        git.init(config=config)
        git.add("--all")
        git.commit("Test Repo")

    @pytest.fixture
    def full_app(self):
        from dallinger.heroku.tools import HerokuApp
        the_app = HerokuApp(dallinger_uid='fake-uid', output=None, team=None)
        yield the_app
        the_app.destroy()

    @pytest.fixture
    def app(self):
        from dallinger.heroku.tools import HerokuApp
        with mock.patch('dallinger.heroku.tools.subprocess'):
            the_app = HerokuApp(
                dallinger_uid='fake-uid', output=None, team="fake team"
            )
            yield the_app

    def test_name(self, app):
        assert app.name == u'dlgr-fake-uid'

    def test_url(self, app):
        assert app.url == u'https://dlgr-fake-uid.herokuapp.com'

    def test_dashboard_url(self, app):
        assert app.dashboard_url == u'https://dashboard.heroku.com/apps/dlgr-fake-uid'

    def test_bootstrap_creates_app_with_team(self, app, check_call, check_output):
        check_output.return_value = 'test@example.com'
        app.team = 'some-team'
        app.bootstrap()
        check_call.assert_has_calls([
            mock.call(['heroku', 'apps:create', 'dlgr-fake-uid', '--buildpack',
                       'heroku/python',
                       '--org', 'some-team'], stdout=None),
        ])

    def test_bootstrap_sets_variables(self, app, check_call, check_output):
        check_output.return_value = 'test@example.com'
        app.team = 'some-team'
        app.bootstrap()
        check_call.assert_called_with(
            ['heroku', 'config:set',
             'CREATOR=test@example.com',
             'DALLINGER_UID=fake-uid',
             'HOST=https://dlgr-fake-uid.herokuapp.com',
             '--app', 'dlgr-fake-uid'], stdout=None
        )

    def test_addon(self, app, check_call):
        app.addon('some-fake-addon')
        check_call.assert_called_once_with(
            ["heroku", "addons:create", "some-fake-addon", "--app", app.name],
            stdout=None
        )

    def test_addon_destroy(self, app, check_call):
        app.addon_destroy('some-fake-addon')
        check_call.assert_called_once_with(
            [
                "heroku",
                "addons:destroy", 'some-fake-addon',
                "--app", app.name,
                "--confirm", app.name
            ],
            stdout=None
        )

    def test_buildpack(self, app, check_call):
        app.buildpack('some-fake-buildpack')
        check_call.assert_called_once_with(
            ["heroku", "buildpacks:add", "some-fake-buildpack", "--app", app.name],
            stdout=None
        )

    def test_clock_is_on_checks_psscale(self, app, check_output):
        app.clock_is_on
        check_output.assert_called_once_with(
            ["heroku", "ps:scale", "--app", app.name]
        )

    def test_clock_is_on_returns_true_if_clock_1(self, app, check_output):
        check_output.return_value = b'clock=1:Standard-2X console=0:Standard-1X'
        assert app.clock_is_on is True

    def test_clock_is_on_returns_false_if_clock_0(self, app, check_output):
        check_output.return_value = b'clock=0:Standard-2X console=0:Standard-1X'
        assert app.clock_is_on is False

    def test_clock_is_on_returns_false_if_no_clock(self, app, check_output):
        check_output.return_value = b'console=0:Standard-1X web=1:Standard-2X'
        assert app.clock_is_on is False

    def test_db_uri(self, app, check_output):
        check_output.return_value = b'blahblahpostgres://foobar'
        assert app.db_uri == u'postgres://foobar'

    def test_db_uri_raises_if_no_match(self, app, check_output):
        check_output.return_value = u'└─ as DATABASE on ⬢ dlgr-da089b8f app'.encode('utf8')
        with pytest.raises(NameError) as excinfo:
            app.db_uri
            assert excinfo.match("Could not retrieve the DB URI")

    def test_db_url(self, app, check_output, check_call):
        check_output.return_value = b'some url    '
        assert app.db_url == u'some url'
        check_call.assert_called_once_with(
            ["heroku", "pg:wait", "--app", app.name],
            stdout=None
        )

    def test_backup_capture(self, app, check_call):
        app.backup_capture()
        check_call.assert_called_once_with(
            ["heroku", "pg:backups:capture", "--app", app.name],
            stdout=None, stderr=None
        )

    def test_backup_download(self, app, check_call):
        app.backup_download()
        check_call.assert_called_once_with(
            ["heroku", "pg:backups:download", "--app", app.name],
            stdout=None, stderr=None
        )

    def test_destroy(self, app, check_output):
        check_output.return_value = b'some response message'
        assert app.destroy() == 'some response message'
        check_output.assert_called_once_with(
            ["heroku", "apps:destroy", "--app", app.name, "--confirm", app.name],
        )

    def test_get(self, app, check_output):
        check_output.return_value = b'some value'
        assert app.get('some key') == u'some value'
        check_output.assert_called_once_with(
            ["heroku", "config:get", "some key", "--app", app.name],
        )

    def test_open_logs(self, app, check_call):
        app.open_logs()
        check_call.assert_called_once_with(
            ["heroku", "addons:open", "papertrail", "--app", app.name],
            stdout=None
        )

    def test_pg_pull(self, app, check_call):
        app.pg_pull()
        check_call.assert_called_once_with(
            ["heroku", "pg:pull", "DATABASE_URL", app.name, "--app", app.name],
            stdout=None
        )

    def test_pg_wait(self, app, check_call):
        app.pg_wait()
        check_call.assert_called_once_with(
            ["heroku", "pg:wait", "--app", app.name],
            stdout=None
        )

    def test_redis_url(self, app, check_output):
        check_output.return_value = b'some url'
        assert app.redis_url == u'some url'
        check_output.assert_called_once_with(
            ["heroku", "config:get", "REDIS_URL", "--app", app.name],
        )

    def test_restore(self, app, check_call):
        app.restore('some url')
        check_call.assert_called_once_with(
            [
                "heroku",
                "pg:backups:restore",
                "some url",
                "DATABASE_URL",
                "--app",
                app.name,
                "--confirm",
                app.name,
            ],
            stdout=None
        )

    def test_scale_up_dyno(self, app, check_call):
        app.scale_up_dyno('some process', quantity=1, size='free')
        check_call.assert_called_once_with(
            [
                "heroku",
                "ps:scale",
                "some process=1:free",
                "--app",
                app.name,
            ],
            stdout=None
        )

    def test_scale_down_dyno(self, app, check_call):
        app.scale_down_dyno('some process')
        check_call.assert_called_once_with(
            [
                "heroku",
                "ps:scale",
                "some process=0",
                "--app",
                app.name,
            ],
            stdout=None
        )

    def test_scale_down_dynos_with_clock_off(self, app, check_call, check_output):
        check_output.return_value = b'[string indicating no clock process]'
        app.scale_down_dynos()
        check_call.assert_has_calls([
            mock.call(['heroku', 'ps:scale', 'web=0', '--app', u'dlgr-fake-uid'], stdout=None),
            mock.call(['heroku', 'ps:scale', 'worker=0', '--app', u'dlgr-fake-uid'], stdout=None)
        ])

    def test_scale_down_dynos_with_clock_on(self, app, check_call, check_output):
        check_output.return_value = b'clock=1 <= indicates clock is on'
        app.scale_down_dynos()
        check_call.assert_has_calls([
            mock.call(['heroku', 'ps:scale', 'web=0', '--app', u'dlgr-fake-uid'], stdout=None),
            mock.call(['heroku', 'ps:scale', 'worker=0', '--app', u'dlgr-fake-uid'], stdout=None),
            mock.call(['heroku', 'ps:scale', 'clock=0', '--app', u'dlgr-fake-uid'], stdout=None),
        ])

    def test_set(self, app, check_call):
        app.set('some key', 'some value')
        check_call.assert_called_once_with(
            [
                "heroku",
                "config:set",
                "some key='some value'",
                "--app",
                app.name,
            ],
            stdout=None
        )

    def test_set_multiple(self, app, check_call):
        app.set_multiple(key1='some value', key2='another value')
        check_call.assert_called_once_with(
            [
                "heroku",
                "config:set",
                "key1='some value'",
                "key2='another value'",
                "--app",
                app.name,
            ],
            stdout=None
        )

    def test_set_called_with_nonsensitive_key_uses_stdoutput(self, app, check_call):
        app.set('some_nonsensitive_key', 'some value')
        assert check_call.call_args_list[0][-1]['stdout'] is app.out

    def test_set_called_with_sensitive_key_suppresses_stdoutput(self, app, check_call):
        app.set('aws_secret_access_key', 'some value')
        assert len(check_call.call_args_list) == 0

    @pytest.mark.skipif(not pytest.config.getvalue("heroku"),
                        reason="--heroku was not specified")
    def test_full_monty(self, full_app, temp_repo):
        app = full_app
        assert app.name == u'dlgr-fake-uid'
        assert app.url == u'https://dlgr-fake-uid.herokuapp.com'
        assert app.dashboard_url == u"https://dashboard.heroku.com/apps/dlgr-fake-uid"
        app.bootstrap()
        app.buildpack("https://github.com/stomita/heroku-buildpack-phantomjs")
        app.set('auto_recruit', True)


@pytest.mark.usefixtures('bartlett_dir')
class TestHerokuLocalWrapper(object):

    @pytest.fixture
    def config(self):
        from dallinger.deployment import setup_experiment
        cwd = os.getcwd()
        config = get_config()
        if not config.ready:
            config.load()

        (id, tmp) = setup_experiment(log=mock.Mock(), verbose=True, exp_config={})

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
    def heroku(self, config, env, output, clear_workers):
        from dallinger.heroku.tools import HerokuLocalWrapper
        wrapper = HerokuLocalWrapper(config, output, env=env)
        yield wrapper
        try:
            print("Calling stop() on {}".format(wrapper))
            print(wrapper._record[-1])
            wrapper.stop(signal.SIGKILL)
        except IndexError:
            pass

    def test_start(self, heroku):
        assert heroku.start()
        assert heroku.is_running

    def test_start_raises_without_home_dir_set(self, heroku):
        from dallinger.heroku.tools import HerokuStartupError
        env = heroku.env.copy()
        del env['HOME']
        heroku.env = env
        with pytest.raises(HerokuStartupError) as excinfo:
            heroku.start()
        assert excinfo.match('"HOME" environment not set... aborting.')

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

    def test_as_context_manager(self, config, env, output, clear_workers):
        from dallinger.heroku.tools import HerokuLocalWrapper
        with HerokuLocalWrapper(config, output, env=env) as heroku:
            assert heroku.is_running
        assert not heroku.is_running


class TestHerokuInfo(object):

    @pytest.fixture
    def info(self):

        from dallinger.heroku.tools import HerokuInfo
        yield HerokuInfo(team="fake team")

    def test_login_name(self, info, custom_app_output):
        login_name = info.login_name()
        custom_app_output.assert_has_calls([
            mock.call(['heroku', 'auth:whoami'])
        ])
        assert login_name == 'test@example.com'

    def test_all_apps(self, info, custom_app_output):
        app_info = info.all_apps()
        custom_app_output.assert_has_calls([
            mock.call(['heroku', 'apps', '--json', '--org', 'fake team'])
        ])
        assert app_info == [
            {'created_at': '2018-01-01T12:00Z',
             'name': 'dlgr-my-uid',
             'web_url': 'https://dlgr-my-uid.herokuapp.com'},
            {'created_at': '2018-01-02T00:00Z',
             'name': 'dlgr-another-uid',
             'web_url': 'https://dlgr-another-uid.herokuapp.com'}
        ]

    def test_my_apps(self, info, custom_app_output):
        app_info = info.my_apps()
        custom_app_output.assert_has_calls([
            mock.call(['heroku', 'auth:whoami']),
            mock.call(['heroku', 'apps', '--json', '--org', 'fake team']),
            mock.call(['heroku', 'config:get', 'CREATOR', '--app', 'dlgr-my-uid']),
            mock.call(['heroku', 'config:get', 'DALLINGER_UID', '--app', 'dlgr-my-uid']),
            mock.call(['heroku', 'config:get', 'CREATOR', '--app', 'dlgr-another-uid'])
        ])
        assert app_info == [
            {'created_at': '2018-01-01T12:00Z',
             'dallinger_uid': 'my-uid',
             'name': 'dlgr-my-uid',
             'web_url': 'https://dlgr-my-uid.herokuapp.com'}
        ]
