#!/usr/bin/python
# -*- coding: utf-8 -*-
import mock
import os
import pexpect
import pytest
import six
import subprocess
import sys
import tempfile
from pytest import raises
from six.moves import configparser

from dallinger.deployment import new_webbrowser_profile
from dallinger.command_line import verify_package
from dallinger.config import get_config
from dallinger import recruiters


def found_in(name, path):
    return os.path.exists(os.path.join(path, name))


@pytest.fixture
def output():
    from dallinger.command_line import Output
    return Output(log=mock.Mock(), error=mock.Mock(), blather=mock.Mock())


@pytest.fixture
def browser():
    import webbrowser
    mock_browser = mock.Mock(spec=webbrowser)
    with mock.patch('dallinger.deployment.new_webbrowser_profile') as get_browser:
        get_browser.return_value = mock_browser
        yield mock_browser


@pytest.fixture
def faster(tempdir):
    with mock.patch.multiple('dallinger.deployment',
                             time=mock.DEFAULT,
                             setup_experiment=mock.DEFAULT) as mocks:
        mocks['setup_experiment'].return_value = ('fake-uid', tempdir)

        yield mocks


@pytest.fixture
def launch():
    with mock.patch('dallinger.deployment._handle_launch_data') as hld:
        hld.return_value = {'recruitment_msg': 'fake\nrecruitment\nlist'}
        yield hld


@pytest.fixture
def fake_git():
    with mock.patch('dallinger.deployment.GitClient') as git:
        yield git


@pytest.fixture
def herokuapp():
    # Patch addon since we're using a free app which doesn't support them:
    from dallinger.heroku.tools import HerokuApp
    instance = HerokuApp('fake-uid', output=None, team=None)
    instance.addon = mock.Mock()
    with mock.patch('dallinger.deployment.HerokuApp') as mock_app_class:
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
    with mock.patch('dallinger.deployment.heroku') as heroku_module:
        heroku_module.auth_token.return_value = u'fake token'
        with mock.patch('dallinger.deployment.HerokuApp') as mock_app_class:
            mock_app_class.return_value = instance
            yield instance


class TestIsolatedWebbrowser(object):

    def test_chrome_isolation(self):
        import webbrowser
        with mock.patch('dallinger.deployment.is_command') as is_command:
            is_command.side_effect = lambda s: s == 'google-chrome'
            isolated = new_webbrowser_profile()
        assert isinstance(isolated, webbrowser.Chrome)
        assert isolated.remote_args[:2] == [r'%action', r'%s']
        assert isolated.remote_args[-1].startswith(
            '--user-data-dir="{}'.format(tempfile.gettempdir())
        )

    def test_firefox_isolation(self):
        import webbrowser
        with mock.patch('dallinger.deployment.is_command') as is_command:
            is_command.side_effect = lambda s: s == 'firefox'
            isolated = new_webbrowser_profile()
        assert isinstance(isolated, webbrowser.Mozilla)
        assert isolated.remote_args[0] == '-profile'
        assert isolated.remote_args[1].startswith(tempfile.gettempdir())
        assert isolated.remote_args[2:] == ['-new-instance', '-no-remote', '-url', r'%s']

    def test_fallback_isolation(self):
        import webbrowser
        with mock.patch('dallinger.deployment.is_command') as is_command:
            is_command.return_value = False
            isolated = new_webbrowser_profile()
        assert isolated == webbrowser


