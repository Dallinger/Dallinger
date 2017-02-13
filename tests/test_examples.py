#!/usr/bin/python
# -*- coding: utf-8 -*-
import os

import dallinger


class TestExamples(object):

    def setup(self):
        """Set up the environment by resetting the tables."""
        os.chdir("demos")

    def teardown(self):
        os.chdir("..")

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def verify_demo(self, demo):
        os.chdir(demo)
        is_passing = dallinger.command_line.verify_package()
        assert is_passing
        os.chdir("..")

    def test_verify_demo_bartlett1932(self):
        self.verify_demo("bartlett1932")

    def test_verify_demo_function_learning(self):
        self.verify_demo("function-learning")
