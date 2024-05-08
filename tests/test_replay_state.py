"""Tests for the data module."""

import os
import shutil
from datetime import datetime
from unittest import mock

import pytest


@pytest.fixture
def zip_path():
    return os.path.join("tests", "datasets", "test_export.zip")


@pytest.mark.slow
class TestReplayState(object):
    @pytest.fixture
    def cleanup(self):
        yield
        shutil.rmtree("data")

    @pytest.fixture
    def experiment(self):
        from dlgr.demos.bartlett1932.experiment import Bartlett1932

        yield Bartlett1932()

    bartlett_export = os.path.join("tests", "datasets", "bartlett_bots.zip")

    @pytest.fixture
    def scrubber(self, experiment, db_session):
        with experiment.restore_state_from_replay(
            "bartlett-test", session=db_session, zip_path=self.bartlett_export
        ) as scrubber:
            yield scrubber

    def test_scrub_forwards(self, scrubber):
        target = datetime(2017, 6, 23, 12, 0, 29, 941148)
        with mock.patch(
            "dlgr.demos.bartlett1932.experiment.Bartlett1932.replay_event"
        ) as replay_event:
            replay_event.assert_not_called()
            scrubber(target)
            assert replay_event.call_count == 4
            scrubber(datetime.now())
            assert replay_event.call_count == 5

    def test_cannot_scrub_backwards(self, scrubber):
        target = datetime(2017, 6, 23, 12, 0, 29, 941148)
        with mock.patch(
            "dlgr.demos.bartlett1932.experiment.Bartlett1932.replay_event"
        ) as replay_event:
            replay_event.assert_not_called()
            scrubber(datetime.now())
            assert replay_event.call_count == 5
            with pytest.raises(NotImplementedError):
                scrubber(target)
