#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import subprocess


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
