import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

import pytest
from redis import ConnectionError as RedisConnectionError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from dallinger import db
from dallinger.models import Notification, RealtimeEvent, RealtimeSession
from dallinger.realtime import store
from dallinger.realtime.core import fail_session, run_pass
from dallinger.realtime.jobs import write_ending, write_records
from dallinger.realtime.utils import dump_json
from tests.realtime.helpers import (
    CLOCK,
    TurnTally,
    clock,
    create_session,
    keys_expire,
    message,
)

pytestmark = pytest.mark.usefixtures("redis_conn", "realtime_experiment")


class Scoring(TurnTally):
    def handle_effect(self, name, payload, session_row):
        db.session.add(
            Notification(
                assignment_id="{}:{}".format(session_row.id, payload["by"]),
                event_type=name,
            )
        )


# Runs two records jobs for one session as a gevent worker would: patched
# before Dallinger is imported, as dallinger_scripts/worker.py does, with each
# job in its own greenlet. The effect handler yields while the first job holds
# the session's row lock.
JOBS_IN_A_GEVENT_WORKER = """
import gevent.monkey

gevent.monkey.patch_all()

import sys

import dallinger.heroku.rq_gevent_worker
import gevent

from dallinger import experiment
from dallinger.realtime.jobs import write_records
from tests.realtime.helpers import TurnTally


class Yielding(TurnTally):
    def handle_effect(self, name, payload, session_row):
        gevent.sleep(0.1)


class Loaded:
    channel = None
    realtime_games = [Yielding]


experiment.load = lambda: Loaded
jobs = [gevent.spawn(write_records, int(sys.argv[1])) for _ in range(2)]
gevent.joinall(jobs)
sys.exit(0 if all(job.successful() for job in jobs) else 1)
"""

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def save(session_id, entries, now, error=None):
    """Play a pass over ``entries`` and save it, as a runner would, or fail the
    session with ``error``.
    """
    store.redis_conn.delete(store.session_key(session_id, "claim"))
    token, _ = store.claim(session_id, "test", 30)
    saved = store.load_session(session_id)["saved"]
    game = store.experiment_games()["tally"]
    if error is None:
        result = run_pass(game, saved, entries, now, CLOCK)
    else:
        result = fail_session(game, saved, entries, now, CLOCK, error)
    assert store.save_passes([(session_id, token, [], result)], 30) == []
    return result


def events(session_id):
    return (
        db.session.query(RealtimeEvent)
        .filter_by(session_id=session_id)
        .order_by(RealtimeEvent.sequence)
        .all()
    )


def row(session_id):
    return db.session.get(RealtimeSession, session_id)


def records_left(session_id):
    return store.redis_conn.xlen(store.session_key(session_id, "records"))


def wait_for_a_lock_wait():
    """Wait until a connection is waiting for a lock another holds."""
    deadline = time.monotonic() + 5
    with db.engine.connect() as connection:
        while time.monotonic() < deadline:
            # Each poll in its own transaction: Postgres keeps the
            # pg_stat_activity it first read until the transaction ends.
            with connection.begin():
                waiting = connection.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE wait_event_type = 'Lock'"
                    )
                ).scalar()
            if waiting:
                return
            time.sleep(0.01)
    raise AssertionError("No connection waited for a lock.")


def entries(session_id):
    return [
        json.loads(fields[b"entry"])
        for _, fields in store.redis_conn.xrange(
            store.session_key(session_id, "entries")
        )
    ]


