#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import print_function
import os
import pytest
import shutil
import sys


class TestGridUniverse(object):
    @pytest.mark.skipif(
        not pytest.config.getvalue("griduniverse"),
        reason="--griduniverse was specified",
    )
    def test_tests(self):
        from dallinger.utils import GitClient
        from dallinger.utils import run_command

        original_dir = os.getcwd()
        git = GitClient()
        gudir = git.clone("https://github.com/Dallinger/Griduniverse.git")
        os.chdir(gudir)
        cmd = [sys.executable, "setup.py", "develop"]
        st = run_command(cmd, sys.stdout)
        cmd = [sys.executable, "-m", "pytest"]
        st = run_command(cmd, sys.stdout, ignore_errors=True)
        os.chdir(original_dir)
        shutil.rmtree(gudir, ignore_errors=True)
        print("Grid Universe tests finished running.")
        if st != 0:
            print("Some tests failed.")
        assert st == 0
