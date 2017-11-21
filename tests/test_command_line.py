#!/usr/bin/python
# -*- coding: utf-8 -*-
import filecmp
import mock
import os
import pytest
import re
import subprocess
import sys
from uuid import UUID
from click.testing import CliRunner
from ConfigParser import NoOptionError, SafeConfigParser

import pexpect
from pytest import raises

import dallinger.command_line
from dallinger.command_line import verify_package
from dallinger.compat import unicode
from dallinger.config import get_config
from dallinger import recruiters
import dallinger.version


def found_in(name, path):
    return os.path.exists(os.path.join(path, name))


@pytest.fixture
def output():

    class Output(object):

        def __init__(self):
            self.log = mock.Mock()
            self.error = mock.Mock()
            self.blather = mock.Mock()

    return Output()


@pytest.fixture
def sleepless():
    # Use this fixture to ignore sleep() calls, for speed.
    with mock.patch('dallinger.command_line.time.sleep'):
        yield


@pytest.fixture
def browser():
    with mock.patch('dallinger.command_line.webbrowser') as mock_browser:
        yield mock_browser


@pytest.fixture
def heroku():
    from dallinger.heroku.tools import HerokuApp
    instance = mock.Mock(spec=HerokuApp)
    with mock.patch('dallinger.command_line.HerokuApp') as mock_app_class:
        mock_app_class.return_value = instance
        yield instance


@pytest.fixture
def data():
    with mock.patch('dallinger.command_line.data') as mock_data:
        mock_data.backup.return_value = 'fake backup url'
        mock_bucket = mock.Mock()
        mock_key = mock.Mock()
        mock_key.generate_url.return_value = 'fake restore url'
        mock_bucket.lookup.return_value = mock_key
        mock_data.user_s3_bucket.return_value = mock_bucket
        yield mock_data


@pytest.mark.usefixtures('bartlett_dir')
class TestVerify(object):

    def test_verify(self):
        subprocess.check_call(["dallinger", "verify"])


class TestCommandLine(object):

    def test_dallinger_no_args(self):
        output = subprocess.check_output(["dallinger"])
        assert("Usage: dallinger [OPTIONS] COMMAND [ARGS]" in output)

    def test_log_empty(self):
        id = "dlgr-3b9c2aeb"
        assert ValueError, subprocess.call(["dallinger", "logs", "--app", id])

    def test_log_no_flag(self):
        assert TypeError, subprocess.call(["dallinger", "logs"])

    def test_deploy_empty(self):
        id = "dlgr-3b9c2aeb"
        assert ValueError, subprocess.call(["dallinger", "deploy", "--app", id])

    def test_sandbox_empty(self):
        id = "dlgr-3b9c2aeb"
        assert ValueError, subprocess.call(["dallinger", "sandbox", "--app", id])

    def test_verify_id_short_fails(self):
        id = "dlgr-3b9c2aeb"
        assert ValueError, dallinger.commandline.verify_id(id)

    def test_empty_id_fails_verification(self):
        assert ValueError, dallinger.commandline.verify_id(None)

    def test_new_uuid(self):
        output = subprocess.check_output(["dallinger", "uuid"])
        assert isinstance(UUID(output.strip(), version=4), UUID)

    def test_dallinger_help(self):
        output = subprocess.check_output(["dallinger", "--help"])
        assert("Commands:" in output)

    def test_setup(self):
        subprocess.check_call(["dallinger", "setup"])
        subprocess.check_call(["dallinger", "setup"])