class TestWritingRecords:
    def test_records_become_events_and_effects_are_handled_with_them(
        self, realtime_experiment
    ):
        realtime_experiment.realtime_games = [Scoring]
        session_id = create_session(Scoring, ["1", "2"])
        state = save(
            session_id,
            [
                message(1, "1", "up", number=3),
                message(2, "2", "bad"),
                message(3, "1", "effect"),
            ],
            now=6,
        ).records[-1]["state"]
        assert store.mark_records_queued(session_id, 30)

        write_records(session_id)

        written = events(session_id)
        assert [
            (each.sequence, each.event_type, each.participant_id, each.payload)
            for each in written
        ] == [
            (1, "message", 1, "up"),
            (2, "message", 2, "bad"),
            (3, "message", 1, "effect"),
            (4, "effect", None, {"by": "1"}),
            (5, "checkpoint", None, None),
        ]
        up, bad, _, effect, checkpoint = written
        assert (
            up.scope,
            up.number,
            up.browser_time,
            up.view_time,
            up.session_time,
        ) == ("page", 3, 50.0, 0.0, 1)
        assert up.receive_time == datetime.fromtimestamp(101.0)
        assert (up.status, bad.status, bad.reason) == (
            "accepted",
            "rejected",
            {"code": "bad"},
        )
        sql_null = db.session.query(RealtimeEvent.sequence).filter(
            RealtimeEvent.event_type == "message", RealtimeEvent.reason.is_(None)
        )
        assert sorted(sequence for (sequence,) in sql_null) == [1, 3]
        assert effect.name == "scored"
        assert checkpoint.state == state
        assert row(session_id).checkpoint == state
        assert [
            (each.assignment_id, each.event_type)
            for each in db.session.query(Notification)
        ] == [("{}:1".format(session_id), "scored")]
        assert records_left(session_id) == 0
        assert store.mark_records_queued(session_id, 30)

    def test_a_clock_measurement_becomes_an_event(self):
        session_id = create_session(TurnTally, ["1"])
        save(session_id, [clock(1, "1")], now=1)
        assert store.mark_records_queued(session_id, 30)

        write_records(session_id)

        (measured,) = events(session_id)
        assert (
            measured.event_type,
            measured.session_time,
            measured.participant_id,
            measured.scope,
            measured.browser_time,
            measured.payload,
            measured.receive_time,
        ) == (
            "clock",
            1,
            1,
            "page",
            5001.0,
            {"server_time": 901.0, "round_trip": 0.04},
            datetime.fromtimestamp(101.0),
        )

    def test_a_later_job_writes_only_the_records_added_since(self):
        session_id = create_session(TurnTally, ["1"])
        save(session_id, [message(1, "1", "up")], now=1)
        write_records(session_id)
        save(session_id, [message(2, "1", "down")], now=2, error=KeyError("down"))

        write_records(session_id)
        write_records(session_id)

        written = events(session_id)
        assert [(each.sequence, each.event_type, each.status) for each in written] == [
            (1, "message", "accepted"),
            (2, "message", "failed"),
            (3, "end", None),
        ]
        end = written[-1]
        assert (end.reason, end.outcome, end.state) == (
            "failed",
            {"reason": "failed", "moves": 1},
            {"players": ["1"], "log": [["1", "up", 1]]},
        )
        assert "KeyError: 'down'" in end.error
        ended = row(session_id)
        assert (ended.status, ended.end_reason, ended.outcome, ended.final_state) == (
            "failed",
            "failed",
            end.outcome,
            end.state,
        )
        assert ended.error == end.error

    def test_records_a_job_wrote_but_couldnt_remove_arent_written_again(
        self, monkeypatch
    ):
        def fail_to_trim(*args):
            raise RedisConnectionError("lost")

        session_id = create_session(TurnTally, ["1"])
        save(session_id, [message(1, "1", "up")], now=1)
        with monkeypatch.context() as patched:
            patched.setattr(store, "trim_records", fail_to_trim)
            with pytest.raises(RedisConnectionError):
                write_records(session_id)
        assert row(session_id).status == "running"
        save(session_id, [message(2, "1", "down")], now=2)

        write_records(session_id)

        assert [each.payload for each in events(session_id)] == ["up", "down"]
        assert row(session_id).status == "running"
        assert records_left(session_id) == 0

    def test_overlapping_jobs_write_each_record_once(self, realtime_experiment):
        class Waiting(TurnTally):
            started = threading.Event()
            release = threading.Event()

            def handle_effect(self, name, payload, session_row):
                self.started.set()
                assert self.release.wait(5)

        realtime_experiment.realtime_games = [Waiting]
        session_id = create_session(Waiting, ["1"])
        save(session_id, [message(1, "1", "effect"), message(2, "1", "up")], now=2)
        errors = []

        def job():
            try:
                write_records(session_id)
            except Exception as error:
                errors.append(error)

        first = threading.Thread(target=job)
        first.start()
        assert Waiting.started.wait(5)
        assert store.mark_records_queued(session_id, 30)
        second = threading.Thread(target=job)
        second.start()
        wait_for_a_lock_wait()
        waiting_job_kept_the_flag = not store.mark_records_queued(session_id, 30)
        Waiting.release.set()
        first.join(5)
        second.join(5)

        assert errors == []
        assert waiting_job_kept_the_flag
        assert [each.sequence for each in events(session_id)] == [1, 2, 3]
        assert row(session_id).status == "running"


