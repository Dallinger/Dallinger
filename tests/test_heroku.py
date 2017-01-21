#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import mock
from dallinger.config import get_config
from dallinger.heroku import app_name


class TestHeroku(object):

    def test_heroku_app_name(self):
        id = "8fbe62f5-2e33-4274-8aeb-40fc3dd621a0"
        assert(len(app_name(id)) < 30)


class TestHerokuClock(object):

    def test_check_db_for_missing_notifications_assembles_resources(self):
        os.chdir('tests/experiment')

        config = get_config()
        if not config.ready:
            config.load_config()
        # Can't import until after config is loaded:
        from dallinger.heroku.clock import check_db_for_missing_notifications
        runner = 'dallinger.heroku.clock._run_notifications_check'
        with mock.patch(runner) as mock_runner:
            check_db_for_missing_notifications()

        mock_runner.assert_called()