@pytest.mark.usefixtures('bartlett_dir', 'active_config')
class TestSetupExperiment(object):

    def test_setup_creates_new_experiment(self):
        from dallinger.command_line import setup_experiment
        # Baseline
        exp_dir = os.getcwd()
        assert found_in('experiment.py', exp_dir)
        assert not found_in('dallinger_experiment.py', exp_dir)
        assert not found_in('experiment_id.txt', exp_dir)
        assert not found_in('Procfile', exp_dir)
        assert not found_in('launch.py', exp_dir)
        assert not found_in('worker.py', exp_dir)
        assert not found_in('clock.py', exp_dir)

        exp_id, dst = setup_experiment()

        # dst should be a temp dir with a cloned experiment for deployment
        assert(exp_dir != dst)
        assert('/tmp' in dst)

        assert found_in('experiment_id.txt', dst)
        assert not found_in('experiment.py', dst)
        assert found_in('dallinger_experiment.py', dst)
        assert found_in('models.py', dst)
        assert found_in('Procfile', dst)
        assert found_in('launch.py', dst)
        assert found_in('worker.py', dst)
        assert found_in('clock.py', dst)

        assert filecmp.cmp(
            os.path.join(dst, 'dallinger_experiment.py'),
            os.path.join(exp_dir, 'experiment.py')
        )

        assert found_in(os.path.join("static", "css", "dallinger.css"), dst)
        assert found_in(os.path.join("static", "scripts", "dallinger2.js"), dst)
        assert found_in(os.path.join("static", "scripts", "reconnecting-websocket.js"), dst)
        assert found_in(os.path.join("static", "scripts", "reqwest.min.js"), dst)
        assert found_in(os.path.join("static", "scripts", "spin.min.js"), dst)
        assert found_in(os.path.join("static", "robots.txt"), dst)
        assert found_in(os.path.join("templates", "error.html"), dst)
        assert found_in(os.path.join("templates", "launch.html"), dst)
        assert found_in(os.path.join("templates", "complete.html"), dst)

    def test_setup_with_custom_dict_config(self):
        from dallinger.command_line import setup_experiment
        config = get_config()
        assert config.get('num_dynos_web') == 1

        exp_id, dst = setup_experiment(exp_config={'num_dynos_web': 2})
        # Config is updated
        assert config.get('num_dynos_web') == 2

        # Code snapshot is saved
        os.path.exists(os.path.join('snapshots', exp_id + '-code.zip'))

        # There should be a modified configuration in the temp dir
        deploy_config = SafeConfigParser()
        deploy_config.read(os.path.join(dst, 'config.txt'))
        assert int(deploy_config.get('Parameters', 'num_dynos_web')) == 2

    def test_setup_excludes_sensitive_config(self):
        from dallinger.command_line import setup_experiment
        config = get_config()
        # Auto detected as sensitive
        config.register('a_password', unicode)
        # Manually registered as sensitive
        config.register('something_sensitive', unicode, sensitive=True)
        # Not sensitive at all
        config.register('something_normal', unicode)

        config.extend({'a_password': u'secret thing',
                       'something_sensitive': u'hide this',
                       'something_normal': u'show this'})

        exp_id, dst = setup_experiment()

        # The temp dir should have a config with the sensitive variables missing
        deploy_config = SafeConfigParser()
        deploy_config.read(os.path.join(dst, 'config.txt'))
        assert(deploy_config.get(
            'Parameters', 'something_normal') == u'show this'
        )
        with raises(NoOptionError):
            deploy_config.get('Parameters', 'a_password')
        with raises(NoOptionError):
            deploy_config.get('Parameters', 'something_sensitive')

    def test_payment_type(self):
        config = get_config()
        with raises(TypeError):
            config['base_payment'] = 12

    def test_large_float_payment(self):
        config = get_config()
        config['base_payment'] = 1.2342
        assert verify_package() is False

    def test_negative_payment(self):
        config = get_config()
        config['base_payment'] = -1.99
        assert verify_package() is False


class TestGitClient(object):

    def test_client(self, in_tempdir, stub_config):
        from dallinger.utils import GitClient
        stub_config.write()
        config = {'user.name': 'Test User', 'user.email': 'test@example.com'}
        git = GitClient(output=None)
        git.init(config=config)
        git.add("--all")
        git.commit("Test Repo")
        assert "Test Repo" in subprocess.check_output(['git', 'log'])


@pytest.fixture
def faster(tempdir):
    with mock.patch.multiple('dallinger.command_line',
                             time=mock.DEFAULT,
                             setup_experiment=mock.DEFAULT) as mocks:
        mocks['setup_experiment'].return_value = ('fake-uid', tempdir)

        yield mocks