class TestEnding:
    def test_the_final_job_tells_the_players_pages_and_expires_the_sessions_keys(
        self, saved_frames
    ):
        session_id = create_session(TurnTally, ["1", "2", "9"], bots=["9"])
        before = datetime.now()
        save(session_id, [message(1, "1", "up"), message(2, "1", "stop")], now=2)
        after = datetime.now()
        assert store.realtime_result(session_id) is None
        assert store.load_ending(session_id)["status"] is None

        write_ending(session_id)

        assert store.load_ending(session_id)["status"] == "ended"
        ended = row(session_id)
        assert (ended.status, ended.end_reason, ended.final_state, ended.error) == (
            "ended",
            "finished",
            {"players": ["1", "2", "9"], "log": [["1", "up", 1], ["1", "stop", 2]]},
            None,
        )
        # Stream IDs count whole milliseconds.
        assert before - timedelta(milliseconds=1) <= ended.end_time <= after
        assert store.realtime_result(session_id) == {"reason": "finished", "moves": 2}
        log = [["1", "up", 1], ["1", "stop", 2]]
        assert saved_frames() == [
            (
                [player],
                None,
                {
                    "type": "realtime_saved",
                    "session_id": session_id,
                    "status": "ended",
                    "reason": "finished",
                    "view": {"for": player, "log": log},
                },
            )
            for player in ("1", "2")
        ]
        assert keys_expire(session_id)

    def test_a_final_job_that_fails_still_tells_the_pages_and_expires_the_keys(
        self, saved_frames
    ):
        session_id = create_session(TurnTally, ["1"])
        save(session_id, [message(1, "1", "effect"), message(2, "1", "stop")], now=2)

        with pytest.raises(NotImplementedError):
            write_ending(session_id)

        failed = row(session_id)
        assert (failed.status, failed.end_reason) == ("failed", None)
        assert store.realtime_result(session_id) is None
        assert [payload["status"] for _, _, payload in saved_frames()] == ["failed"]
        assert keys_expire(session_id)


