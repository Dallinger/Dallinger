#!/usr/bin/python
# -*- coding: utf-8 -*-
import os

from pytest import raises

from dallinger.config import get_config


class TestClock(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        os.chdir('tests/experiment')
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
        with raises(RuntimeError, message='Config loading not finished'):
            jobs[0].func()

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