@pytest.fixture
def launch():
    with mock.patch('dallinger.command_line._handle_launch_data') as hld:
        hld.return_value = {'recruitment_msg': 'fake\nrecruitment\nlist'}
        yield hld


@pytest.fixture
def fake_git():
    with mock.patch('dallinger.command_line.GitClient') as git:
        yield git


@pytest.fixture
def herokuapp():
    # Patch addon since we're using a free app which doesn't support them:
    from dallinger.heroku.tools import HerokuApp
    instance = HerokuApp('fake-uid', output=None, team=None)
    instance.addon = mock.Mock()
    with mock.patch('dallinger.command_line.HerokuApp') as mock_app_class:
        mock_app_class.return_value = instance
        yield instance
        instance.destroy()


@pytest.fixture
def heroku_mock():
    # Patch addon since we're using a free app which doesn't support them:
    from dallinger.heroku.tools import HerokuApp
    instance = mock.Mock(spec=HerokuApp)
    instance.redis_url = '\n'
    instance.name = u'dlgr-fake-uid'
    instance.url = u'fake-url'
    instance.db_url = u'fake-url'
    with mock.patch('dallinger.command_line.heroku') as heroku_module:
        heroku_module.auth_token.return_value = u'fake token'
        with mock.patch('dallinger.command_line.HerokuApp') as mock_app_class:
            mock_app_class.return_value = instance
            yield instance


@pytest.mark.usefixtures('active_config', 'launch', 'fake_git', 'faster')
class TestDeploySandboxSharedSetupNoExternalCalls(object):

    @pytest.fixture
    def dsss(self):
        from dallinger.command_line import deploy_sandbox_shared_setup
        return deploy_sandbox_shared_setup

    def test_result(self, dsss, heroku_mock):
        result = dsss()
        assert result == {
            'app_home': u'fake-url',
            'app_name': u'dlgr-fake-uid',
            'recruitment_msg': 'fake\nrecruitment\nlist'
        }

    def test_bootstraps_heroku(self, dsss, heroku_mock):
        dsss()
        heroku_mock.bootstrap.assert_called_once()

    def test_installs_phantomjs(self, dsss, heroku_mock):
        dsss()
        heroku_mock.buildpack.assert_called_once_with(
            'https://github.com/stomita/heroku-buildpack-phantomjs'
        )

    def test_installs_addons(self, dsss, heroku_mock):
        dsss()
        heroku_mock.addon.assert_has_calls([
            mock.call('heroku-postgresql:standard-0'),
            mock.call('heroku-redis:premium-0'),
            mock.call('papertrail'),
            mock.call('sentry')
        ])

    def test_sets_app_properties(self, dsss, heroku_mock):
        dsss()
        heroku_mock.set.assert_has_calls([
            mock.call('auto_recruit', True),
            mock.call('aws_access_key_id', u'fake aws key'),
            mock.call('aws_region', u'us-east-1'),
            mock.call('aws_secret_access_key', u'fake aws secret'),
            mock.call('dallinger_email_key', u'fake password'),
            mock.call('dallinger_email_username', u'test@example.com'),
            mock.call('whimsical', True),
        ])

    def test_scales_dynos(self, dsss, heroku_mock):
        dsss()
        heroku_mock.scale_up_dyno.assert_has_calls([
            mock.call('web', 1, u'free'),
            mock.call('worker', 1, u'free'),
            mock.call('clock', 1, u'free')
        ])


@pytest.mark.skipif(not pytest.config.getvalue("heroku"),
                    reason="--heroku was not specified")
@pytest.mark.usefixtures('bartlett_dir', 'active_config', 'launch', 'herokuapp')
class TestDeploySandboxSharedSetupFullSystem(object):

    @pytest.fixture
    def dsss(self):
        from dallinger.command_line import deploy_sandbox_shared_setup
        return deploy_sandbox_shared_setup

    def test_full_deployment(self, dsss):
        no_clock = {'clock_on': False}  # can't run clock on free dyno
        result = dsss(exp_config=no_clock)  # can't run clock on free dyno
        app_name = result.get('app_name')
        assert app_name.startswith('dlgr')


