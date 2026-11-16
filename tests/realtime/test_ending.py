import threading
import time

import pytest
from rq import Queue, SimpleWorker

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession
from dallinger.realtime import add_realtime_player, jobs, store
from dallinger.realtime.game import FINISHED, MAX_DURATION
from dallinger.realtime.runner import Runner
from dallinger.realtime.session_sockets import SessionSocket
from tests.realtime.helpers import (
    Growing,
    TurnTally,
    add,
    create_session,
    join,
    keys_expire,
    message,
)

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
    session_id = create_session(game_type, ["1"])
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


def test_a_player_added_to_a_running_game_plays_and_can_finish_before_it(
    realtime_experiment, saved_frames
):
    realtime_experiment.realtime_games = [TurnTally, Growing]
    Growing.player_endings.clear()
    session_id = create_session(Growing, ["1"])
    add(session_id, join(0, "1"))
    with pytest.raises(ValueError, match="doesn't define on_add"):
        add_realtime_player(create_session(TurnTally, ["1"]), 3)
    add_realtime_player(session_id, 3)
    db.session.commit()
    assert db.session.get(RealtimeSession, session_id).members == [1]
    add(session_id, join(0, "3"))
    add(session_id, message(0, "3", "leave"))

    runner = Runner(store.experiment_games(), name="test-runner")
    playing = threading.Thread(target=runner.run)
    playing.start()
    try:
        deadline = time.monotonic() + 5
        while (
            store.load_player_ending(session_id, "3") is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
    finally:
        runner.stop()
        playing.join(5)
    jobs.write_records(session_id)

    row = db.session.get(RealtimeSession, session_id)
    assert row.members == [1, 3] and row.status == "running"
    with pytest.raises(ValueError, match="already a player"):
        add_realtime_player(session_id, "3")
    events = db.session.query(RealtimeEvent).filter_by(session_id=session_id)
    assert [
        (e.event_type, e.participant_id, e.reason)
        for e in events
        if e.participant_id == 3
    ] == [
        ("player_add", 3, None),
        ("message", 3, None),
        ("player_end", 3, "done"),
    ]
    ((_, player, ending),) = Growing.player_endings
    assert (player, ending["reason"]) == ("3", "done")
    ((participants, _, frame),) = saved_frames()
    assert (participants, frame["status"], frame["reason"]) == (["3"], "ended", "done")
    reload = SessionSocket(session_id, Growing(), "3", "page", "a reload")
    assert '"realtime_saved"' in reload.join()
