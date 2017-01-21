#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import mock
import pytest
import dallinger.db
from dallinger.config import get_config
from dallinger.heroku import app_name


@pytest.fixture
def setup():
    db = dallinger.db.init_db(drop_all=True)
    os.chdir('tests/experiment')
    config = get_config()
    if not config.ready:
        config.load_config()
    yield config
    db.rollback()
    db.close()
    os.chdir('../..')


class TestHeroku(object):

    def test_heroku_app_name(self):
        id = "8fbe62f5-2e33-4274-8aeb-40fc3dd621a0"
        assert(len(app_name(id)) < 30)


class TestHerokuClock(object):

    def test_check_db_for_missing_notifications_assembles_resources(self, setup):
        # Can't import until after config is loaded:
        from dallinger.heroku.clock import check_db_for_missing_notifications
        with mock.patch.multiple('dallinger.heroku.clock',
                                 _run_notifications_check=mock.DEFAULT,
                                 MTurkConnection=mock.DEFAULT) as mocks:
            mocks['MTurkConnection'].return_value = 'fake connection'
            check_db_for_missing_notifications()

            mocks['_run_notifications_check'].assert_called()