@pytest.mark.usefixtures('bartlett_dir')
class Test_handle_launch_data(object):

    @pytest.fixture
    def handler(self):
        from dallinger.command_line import _handle_launch_data
        return _handle_launch_data

    def test_success(self, handler):
        log = mock.Mock()
        with mock.patch('dallinger.command_line.requests.post') as mock_post:
            result = mock.Mock(
                ok=True,
                json=mock.Mock(return_value={'message': u'msg!'}),
            )
            mock_post.return_value = result
            assert handler('/some-launch-url', error=log) == {'message': u'msg!'}

    def test_failure(self, handler):
        from requests.exceptions import HTTPError
        log = mock.Mock()
        with mock.patch('dallinger.command_line.requests.post') as mock_post:
            mock_post.return_value = mock.Mock(
                ok=False,
                json=mock.Mock(return_value={'message': u'msg!'}),
                raise_for_status=mock.Mock(side_effect=HTTPError)
            )
            with pytest.raises(HTTPError):
                handler('/some-launch-url', error=log)

        log.assert_has_calls([
            mock.call('Experiment launch failed, check web dyno logs for details.'),
            mock.call(u'msg!')
        ])

    def test_non_json_response_error(self, handler):
        log = mock.Mock()
        with mock.patch('dallinger.command_line.requests.post') as mock_post:
            mock_post.return_value = mock.Mock(
                json=mock.Mock(side_effect=ValueError),
                text='Big, unexpected problem.'
            )
            with pytest.raises(ValueError):
                handler('/some-launch-url', error=log)

        log.assert_called_once_with(
            'Error parsing response from /launch, check web dyno logs for details: '
            'Big, unexpected problem.'
        )


