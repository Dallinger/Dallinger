"""Tests for the Dallinger API."""

import subprocess
import re
import os
import requests


class TestHeroku(object):

    """The Heroku test class."""

    sandbox_output = subprocess.check_output([
        "cd",
        "demos/bartlett1932;",
        "dallinger",
        "sandbox",
        "--verbose"
    ])

    os.environ['app_id'] = re.search(
        'Running as experiment (.*)...', sandbox_output).group(1)

    @classmethod
    def teardown_class(cls):
        """Remove the app from Heroku."""
        app_id = os.environ['app_id']
        subprocess.call([
            "heroku",
            "apps:destroy",
            "--app",
            app_id,
            "--confirm",
            app_id
        ])

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

    def test_nonexistent_route(self):
        """Ensure that a nonexistent route returns a 500 error."""
        app_id = os.environ['app_id']
        r = requests.get("http://{}.herokuapp.com/nope".format(app_id))
        assert r.status_code == 500
