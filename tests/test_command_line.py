#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import subprocess


class TestCommandLine(object):

    def setup(self):
        """Set up the environment by moving to the examples directory."""
        os.chdir("examples")

    def teardown(self):
        os.chdir("..")

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_wallace_help(self):
        output = subprocess.check_output("wallace", shell=True)
        assert("Usage: wallace [OPTIONS] COMMAND [ARGS]" in output)
