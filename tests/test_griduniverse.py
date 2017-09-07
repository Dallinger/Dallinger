"""
Tests for `dlgr.griduniverse` module.
"""
import mock
import os
import pytest
import shutil
import tempfile
from dallinger.experiments import Griduniverse


class TestGriduniverse(object):


    def test_bot_api(self):
        """Run bots using headless chrome and collect data."""
        self.experiment = Griduniverse()
        data = self.experiment.run(
                mode=u'debug',
                webdriver_type=u'chrome',
                recruiter=u'bots',
                bot_policy=u"AdvantageSeekingBot",
                max_participants=1,
                num_dynos_worker=1,
                time_per_round=30.0,
           )
        results = self.experiment.average_score(data)
        assert results > 0