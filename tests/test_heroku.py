"""Tests for the Wallace API."""

import subprocess
import re
import requests


class TestHeroku(object):

    """The Heroku test class."""

    def test_sandbox(self):
        """Launch the experiment on Heroku."""
        sandbox_output = subprocess.check_output(
            "cd examples/bartlett1932; wallace sandbox --verbose", shell=True)

        id = re.search(
            'Running as experiment (.*)...', sandbox_output).group(1)

        r = requests.get("http://{}.herokuapp.com/summary".format(id))

        assert r.json()['status'] == []

        subprocess.call(
            "heroku apps:destroy --app {} --confirm {}".format(id),
            shell=True)