@pytest.mark.usefixtures('bartlett_dir', 'active_config')
class TestSetupExperiment(object):

    def test_setup_creates_new_experiment(self):
        from dallinger.deployment import setup_experiment
        # Baseline
        exp_dir = os.getcwd()
        assert found_in('experiment.py', exp_dir)
        assert not found_in('experiment_id.txt', exp_dir)
        assert not found_in('Procfile', exp_dir)
        assert not found_in('launch.py', exp_dir)
        assert not found_in('worker.py', exp_dir)
        assert not found_in('clock.py', exp_dir)

        exp_id, dst = setup_experiment(log=mock.Mock())

        # dst should be a temp dir with a cloned experiment for deployment
        assert(exp_dir != dst)
        assert('/tmp' in dst)

        assert found_in('experiment_id.txt', dst)
        assert found_in('experiment.py', dst)
        assert found_in('models.py', dst)
        assert found_in('Procfile', dst)
        assert found_in('launch.py', dst)
        assert found_in('worker.py', dst)
        assert found_in('clock.py', dst)

        assert found_in(os.path.join("static", "css", "dallinger.css"), dst)
        assert found_in(os.path.join("static", "scripts", "dallinger2.js"), dst)
        assert found_in(os.path.join("static", "scripts", "reconnecting-websocket.js"), dst)
        assert found_in(os.path.join("static", "scripts", "reqwest.min.js"), dst)
        assert found_in(os.path.join("static", "scripts", "spin.min.js"), dst)
        assert found_in(os.path.join("static", "scripts", "store+json2.min.js"), dst)
        assert found_in(os.path.join("static", "robots.txt"), dst)
        assert found_in(os.path.join("templates", "error.html"), dst)
        assert found_in(os.path.join("templates", "error-complete.html"), dst)
        assert found_in(os.path.join("templates", "launch.html"), dst)
        assert found_in(os.path.join("templates", "complete.html"), dst)

    def test_setup_with_custom_dict_config(self):
        from dallinger.deployment import setup_experiment
        config = get_config()
        assert config.get('num_dynos_web') == 1

        exp_id, dst = setup_experiment(log=mock.Mock(), exp_config={'num_dynos_web': 2})
        # Config is updated
        assert config.get('num_dynos_web') == 2

        # Code snapshot is saved
        os.path.exists(os.path.join('snapshots', exp_id + '-code.zip'))

        # There should be a modified configuration in the temp dir
        deploy_config = configparser.SafeConfigParser()
        deploy_config.read(os.path.join(dst, 'config.txt'))
        assert int(deploy_config.get('Parameters', 'num_dynos_web')) == 2

    def test_setup_excludes_sensitive_config(self):
        from dallinger.deployment import setup_experiment
        config = get_config()
        # Auto detected as sensitive
        config.register('a_password', six.text_type)
        # Manually registered as sensitive
        config.register('something_sensitive', six.text_type, sensitive=True)
        # Not sensitive at all
        config.register('something_normal', six.text_type)

        config.extend({'a_password': u'secret thing',
                       'something_sensitive': u'hide this',
                       'something_normal': u'show this'})

        exp_id, dst = setup_experiment(log=mock.Mock())

        # The temp dir should have a config with the sensitive variables missing
        deploy_config = configparser.SafeConfigParser()
        deploy_config.read(os.path.join(dst, 'config.txt'))
        assert(deploy_config.get(
            'Parameters', 'something_normal') == 'show this'
        )
        with raises(configparser.NoOptionError):
            deploy_config.get('Parameters', 'a_password')
        with raises(configparser.NoOptionError):
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


@pytest.mark.usefixtures('in_tempdir')
class TestGitClient(object):

    @pytest.fixture
    def git(self):
        from dallinger.utils import GitClient
        git = GitClient()
        return git

    def test_client(self, git, stub_config):
        stub_config.write()
        config = {'user.name': 'Test User', 'user.email': 'test@example.com'}
        git.init(config=config)
        git.add("--all")
        git.commit("Test Repo")
        assert b"Test Repo" in subprocess.check_output(['git', 'log'])

    def test_includes_details_in_exceptions(self, git):
        with pytest.raises(Exception) as ex_info:
            git.push('foo', 'bar')
        assert ex_info.match('Not a git repository')

    def test_can_use_alternate_output(self, git):
        import tempfile
        git.out = tempfile.NamedTemporaryFile()
        git.encoding = 'utf8'
        git.init()
        git.out.seek(0)
        assert b"git init" in git.out.read()