@pytest.mark.usefixtures('bartlett_dir', 'clear_workers', 'env')
class TestDebugServer(object):

    @pytest.fixture
    def debugger_unpatched(self, output):
        from dallinger.command_line import DebugSessionRunner
        debugger = DebugSessionRunner(
            output, verbose=True, bot=False, proxy_port=None, exp_config={}
        )
        return debugger

    @pytest.fixture
    def debugger(self, debugger_unpatched):
        from dallinger.heroku.tools import HerokuLocalWrapper
        debugger = debugger_unpatched
        debugger.notify = mock.Mock(return_value=HerokuLocalWrapper.MONITOR_STOP)
        return debugger

    def test_startup(self, debugger):
        debugger.run()
        "Server is running" in str(debugger.out.log.call_args_list[0])

    def test_raises_if_heroku_wont_start(self, debugger):
        mock_wrapper = mock.Mock(
            __enter__=mock.Mock(side_effect=OSError),
            __exit__=mock.Mock(return_value=False)
        )
        with mock.patch('dallinger.command_line.HerokuLocalWrapper') as Wrapper:
            Wrapper.return_value = mock_wrapper
            with pytest.raises(OSError):
                debugger.run()

    def test_recruitment_closed(self, debugger_unpatched):
        from dallinger.heroku.tools import HerokuLocalWrapper
        debugger = debugger_unpatched
        debugger.new_recruit = mock.Mock(return_value=None)
        response = mock.Mock(
            json=mock.Mock(return_value={'completed': True})
        )
        with mock.patch('dallinger.command_line.requests') as mock_requests:
            mock_requests.get.return_value = response
            response = debugger.notify(recruiters.CLOSE_RECRUITMENT_LOG_PREFIX)

        assert response == HerokuLocalWrapper.MONITOR_STOP
        debugger.out.log.assert_called_with('Experiment completed, all nodes filled.')

    def test_new_recruit(self, debugger_unpatched, browser):
        debugger_unpatched.notify(
            " {} some-fake-url".format(recruiters.NEW_RECRUIT_LOG_PREFIX)
        )

        browser.open.assert_called_once_with(
            'some-fake-url', autoraise=True, new=1
        )

    def test_new_recruit_not_triggered_if_quoted(self, debugger_unpatched, browser):
        debugger_unpatched.notify(
            ' "{}" some-fake-url'.format(recruiters.NEW_RECRUIT_LOG_PREFIX)
        )

        browser.open.assert_not_called()

    @pytest.mark.skipif(not pytest.config.getvalue("runbot"),
                        reason="--runbot was specified")
    def test_debug_bots(self, env):
        # Make sure debug server runs to completion with bots
        p = pexpect.spawn(
            'dallinger',
            ['debug', '--verbose', '--bot'],
            env=env,
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact('Server is running', timeout=300)
            p.expect_exact('Recruitment is complete', timeout=600)
            p.expect_exact('Experiment completed', timeout=60)
            p.expect_exact('Local Heroku process terminated', timeout=10)
        finally:
            try:
                p.sendcontrol('c')
                p.read()
            except IOError:
                pass


@pytest.mark.usefixtures('bartlett_dir', 'clear_workers', 'env')
class TestLoad(object):

    exp_id = "some_experiment_id"

    @pytest.fixture
    def export(self):
        # Data export created, then removed after test[s]
        from dallinger.data import export
        path = export(self.exp_id, local=True)
        yield path
        os.remove(path)

    @pytest.fixture
    def loader(self, db_session, output, clear_workers):
        from dallinger.command_line import LoadSessionRunner
        from dallinger.heroku.tools import HerokuLocalWrapper
        loader = LoadSessionRunner(self.exp_id, output, verbose=True,
                                   exp_config={})
        loader.notify = mock.Mock(return_value=HerokuLocalWrapper.MONITOR_STOP)

        yield loader

    @pytest.fixture
    def replay_loader(self, db_session, env, output, clear_workers):
        from dallinger.command_line import LoadSessionRunner
        loader = LoadSessionRunner(self.exp_id, output, verbose=True,
                                   exp_config={'replay': True})
        loader.keep_running = mock.Mock(return_value=False)\


        def launch_and_finish(self):
            from dallinger.heroku.tools import HerokuLocalWrapper
            loader.out.log("Launching replay browser...")
            return HerokuLocalWrapper.MONITOR_STOP

        loader.start_replay = mock.Mock(
            return_value=None,
            side_effect=launch_and_finish
        )
        yield loader

    def test_load_runs(self, loader, export):
        loader.keep_running = mock.Mock(return_value=False)
        loader.run()

        loader.out.log.assert_has_calls([
            mock.call('Starting up the server...'),
            mock.call('Ingesting dataset from some_experiment_id-data.zip...'),
            mock.call('Server is running on http://0.0.0.0:5000. Press Ctrl+C to exit.'),
            mock.call('Terminating dataset load for experiment some_experiment_id'),
            mock.call('Cleaning up local Heroku process...'),
            mock.call('Local Heroku process terminated.')
        ])

    def test_load_raises_on_nonexistent_id(self, loader):
        loader.app_id = 'nonsense'
        loader.keep_running = mock.Mock(return_value=False)
        with pytest.raises(IOError):
            loader.run()

    def test_load_with_replay(self, replay_loader, export):
        replay_loader.run()

        replay_loader.out.log.assert_has_calls([
            mock.call('Starting up the server...'),
            mock.call('Ingesting dataset from some_experiment_id-data.zip...'),
            mock.call('Server is running on http://0.0.0.0:5000. Press Ctrl+C to exit.'),
            mock.call('Launching the experiment...'),
            mock.call('Launching replay browser...'),
            mock.call('Terminating dataset load for experiment some_experiment_id'),
            mock.call('Cleaning up local Heroku process...'),
            mock.call('Local Heroku process terminated.')
        ])


class TestOutput(object):

    @pytest.fixture
    def output(self):
        from dallinger.command_line import Output
        return Output()

    def test_outs(self, output):
        output.log('logging')
        output.error('an error')
        output.blather('blah blah blah')


class TestHeader(object):
    def test_header_contains_version_number(self):
        # Make sure header contains the version number.
        assert dallinger.version.__version__ in dallinger.command_line.header


class TestSandboxAndDeploy(object):

    @pytest.fixture
    def sandbox(self):
        from dallinger.command_line import sandbox
        return sandbox

    @pytest.fixture
    def deploy(self):
        from dallinger.command_line import deploy
        return deploy

    @pytest.fixture
    def dsss(self):
        with mock.patch('dallinger.command_line.deploy_sandbox_shared_setup') as mock_dsss:
            yield mock_dsss

    def test_sandbox_with_app_id(self, sandbox, dsss):
        CliRunner().invoke(
            sandbox,
            [
                '--verbose',
                '--app', 'some app id',
            ]
        )
        dsss.assert_called_once_with(app=u'some app id', verbose=True)
        assert get_config().get('mode') == u'sandbox'

    def test_sandbox_with_no_app_id(self, sandbox, dsss):
        CliRunner().invoke(
            sandbox,
            [
                '--verbose',
            ]
        )
        dsss.assert_called_once_with(app=None, verbose=True)
        assert get_config().get('mode') == u'sandbox'

    def test_sandbox_with_invalid_app_id(self, sandbox, dsss):
        result = CliRunner().invoke(
            sandbox,
            [
                '--verbose',
                '--app', 'dlgr-some app id',
            ]
        )
        dsss.assert_not_called()
        assert result.exit_code == -1
        assert 'The --app flag requires the full UUID' in result.exception.message

    def test_deploy_with_app_id(self, deploy, dsss):
        CliRunner().invoke(
            deploy,
            [
                '--verbose',
                '--app', 'some app id',
            ]
        )
        dsss.assert_called_once_with(app=u'some app id', verbose=True)
        assert get_config().get('mode') == u'live'


class TestSummary(object):

    @pytest.fixture
    def summary(self):
        from dallinger.command_line import summary
        return summary

    @pytest.fixture
    def patched_summary_route(self):
        response = mock.Mock()
        response.json.return_value = {
            u'completed': True,
            u'nodes_remaining': 0,
            u'required_nodes': 0,
            u'status': u'success',
            u'summary': [[u'approved', 1], [u'submitted', 1]],
            u'unfilled_networks': 0
        }
        with mock.patch('dallinger.command_line.requests') as req:
            req.get.return_value = response
            yield req

    def test_summary(self, summary, patched_summary_route):
        result = CliRunner().invoke(
            summary,
            [
                '--app', 'some app id',
            ]
        )
        assert "Yield: 50.00%" in result.output


@pytest.mark.usefixtures('bartlett_dir')
class TestBot(object):

    @pytest.fixture
    def bot_command(self):
        from dallinger.command_line import bot
        return bot

    @pytest.fixture
    def mock_bot(self):
        bot = mock.Mock()
        with mock.patch('dallinger.command_line.bot_factory') as bot_factory:
            bot_factory.return_value = bot
            yield bot

    def test_bot_factory(self):
        from dallinger.command_line import bot_factory
        from dallinger.command_line import setup_experiment
        from dallinger.bots import BotBase
        setup_experiment()
        bot = bot_factory('some url')
        assert isinstance(bot, BotBase)

    def test_bot_no_debug_url(self, bot_command, mock_bot):
        CliRunner().invoke(
            bot_command,
            [
                '--app', 'some app id',
            ]
        )

        assert mock_bot.run_experiment.called

    def test_bot_with_debug_url(self, bot_command, mock_bot):
        CliRunner().invoke(
            bot_command,
            [
                '--app', 'some app id',
                '--debug', 'some url'
            ]
        )

        assert mock_bot.run_experiment.called


class TestQualify(object):

    @pytest.fixture
    def qualify(self):
        from dallinger.command_line import qualify
        return qualify

    @pytest.fixture
    def mturk(self):
        with mock.patch('dallinger.command_line.MTurkService') as mock_mturk:
            mock_results = [{'id': 'some qid', 'score': 1}]
            mock_instance = mock.Mock()
            mock_instance.get_workers_with_qualification.return_value = mock_results
            mock_mturk.return_value = mock_instance

            yield mock_instance

    def test_qualify_single_worker(self, qualify, mturk):
        qual_value = 1
        result = CliRunner().invoke(
            qualify,
            [
                '--qualification', 'some qid',
                '--value', qual_value,
                'some worker id',
            ]
        )
        assert result.exit_code == 0
        mturk.set_qualification_score.assert_called_once_with(
            'some qid', 'some worker id', qual_value, notify=False
        )
        mturk.get_workers_with_qualification.assert_called_once_with('some qid')

    def test_uses_mturk_sandbox_if_specified(self, qualify):
        qual_value = 1
        with mock.patch('dallinger.command_line.MTurkService') as mock_mturk:
            mock_mturk.return_value = mock.Mock()
            CliRunner().invoke(
                qualify,
                [
                    '--sandbox',
                    '--qualification', 'some qid',
                    '--value', qual_value,
                    'some worker id',
                ]
            )
            assert 'sandbox=True' in str(mock_mturk.call_args_list[0])

    def test_raises_with_no_worker(self, qualify, mturk):
        qual_value = 1
        result = CliRunner().invoke(
            qualify,
            [
                '--qualification', 'some qid',
                '--value', qual_value,
            ]
        )
        assert result.exit_code != 0
        assert 'at least one worker ID' in result.output

    def test_can_elect_to_notify_worker(self, qualify, mturk):
        qual_value = 1
        result = CliRunner().invoke(
            qualify,
            [
                '--qualification', 'some qid',
                '--value', qual_value,
                '--notify',
                'some worker id',
            ]
        )
        assert result.exit_code == 0
        mturk.set_qualification_score.assert_called_once_with(
            'some qid', 'some worker id', qual_value, notify=True
        )

    def test_qualify_multiple_workers(self, qualify, mturk):
        qual_value = 1
        result = CliRunner().invoke(
            qualify,
            [
                '--qualification', 'some qid',
                '--value', qual_value,
                'worker1', 'worker2',
            ]
        )
        assert result.exit_code == 0
        mturk.set_qualification_score.assert_has_calls([
            mock.call(u'some qid', u'worker1', 1, notify=False),
            mock.call(u'some qid', u'worker2', 1, notify=False)
        ])

    def test_use_qualification_name(self, qualify, mturk):
        qual_value = 1
        mturk.get_qualification_type_by_name.return_value = {'id': 'some qid'}
        result = CliRunner().invoke(
            qualify,
            [
                '--qualification', 'some qual name',
                '--value', qual_value,
                '--by_name',
                'some worker id',
            ]
        )
        assert result.exit_code == 0
        mturk.set_qualification_score.assert_called_once_with(
            'some qid', 'some worker id', qual_value, notify=False
        )
        mturk.get_workers_with_qualification.assert_called_once_with('some qid')

    def test_use_qualification_name_with_bad_name(self, qualify, mturk):
        qual_value = 1
        mturk.get_qualification_type_by_name.return_value = None
        result = CliRunner().invoke(
            qualify,
            [
                '--qualification', 'some qual name',
                '--value', qual_value,
                '--by_name',
                'some worker id',
            ]
        )
        assert result.exit_code == 2
        assert 'No qualification with name "some qual name" exists.' in result.output


class TestHibernate(object):

    @pytest.fixture
    def hibernate(self, sleepless):
        from dallinger.command_line import hibernate
        return hibernate

    def test_creates_backup(self, hibernate, heroku, data):
        CliRunner().invoke(
            hibernate,
            ['--app', 'some-app-uid', ]
        )
        data.backup.assert_called_once_with('some-app-uid')

    def test_scales_down_dynos(self, hibernate, heroku, data):
        CliRunner().invoke(
            hibernate,
            ['--app', 'some-app-uid', ]
        )
        heroku.scale_down_dyno.assert_has_calls([
            mock.call('web'),
            mock.call('worker'),
            mock.call('clock')
        ])

    def test_kills_addons(self, hibernate, heroku, data):
        CliRunner().invoke(
            hibernate,
            ['--app', 'some-app-uid', ]
        )
        heroku.addon_destroy.assert_has_calls([
            mock.call('heroku-postgresql'),
            mock.call('heroku-redis')
        ])


@pytest.mark.usefixtures('active_config')
class TestAwaken(object):

    @pytest.fixture
    def awaken(self, sleepless):
        from dallinger.command_line import awaken
        return awaken

    def test_creates_database_of_configured_size(self, awaken, heroku, data, active_config):
        CliRunner().invoke(
            awaken,
            ['--app', 'some-app-uid', ]
        )
        size = active_config.get('database_size')
        expected = mock.call('heroku-postgresql:{}'.format(size))
        assert expected == heroku.addon.call_args_list[0]

    def test_adds_redis(self, awaken, heroku, data):
        CliRunner().invoke(
            awaken,
            ['--app', 'some-app-uid', ]
        )
        assert mock.call('heroku-redis:premium-0') == heroku.addon.call_args_list[1]

    def test_restores_database_from_backup(self, awaken, heroku, data):
        CliRunner().invoke(
            awaken,
            ['--app', 'some-app-uid', ]
        )
        heroku.restore.assert_called_once_with('fake restore url')

    def test_scales_up_dynos(self, awaken, heroku, data, active_config):
        CliRunner().invoke(
            awaken,
            ['--app', 'some-app-uid', ]
        )
        web_count = active_config.get('num_dynos_web')
        worker_count = active_config.get('num_dynos_worker')
        size = active_config.get('dyno_type')
        heroku.scale_up_dyno.assert_has_calls([
            mock.call('web', web_count, size),
            mock.call('worker', worker_count, size),
            mock.call('clock', 1, size)
        ])


class TestDestroy(object):

    @pytest.fixture
    def destroy(self):
        from dallinger.command_line import destroy
        return destroy

    def test_calls_destroy(self, destroy, heroku):
        CliRunner().invoke(
            destroy,
            ['--app', 'some-app-uid', '--yes']
        )
        heroku.destroy.assert_called_once()

    def test_requires_confirmation(self, destroy, heroku):
        CliRunner().invoke(
            destroy,
            ['--app', 'some-app-uid']
        )
        heroku.destroy.assert_not_called()


class TestLogs(object):

    @pytest.fixture
    def logs(self):
        from dallinger.command_line import logs
        return logs

    def test_opens_logs(self, logs, heroku):
        CliRunner().invoke(
            logs,
            ['--app', 'some-app-uid', ]
        )
        heroku.open_logs.assert_called_once()


class TestMonitor(object):

    def _twice(self):
        count = [2]

        def countdown():
            if count[0]:
                count[0] -= 1
                return True
            return False

        return countdown

    @pytest.fixture
    def command_line_check_call(self):
        with mock.patch('dallinger.command_line.check_call') as call:
            yield call

    @pytest.fixture
    def summary(self):
        with mock.patch('dallinger.command_line.get_summary') as sm:
            sm.return_value = 'fake summary'
            yield sm

    @pytest.fixture
    def two_summary_checks(self):
        countdown = self._twice()
        counter_factory = mock.Mock(return_value=countdown)
        with mock.patch('dallinger.command_line._keep_running',
                        new_callable=counter_factory):
            yield

    @pytest.fixture
    def monitor(self, sleepless, summary, two_summary_checks):
        from dallinger.command_line import monitor
        return monitor

    def test_opens_browsers(self, monitor, heroku, browser, command_line_check_call):
        heroku.dashboard_url = 'fake-dashboard-url'
        CliRunner().invoke(
            monitor,
            ['--app', 'some-app-uid', ]
        )
        browser.open.assert_has_calls([
            mock.call('fake-dashboard-url'),
            mock.call('https://requester.mturk.com/mturk/manageHITs')
        ])

    def test_calls_open_with_db_uri(self, monitor, heroku, browser, command_line_check_call):
        heroku.db_uri = 'fake-db-uri'
        CliRunner().invoke(
            monitor,
            ['--app', 'some-app-uid', ]
        )
        command_line_check_call.assert_called_once_with(['open', 'fake-db-uri'])

    def test_shows_summary_in_output(self, monitor, heroku, browser, command_line_check_call):
        heroku.db_uri = 'fake-db-uri'
        result = CliRunner().invoke(
            monitor,
            ['--app', 'some-app-uid', ]
        )

        assert len(re.findall('fake summary', result.output)) == 2

    def test_raises_on_null_app_id(self, monitor, heroku, browser, command_line_check_call):
        heroku.db_uri = 'fake-db-uri'
        result = CliRunner().invoke(
            monitor,
            ['--app', None, ]
        )
        assert result.exception.message == 'Select an experiment using the --app flag.'
