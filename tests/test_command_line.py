#!/usr/bin/python
# -*- coding: utf-8 -*-
import filecmp
import os
import pexpect
import subprocess
from dallinger.config import get_config


class TestCommandLine(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        os.chdir("demos")

    def teardown(self):
        os.chdir("..")

    def test_dallinger_help(self):
        output = subprocess.check_output("dallinger", shell=True)
        assert("Usage: dallinger [OPTIONS] COMMAND [ARGS]" in output)


class TestSetupExperiment(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        self.orig_dir = os.getcwd()
        os.chdir("demos/bartlett1932")

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
        assert(os.path.exists('psiturkapp.py') is False)
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
        assert(filecmp.cmp('dallinger_experiment.py',
                           os.path.join(exp_dir, 'experiment.py')) is True)

        assert(os.path.exists('Procfile') is True)
        assert(os.path.exists('psiturkapp.py') is True)
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
        from localconfig import LocalConfig
        # Baseline config
        orig_config = LocalConfig('config.txt')
        assert(orig_config.get('Server Parameters', 'num_dynos_web') == 1)
        assert(orig_config.get('Server Parameters', 'bogus_entry') is None)
        assert(orig_config.get('New Group', 'something') is None)

        exp_id, dst = setup_experiment(exp_config={
            'Server Parameters': {'num_dynos_web': 2, 'bogus_entry': True},
            'New Group': {'something': 'nothing'}
        })
        # There should be a modified configuration in the temp dir
        os.chdir(dst)
        deploy_config = LocalConfig('config.txt')
        assert(deploy_config.get('Server Parameters', 'num_dynos_web') == 2)
        assert(deploy_config.get('Server Parameters', 'bogus_entry') is True)
        assert(deploy_config.get('New Group', 'something') == 'nothing')

    def test_setup_with_custom_localconfig(self):
        from dallinger.command_line import setup_experiment
        from localconfig import LocalConfig
        # Baseline config
        orig_config = LocalConfig('config.txt')
        assert(orig_config.get('Server Parameters', 'num_dynos_web') == 1)
        assert(orig_config.get('Server Parameters', 'bogus_entry') is None)
        assert(orig_config.get('New Group', 'something') is None)

        new_config = LocalConfig('bogus.txt')
        new_config.add_section('Experiment Configuration')
        new_config.add_section('Server Parameters')
        new_config.add_section('New Group')
        new_config.set('Server Parameters', 'num_dynos_web', 2)
        new_config.set('Server Parameters', 'bogus_entry', True)
        new_config.set('New Group', 'something', 'nothing')

        exp_id, dst = setup_experiment(exp_config=new_config)
        # There should be a modified configuration in the temp dir
        os.chdir(dst)
        deploy_config = LocalConfig('config.txt')
        assert(deploy_config.get('Server Parameters', 'num_dynos_web') == 2)
        assert(deploy_config.get('Server Parameters', 'bogus_entry') is True)
        assert(deploy_config.get('New Group', 'something') == 'nothing')


class TestDebugServer(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        self.orig_dir = os.getcwd()
        os.chdir("demos/bartlett1932")

    def teardown(self):
        os.chdir(self.orig_dir)

    def test_startup(self):
        # Make sure debug server starts without error
        port = get_config().get('port')
        p = pexpect.spawn('dallinger', ['debug'])
        p.expect_exact('Server is running on 0.0.0.0:{}. Press Ctrl+C to exit.'.format(port))
        p.sendcontrol('c')