@pytest.mark.usefixtures('active_config', 'launch', 'fake_git', 'faster')
class TestDeploySandboxSharedSetupNoExternalCalls(object):

    @pytest.fixture
    def dsss(self):
        from dallinger.deployment import deploy_sandbox_shared_setup
        return deploy_sandbox_shared_setup

    def test_result(self, dsss, heroku_mock):
        result = dsss(log=mock.Mock())
        assert result == {
            'app_home': u'fake-url',
            'app_name': u'dlgr-fake-uid',
            'recruitment_msg': 'fake\nrecruitment\nlist'
        }

    def test_bootstraps_heroku(self, dsss, heroku_mock):
        dsss(log=mock.Mock())
        heroku_mock.bootstrap.assert_called_once()

    def test_installs_phantomjs(self, dsss, heroku_mock):
        dsss(log=mock.Mock())
        heroku_mock.buildpack.assert_called_once_with(
            'https://github.com/stomita/heroku-buildpack-phantomjs'
        )

    def test_installs_addons(self, dsss, heroku_mock):
        dsss(log=mock.Mock())
        heroku_mock.addon.assert_has_calls([
            mock.call('heroku-postgresql:standard-0'),
            mock.call('heroku-redis:premium-0'),
            mock.call('papertrail'),
            mock.call('sentry')
        ])

    def test_sets_app_properties(self, dsss, heroku_mock):
        dsss(log=mock.Mock())
        heroku_mock.set.assert_has_calls([
            mock.call('auto_recruit', True),
            mock.call('aws_access_key_id', u'fake aws key'),
            mock.call('aws_region', u'us-east-1'),
            mock.call('aws_secret_access_key', u'fake aws secret'),
            mock.call('smtp_password', u'fake email password'),
            mock.call('smtp_username', u'fake email username'),
            mock.call('whimsical', True),
        ])

    def test_scales_dynos(self, dsss, heroku_mock):
        dsss(log=mock.Mock())
        heroku_mock.scale_up_dyno.assert_has_calls([
            mock.call('web', 1, u'free'),
            mock.call('worker', 1, u'free'),
            mock.call('clock', 1, u'free')
        ])

    def test_calls_launch(self, dsss, heroku_mock, launch):
        log = mock.Mock()
        dsss(log=log)
        launch.assert_called_once_with('fake-url/launch', error=log)


@pytest.mark.skipif(not pytest.config.getvalue("heroku"),
                    reason="--heroku was not specified")
@pytest.mark.usefixtures('bartlett_dir', 'active_config', 'launch', 'herokuapp')
class TestDeploySandboxSharedSetupFullSystem(object):

    @pytest.fixture
    def dsss(self):
        from dallinger.deployment import deploy_sandbox_shared_setup
        return deploy_sandbox_shared_setup

    def test_full_deployment(self, dsss):
        no_clock = {'clock_on': False}  # can't run clock on free dyno
        result = dsss(log=mock.Mock(), exp_config=no_clock)  # can't run clock on free dyno
        app_name = result.get('app_name')
        assert app_name.startswith('dlgr')


@pytest.mark.usefixtures('active_config')
class Test_deploy_in_mode(object):

    @pytest.fixture
    def dim(self):
        from dallinger.deployment import _deploy_in_mode
        return _deploy_in_mode

    @pytest.fixture
    def dsss(self):
        with mock.patch('dallinger.deployment.deploy_sandbox_shared_setup') as mock_dsss:
            yield mock_dsss

    def test_sets_mode_in_config(self, active_config, dim, dsss):
        dim(u'live', 'some app id', verbose=True, log=mock.Mock())
        dsss.assert_called_once()
        assert active_config.get('mode') == u'live'

    def test_sets_logfile_to_dash_for_some_reason(self, active_config, dim, dsss):
        dim(u'live', 'some app id', verbose=True, log=mock.Mock())
        assert active_config.get('logfile') == u'-'


