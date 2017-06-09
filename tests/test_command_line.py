#!/usr/bin/python
# -*- coding: utf-8 -*-
import filecmp
import os
import pytest
import shutil
import subprocess
import sys
import tempfile
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
def env():
    # Heroku requires a home directory to start up
    # We create a fake one using tempfile and set it into the
    # environment to handle sandboxes on CI servers

    fake_home = tempfile.mkdtemp()
    environ = os.environ.copy()
    environ.update({'HOME': fake_home})
    yield environ

    shutil.rmtree(fake_home, ignore_errors=True)


class TestCommandLine(object):

    def test_dallinger_help(self):
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

    def test_setup_copies_dataset_archive(self, root):
        from dallinger.command_line import setup_experiment
        zip_path = os.path.join(
            root,
            'tests',
            'datasets',
            'test_export.zip'
        )
        exp_id, dst = setup_experiment(dataset=zip_path)
        assert 'test_export.zip' in os.listdir(dst)

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
class TestDebugServer(object):

    def test_startup(self, env):
        # Make sure debug server starts without error
        p = pexpect.spawn(
            'dallinger',
            ['debug', '--verbose'],
            env=env,
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact('Server is running', timeout=120)
        finally:
            p.sendcontrol('c')
            p.read()

    def test_launch_failure(self, env):
        # Make sure debug server starts without error
        env['recruiter'] = u'bogus'
        p = pexpect.spawn(
            'dallinger',
            ['debug', '--verbose'],
            env=env,
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact('Launching the experiment...', timeout=120)
            p.expect_exact('Experiment launch failed, check web dyno logs for details.',
                           timeout=60)
            p.expect_exact('Failed to open recruitment, check experiment server log for details.',
                           timeout=30)
        finally:
            try:
                p.sendcontrol('c')
            except IOError:
                pass
            p.read()

    def test_warning_if_no_heroku_present(self, env):
        # Remove the path item that has heroku in it
        path_items = env['PATH'].split(':')
        path_items = [
            item for item in path_items
            if not os.path.exists(os.path.join(item, 'heroku'))
        ]
        env.update({
            'PATH': ':'.join(path_items)
        })
        p = pexpect.spawn(
            'dallinger',
            ['debug', '--verbose'],
            env=env,
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact("Couldn't start Heroku for local debugging", timeout=120)
        finally:
            p.sendcontrol('c')
            p.read()

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
            p.sendcontrol('c')
            p.read()


@pytest.mark.usefixtures('bartlett_dir')
class TestLoad(object):

    def test_load_runs(self, env, root):
        zip_path = os.path.join(
            root,
            'tests',
            'datasets',
            'test_export.zip'
        )
        p = pexpect.spawn(
            'dallinger',
            ['load', '--verbose', zip_path],
            env=env,
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact('Ingesting dataset', timeout=300)
            p.expect_exact('Server is running', timeout=300)
        finally:
            p.sendcontrol('c')
            p.expect_exact('Terminating dataset load', timeout=300)
            p.read()


class TestHeader(object):
    def test_header_contains_version_number(self):
        # Make sure header contains the version number.
        assert dallinger.version.__version__ in dallinger.command_line.header
