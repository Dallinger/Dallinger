#!/usr/bin/python
# -*- coding: utf-8 -*-
import filecmp
import mock
import os
import pytest
import subprocess
import sys
from uuid import UUID
from ConfigParser import NoOptionError, SafeConfigParser

import pexpect
from pytest import raises

import dallinger.command_line
from dallinger.command_line import verify_package
from dallinger.compat import unicode
from dallinger.config import get_config
import dallinger.version


def found_in(name, path):
    return os.path.exists(os.path.join(path, name))


@pytest.fixture
def env_with_home(env):
    original_env = os.environ.copy()
    if 'HOME' not in original_env:
        os.environ.update(env)
    yield
    os.environ = original_env


@pytest.fixture
def output():

    class Output(object):

        def __init__(self):
            self.log = mock.Mock()
            self.error = mock.Mock()
            self.blather = mock.Mock()

    return Output()


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


@pytest.mark.usefixtures('bartlett_dir')
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
        assert found_in(os.path.join("static", "scripts", "dallinger.js"), dst)
        assert found_in(os.path.join("static", "scripts", "reqwest.min.js"), dst)
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


@pytest.mark.usefixtures('bartlett_dir')
class TestDebugServer(object):

    @pytest.fixture
    def debugger_unpatched(self, env_with_home, output):
        from dallinger.command_line import DebugSessionRunner
        debugger = DebugSessionRunner(output, verbose=True, bot=False, exp_config={})
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
        from dallinger.config import get_config
        debugger = debugger_unpatched
        get_config().load()
        debugger.new_recruit = mock.Mock(return_value=None)
        response = mock.Mock(
            json=mock.Mock(return_value={'completed': True})
        )
        with mock.patch('dallinger.command_line.requests') as mock_requests:
            mock_requests.get.return_value = response
            response = debugger.notify("Close recruitment.")

        assert response == HerokuLocalWrapper.MONITOR_STOP
        debugger.out.log.assert_called_with('Experiment completed, all nodes filled.')

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


@pytest.mark.usefixtures('bartlett_dir')
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
    def loader(self, db_session, env_with_home, output):
        from dallinger.command_line import LoadSessionRunner
        from dallinger.heroku.tools import HerokuLocalWrapper
        loader = LoadSessionRunner(self.exp_id, output, verbose=True, exp_config={})
        loader.notify = mock.Mock(return_value=HerokuLocalWrapper.MONITOR_STOP)

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
