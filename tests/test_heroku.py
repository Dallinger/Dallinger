#!/usr/bin/python
# -*- coding: utf-8 -*-
import os

from dallinger.heroku import app_name


class TestHeroku(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        os.chdir("demos")

    def teardown(self):
        os.chdir("..")

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_heroku_app_name(self):
        id = "8fbe62f5-2e33-4274-8aeb-40fc3dd621a0"
        assert(len(app_name(id)) < 30)
