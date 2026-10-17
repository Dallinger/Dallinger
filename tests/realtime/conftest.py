import json

import pytest

from dallinger import experiment
from dallinger.db import DIRECT_CHANNEL
from dallinger.realtime import store
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


@pytest.fixture
def saved_frames():
    """Return a function that returns each realtime_saved frame published
    since the test started, as its ``(participant_ids, scope, payload)``.
    """
    pubsub = store.redis_conn.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(DIRECT_CHANNEL)
    # The confirmation, which get_message consumes and returns as None.
    pubsub.get_message(timeout=1)

    def frames():
        received = []
        for published in iter(lambda: pubsub.get_message(timeout=0.2), None):
            for item in json.loads(published["data"])["items"]:
                payload = json.loads(item["payload"])
                if payload["type"] == "realtime_saved":
                    received.append((item["participant_ids"], item["scope"], payload))
        return received

    yield frames
    pubsub.close()
