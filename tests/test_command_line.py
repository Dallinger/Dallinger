#!/usr/bin/python
# -*- coding: utf-8 -*-
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile
from ConfigParser import NoOptionError, SafeConfigParser

import pexpect
from pytest import raises

import dallinger.command_line
from dallinger.compat import unicode
from dallinger.config import LOCAL_CONFIG, get_config
import dallinger.version


class TestCommandLine(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        os.chdir("demos")

    def teardown(self):
        os.chdir("..")

    def test_dallinger_help(self):
        output = subprocess.check_output(["dallinger"])
        assert("Usage: dallinger [OPTIONS] COMMAND [ARGS]" in output)


class TestSetupExperiment(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        self.orig_dir = os.getcwd()
        os.chdir("demos/bartlett1932")
        config = get_config()
        config.load_from_file(LOCAL_CONFIG)

    def teardown(self):
        os.chdir(self.orig_dir)

    def test_setup_creates_new_experiment(self):
        from dallinger.command_line import setup_experiment
        # Baseline
        exp_dir = os.getcwd()
        assert(os.path.exists('experiment.py') is True)
        assert(os.path.exists('dallinger_experiment.py') is False)
        assert(os.path.exists('experiment_id.txt') is False)
        assert(os.path.exists('Procfile') is False)
        assert(os.path.exists('launch.py') is False)
        assert(os.path.exists('worker.py') is False)
        assert(os.path.exists('clock.py') is False)

        exp_id, dst = setup_experiment()

        # dst should be a temp dir with a cloned experiment for deployment
        assert(exp_dir != dst)
        assert('/tmp' in dst)
        os.chdir(dst)
        assert(os.path.exists('experiment_id.txt') is True)
        assert(os.path.exists('experiment.py') is False)
        assert(os.path.exists('dallinger_experiment.py') is True)
        assert(os.path.exists('models.py') is True)
        assert(filecmp.cmp('dallinger_experiment.py',
                           os.path.join(exp_dir, 'experiment.py')) is True)

        assert(os.path.exists('Procfile') is True)
        assert(os.path.exists('launch.py') is True)
        assert(os.path.exists('worker.py') is True)
        assert(os.path.exists('clock.py') is True)
        assert(os.path.exists(os.path.join("static", "css", "dallinger.css")) is True)
        assert(os.path.exists(os.path.join("static", "scripts", "dallinger.js")) is True)
        assert(os.path.exists(os.path.join("static", "scripts", "reqwest.min.js")) is True)
        assert(os.path.exists(os.path.join("static", "robots.txt")) is True)
        assert(os.path.exists(os.path.join("templates", "error.html")) is True)
        assert(os.path.exists(os.path.join("templates", "launch.html")) is True)
        assert(os.path.exists(os.path.join("templates", "complete.html")) is True)

    def test_setup_with_custom_dict_config(self):
        from dallinger.command_line import setup_experiment
        config = get_config()
        assert(config.get('num_dynos_web') == 1)

        exp_id, dst = setup_experiment(exp_config={'num_dynos_web': 2})
        # Config is updated
        assert(config.get('num_dynos_web') == 2)

        # Code snapshot is saved
        os.path.exists(os.path.join('snapshots', exp_id + '-code.zip'))

        # There should be a modified configuration in the temp dir
        os.chdir(dst)
        deploy_config = SafeConfigParser()
        deploy_config.read('config.txt')
        assert(int(deploy_config.get('Parameters', 'num_dynos_web')) == 2)

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
        os.chdir(dst)
        deploy_config = SafeConfigParser()
        deploy_config.read('config.txt')
        assert(deploy_config.get(
            'Parameters', 'something_normal') == u'show this'
        )
        with raises(NoOptionError):
            deploy_config.get('Parameters', 'a_password')
        with raises(NoOptionError):
            deploy_config.get('Parameters', 'something_sensitive')


class TestDebugServer(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        self.orig_dir = os.getcwd()
        os.chdir("demos/bartlett1932")
        # Heroku requires a home directory to start up
        # We create a fake one using tempfile and set it into the
        # environment to handle sandboxes on CI servers
        self.fake_home = tempfile.mkdtemp()

        self.environ = os.environ.copy()
        self.environ.update({'HOME': self.fake_home})

    def teardown(self):
        shutil.rmtree(self.fake_home, ignore_errors=True)
        os.chdir(self.orig_dir)

    def test_startup(self):
        # Make sure debug server starts without error
        p = pexpect.spawn(
            'dallinger',
            ['debug', '--verbose'],
            env=self.environ,
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact('Server is running', timeout=120)
        finally:
            p.sendcontrol('c')
            p.read()

    def test_warning_if_no_heroku_present(self):
        environ = self.environ.copy()
        # Remove the path item that has heroku in it
        path_items = environ['PATH'].split(':')
        path_items = [
            item for item in path_items
            if not os.path.exists(os.path.join(item, 'heroku'))
        ]
        environ.update({
            'PATH': ':'.join(path_items)
        })
        p = pexpect.spawn(
            'dallinger',
            ['debug', '--verbose'],
            env=environ,
        )
        p.logfile = sys.stdout
        try:
            p.expect_exact("Couldn't start Heroku for local debugging", timeout=120)
        finally:
            p.sendcontrol('c')
            p.read()

    # def test_debug_bots(self):
    #     # Make sure debug server runs to completion with bots
    #     p = pexpect.spawn(
    #         'dallinger',
    #         ['debug', '--verbose', '--bot'],
    #         env=self.environ,
    #     )
    #     p.logfile = sys.stdout
    #     try:
    #         p.expect_exact('Server is running', timeout=120)
    #         p.expect_exact('Recruitment is complete', timeout=300)
    #         p.expect_exact('Experiment completed', timeout=120)
    #         p.expect_exact('Local Heroku process terminated', timeout=10)
    #     finally:
    #         p.sendcontrol('c')
    #         p.read()


class TestHeader(object):
    def test_header_contains_version_number(self):
        # Make sure header contains the version number.
        assert dallinger.version.__version__ in dallinger.command_line.header
