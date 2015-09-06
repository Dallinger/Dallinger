"""Tests for the Wallace API."""

import subprocess
import re
import os
import requests


class TestHeroku(object):

    """The Heroku test class."""

    sandbox_output = subprocess.check_output(
        "cd examples/bartlett1932; wallace sandbox --verbose", shell=True)

    os.environ['app_id'] = re.search(
        'Running as experiment (.*)...', sandbox_output).group(1)

    @classmethod
    def teardown_class(cls):
        """Remove the app from Heroku."""
        app_id = os.environ['app_id']
        subprocess.call(
            "heroku apps:destroy --app {} --confirm {}".format(app_id, app_id),
            shell=True)

    def test_summary(self):
        """Launch the experiment on Heroku."""
        app_id = os.environ['app_id']
        r = requests.get("http://{}.herokuapp.com/summary".format(app_id))
        assert r.json()['status'] == []

    def test_robots(self):
        """Ensure that robots.txt can be accessed."""
        app_id = os.environ['app_id']
        r = requests.get("http://{}.herokuapp.com/robots.txt".format(app_id))
        assert r.status_code == 200