@pytest.mark.slow
def test_a_gevent_worker_runs_a_job_waiting_for_the_lock_beside_its_holder():
    session_id = create_session(TurnTally, ["1"])
    save(session_id, [message(1, "1", "effect"), message(2, "1", "up")], now=2)

    # A wait on the lock that blocks the whole process times out instead of
    # hanging, which fails the waiting job.
    worker = subprocess.run(
        [sys.executable, "-c", JOBS_IN_A_GEVENT_WORKER, str(session_id)],
        cwd=REPO,
        env={**os.environ, "PGOPTIONS": "-c lock_timeout=3s"},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert worker.returncode == 0, worker.stderr
    assert [each.sequence for each in events(session_id)] == [1, 2, 3]
    assert row(session_id).status == "running"


class TestFailing:
    def test_a_job_that_raises_fails_the_session_and_saves_nothing(self, monkeypatch):
        def lose_redis(*args):
            raise RedisConnectionError("lost")

        session_id = create_session(TurnTally, ["1"])
        save(session_id, [message(1, "1", "up"), message(2, "1", "effect")], now=2)

        with pytest.raises(NotImplementedError):
            write_records(session_id)

        assert events(session_id) == []
        failed = row(session_id)
        assert failed.status == "failed"
        assert (
            "TurnTally queued the effect 'scored' but doesn't define handle_effect."
            in failed.error
        )
        assert entries(session_id) == [{"type": "end", "reason": "failed"}]
        error = failed.error

        save(session_id, [message(3, "1", "up")], now=3)
        write_records(session_id)

        assert events(session_id) == []
        assert records_left(session_id) == 0
        monkeypatch.setattr(store, "delete_records", lose_redis)
        with pytest.raises(RedisConnectionError):
            write_records(session_id)
        assert row(session_id).error == error

    @pytest.mark.parametrize("ending", ["commit", "rollback"])
    def test_a_handler_that_ends_the_transaction_fails_the_session(
        self, realtime_experiment, ending
    ):
        class Committing(TurnTally):
            def handle_effect(self, name, payload, session_row):
                getattr(db.session, ending)()

        realtime_experiment.realtime_games = [Committing]
        session_id = create_session(Committing, ["1"])
        save(session_id, [message(1, "1", "up"), message(2, "1", "effect")], now=2)

        with pytest.raises(RuntimeError) as raised:
            write_records(session_id)

        assert str(raised.value).startswith(
            "Committing.handle_effect, handling the effect 'scored',"
        )
        assert events(session_id) == []
        assert row(session_id).status == "failed"

    def test_a_later_job_ends_a_failed_session_the_failing_one_couldnt(
        self, monkeypatch
    ):
        def lose_redis(*args):
            raise RedisConnectionError("lost")

        session_id = create_session(TurnTally, ["1"])
        save(session_id, [message(1, "1", "effect")], now=1)
        with monkeypatch.context() as patched:
            patched.setattr(store, "end_realtime_session", lose_redis)
            with pytest.raises(NotImplementedError):
                write_records(session_id)
        assert entries(session_id) == []

        write_records(session_id)

        assert entries(session_id) == [{"type": "end", "reason": "failed"}]

    def test_a_job_that_fails_once_the_ending_is_saved_leaves_it_saved(self):
        session_id = create_session(TurnTally, ["1"])
        save(session_id, [message(1, "1", "stop")], now=1)
        write_records(session_id)
        store.redis_conn.xadd(
            store.session_key(session_id, "records"),
            {"record": dump_json({"sequence": 3, "type": "checkpoint"})},
        )

        with pytest.raises(KeyError):
            write_records(session_id)

        ended = row(session_id)
        assert (ended.status, ended.end_reason, ended.error) == (
            "ended",
            "finished",
            None,
        )

    def test_records_that_repeat_written_sequence_numbers_fail_the_session(self):
        session_id = create_session(TurnTally, ["1"])
        save(session_id, [message(1, "1", "up")], now=1)
        before = store.load_session(session_id)["saved"]
        save(session_id, [message(2, "1", "down")], now=2)
        write_records(session_id)
        # Redis restored from before the second pass hands out its sequence
        # numbers again.
        store.redis_conn.hset(store.session_key(session_id, "state"), "saved", before)
        save(session_id, [message(2, "1", "left")], now=2)

        with pytest.raises(IntegrityError):
            write_records(session_id)

        assert [each.payload for each in events(session_id)] == ["up", "down"]
        assert row(session_id).status == "failed"
        assert "duplicate key" in row(session_id).error
        assert entries(session_id) == [{"type": "end", "reason": "failed"}]

    def test_a_session_whose_state_cant_be_read_fails_without_an_end_event(self):
        session_id = create_session(TurnTally, ["1"])
        save(session_id, [message(1, "1", "up")], now=1)
        result = fail_session(
            None, "unreadable", [], 0, CLOCK, RuntimeError("no saved state")
        )
        store.redis_conn.xadd(
            store.session_key(session_id, "records"),
            {"record": dump_json(result.records[0])},
        )

        write_records(session_id)

        assert [each.payload for each in events(session_id)] == ["up"]
        failed = row(session_id)
        assert (failed.status, failed.end_reason) == ("failed", "failed")
        assert "RuntimeError: no saved state" in failed.error
