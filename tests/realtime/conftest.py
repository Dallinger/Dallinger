import pytest

from dallinger import experiment
from tests.realtime import helpers
from tests.realtime.helpers import TurnTally


@pytest.fixture
def realtime_experiment(monkeypatch, db_session):
    """Load an experiment whose only game type is TurnTally, and return its
    class, so a test can change its game types.
    """

    class Loaded:
        channel = None
        realtime_games = [TurnTally]

    monkeypatch.setattr(experiment, "load", lambda: Loaded)
    return Loaded


@pytest.fixture(autouse=True)
def no_runaway_passes():
    helpers.runaway_passes.clear()
    yield
    assert not helpers.runaway_passes, helpers.runaway_passes[0]
