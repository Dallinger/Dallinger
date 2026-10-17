import threading
import time

import pytest
from rq import Queue, SimpleWorker

from dallinger import db
from dallinger.models import RealtimeSession
from dallinger.realtime import store
from dallinger.realtime.game import FINISHED, MAX_DURATION
from dallinger.realtime.runner import Runner
from tests.realtime.helpers import TurnTally, add, join, keys_expire, message

pytestmark = pytest.mark.usefixtures("redis_conn")


class Brief(TurnTally):
    channel = "brief"
    max_duration = 0.3


def finish(session_id):
    add(session_id, message(0, "1", "stop"))


def end_from_outside(session_id):
    store.end_realtime_session(session_id, "abandoned")


@pytest.mark.parametrize(
    "game_type, end, reason",
    [
        (TurnTally, finish, FINISHED),
        (Brief, None, MAX_DURATION),
        (TurnTally, end_from_outside, "abandoned"),
    ],
)
def test_a_game_that_ends_is_saved_and_its_pages_are_told(
    realtime_experiment, saved_frames, game_type, end, reason
):
    realtime_experiment.realtime_games = [TurnTally, Brief]
    session_id = store.create_realtime_session(game_type, ["1"])
    add(session_id, join(0, "1"))
    runner = Runner(store.experiment_games(), name="test-runner")
    playing = threading.Thread(target=runner.run)
    playing.start()
    try:
        if end is not None:
            end(session_id)
        deadline = time.monotonic() + 5
        while store.running_sessions() and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        runner.stop()
        playing.join(5)
    assert store.running_sessions() == []

    queues = [Queue(name, connection=store.redis_conn) for name in ("high", "default")]
    SimpleWorker(queues, connection=store.redis_conn).work(burst=True)

    ended = db.session.get(RealtimeSession, session_id)
    assert (ended.status, ended.end_reason) == ("ended", reason)
    assert store.realtime_result(session_id)["reason"] == reason
    assert [payload["status"] for _, _, payload in saved_frames()] == ["ended"]
    assert keys_expire(session_id)
