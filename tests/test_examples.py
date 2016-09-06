#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import subprocess


class TestExamples(object):

    def setup(self):
        """Set up the environment by resetting the tables."""
        os.chdir("examples")

    def teardown(self):
        os.chdir("..")

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def verify_example(self, example):
        os.chdir(example)
        output = subprocess.check_output("dallinger verify", shell=True)
        assert "✗" not in output
        os.chdir("..")

    def test_verify_example_bartlett1932(self):
        self.verify_example("bartlett1932")

    def test_verify_example_function_learning(self):
        self.verify_example("function-learning")
