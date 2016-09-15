#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import subprocess
from dallinger.command_line import heroku_id


class TestCommandLine(object):

    def setup(self):
        """Set up the environment by moving to the demos directory."""
        os.chdir("demos")

    def teardown(self):
        os.chdir("..")

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_dallinger_help(self):
        output = subprocess.check_output("dallinger", shell=True)
        assert("Usage: dallinger [OPTIONS] COMMAND [ARGS]" in output)

    def test_heroku_app_id(self):
        id = "8fbe62f5-2e33-4274-8aeb-40fc3dd621a0"
        assert(len(heroku_id(id)) < 30)