@pytest.mark.usefixtures('bartlett_dir')
class Test_handle_launch_data(object):

    @pytest.fixture
    def handler(self):
        from dallinger.deployment import _handle_launch_data
        return _handle_launch_data

    def test_success(self, handler):
        log = mock.Mock()
        with mock.patch('dallinger.deployment.requests.post') as mock_post:
            result = mock.Mock(
                ok=True,
                json=mock.Mock(return_value={'message': u'msg!'}),
            )
            mock_post.return_value = result
            assert handler('/some-launch-url', error=log) == {'message': u'msg!'}

    def test_failure(self, handler):
        from requests.exceptions import HTTPError
        log = mock.Mock()
        with mock.patch('dallinger.deployment.requests.post') as mock_post:
            mock_post.return_value = mock.Mock(
                ok=False,
                json=mock.Mock(return_value={'message': u'msg!'}),
                raise_for_status=mock.Mock(side_effect=HTTPError)
            )
            with pytest.raises(HTTPError):
                handler('/some-launch-url', error=log, delay=0.05, remaining=5)

        log.assert_has_calls([
            mock.call('Experiment launch failed, retrying in 0.1 seconds ...'),
            mock.call('Experiment launch failed, retrying in 0.2 seconds ...'),
            mock.call('Experiment launch failed, retrying in 0.4 seconds ...'),
            mock.call('Experiment launch failed, retrying in 0.8 seconds ...'),
            mock.call('Experiment launch failed, check web dyno logs for details.'),
            mock.call(u'msg!')
        ])

    def test_non_json_response_error(self, handler):
        log = mock.Mock()
        with mock.patch('dallinger.deployment.requests.post') as mock_post:
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
        from dallinger.deployment import DebugDeployment
        debugger = DebugDeployment(
            output, verbose=True, bot=False, proxy_port=None, exp_config={}
        )
        yield debugger
        if debugger.status_thread:
            debugger.status_thread.join()

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
        with mock.patch('dallinger.deployment.HerokuLocalWrapper') as Wrapper:
            Wrapper.return_value = mock_wrapper
            with pytest.raises(OSError):
                debugger.run()

    def test_new_participant(self, debugger_unpatched):
        from dallinger.config import get_config
        debugger = debugger_unpatched
        get_config().load()
        debugger.new_recruit = mock.Mock(return_value=None)
        assert not debugger.new_recruit.called
        debugger.notify(' New participant requested: http://example.com')
        assert debugger.new_recruit.called

    def test_recruitment_closed(self, debugger_unpatched):
        from dallinger.config import get_config
        get_config().load()
        debugger = debugger_unpatched
        debugger.new_recruit = mock.Mock(return_value=None)
        debugger.heroku = mock.Mock()
        response = mock.Mock(
            json=mock.Mock(return_value={'completed': True})
        )
        with mock.patch('dallinger.deployment.requests') as mock_requests:
            mock_requests.get.return_value = response
            debugger.notify(recruiters.CLOSE_RECRUITMENT_LOG_PREFIX)
            debugger.status_thread.join()

        debugger.out.log.assert_called_with('Experiment completed, all nodes filled.')
        debugger.heroku.stop.assert_called_once()

    def test_new_recruit(self, debugger_unpatched, browser):
        debugger_unpatched.notify(
            " {} some-fake-url".format(recruiters.NEW_RECRUIT_LOG_PREFIX)
        )

        browser.open.assert_called_once_with(
            'some-fake-url', autoraise=True, new=1
        )

    def test_new_recruit_opens_browser_on_proxy_port(
            self, active_config, debugger_unpatched, browser
    ):
        debugger_unpatched.proxy_port = '2222'
        debugger_unpatched.notify(
            " {} some-fake-url:5000".format(recruiters.NEW_RECRUIT_LOG_PREFIX)
        )
        browser.open.assert_called_once_with(
            'some-fake-url:2222', autoraise=True, new=1
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
            encoding='utf-8',
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
        from dallinger.deployment import LoaderDeployment
        from dallinger.heroku.tools import HerokuLocalWrapper
        loader = LoaderDeployment(
            self.exp_id, output, verbose=True, exp_config={}
        )
        loader.notify = mock.Mock(return_value=HerokuLocalWrapper.MONITOR_STOP)

        yield loader

    @pytest.fixture
    def replay_loader(self, db_session, env, output, clear_workers):
        from dallinger.deployment import LoaderDeployment
        loader = LoaderDeployment(
            self.exp_id, output, verbose=True, exp_config={'replay': True}
        )
        loader.keep_running = mock.Mock(return_value=False)

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
