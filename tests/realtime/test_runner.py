import json
import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import gevent
import pytest
from redis import ConnectionError as RedisConnectionError

from dallinger.db import REALTIME_SESSION_CHANNEL
from dallinger.experiment_server import sockets
from dallinger.realtime import runner as runner_module
from dallinger.realtime import store
from dallinger.realtime.game import FAILED, MAX_TIME_LIMIT
from dallinger.realtime.runner import Runner
from dallinger.realtime.time_limit import GIVE_UP_AFTER
from tests.realtime.helpers import Tally, TurnTally, add, jobs, join, message

pytestmark = pytest.mark.usefixtures("redis_conn")


class Ticker(Tally):
    channel = "ticker"
    tick_rate = 2


class Sleeper(TurnTally):
    channel = "sleeper"

    def apply(self, state, player_id, message, now, sent):
        time.sleep(0.2)
        super().apply(state, player_id, message, now, sent)


class Paced(Sleeper):
    channel = "paced"
    tick_rate = 100


class Crasher(TurnTally):
    channel = "crasher"

    def apply(self, state, player_id, message, now, sent):
        if message == "crash":
            raise KeyError("no such move")
        super().apply(state, player_id, message, now, sent)


@pytest.fixture
def runner(realtime_experiment):
    realtime_experiment.realtime_games = [
        TurnTally,
        Ticker,
        Sleeper,
        Paced,
        Crasher,
    ]
    return Runner(store.experiment_games(), name="test-runner")


@pytest.fixture
def published(monkeypatch):
    """The views each step publishes, by session."""
    batches = []
    monkeypatch.setattr(
        runner_module,
        "publish_views",
        lambda origin, passes: batches.append(dict(passes)),
    )
    return batches


def moves(session_id):
    return [each[1] for each in store.realtime_state(session_id)["log"]]


class TestPlaying:
    def test_a_session_is_saved_before_its_views_are_sent(self, runner, monkeypatch):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        add(session_id, join(0, "1"))
        events = []
        save = store.save_passes
        monkeypatch.setattr(
            store,
            "save_passes",
            lambda passes, ttl: events.append("saved") or save(passes, ttl),
        )
        monkeypatch.setattr(
            runner_module,
            "publish_views",
            lambda origin, passes: events.append(dict(passes)),
        )

        runner.step()

        assert events[0] == "saved"
        assert [view["participant"] for view in events[1][session_id]] == ["1"]
        assert moves(session_id) == ["1"]

    def test_entries_and_ticks_take_turns_on_the_session_clock(self, runner, published):
        """The session resumes at the time an earlier runner saved it at."""
        session_id = store.create_realtime_session(Ticker, ["1"])
        token, _ = store.claim(session_id, "earlier", 30)
        add(session_id, message(0, "1", "early"))
        [item] = store.read_entries({session_id: None}, 0)[session_id]
        entry = dict(store.read_entry(*item), time=10)
        loaded = store.load_session(session_id)
        result = runner_module.run_pass(Ticker(), loaded["saved"], [entry], 10, 0)
        store.save_passes([(session_id, token, [item[0]], result)], 30)
        store.release_session_claims({session_id: token})

        runner.step()
        time.sleep(0.75)
        add(session_id, message(0, "1", "a"))
        time.sleep(0.75)
        runner.step()

        later = [
            each for each in store.realtime_state(session_id)["log"] if each[-1] > 10
        ]
        assert [each[0] for each in later[:3]] == ["tick", "1", "tick"]
        assert 10.5 < later[1][2] < 11
        assert store.running_sessions() == [session_id]

    def test_the_session_clock_follows_redis_rather_than_this_host(
        self, runner, published, monkeypatch
    ):
        ahead = SimpleNamespace(
            time=lambda: time.time() + 100, monotonic=time.monotonic
        )
        monkeypatch.setattr(runner_module, "time", ahead)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        add(session_id, message(0, "1", "a"))

        runner.step()

        assert store.running_sessions() == [session_id]
        [(_, _, applied_at)] = store.realtime_state(session_id)["log"]
        assert applied_at < 1

    def test_a_read_waits_until_the_next_tick(self, runner, published, monkeypatch):
        monkeypatch.setattr(runner_module, "CLAIM_INTERVAL", 30)
        monkeypatch.setattr(runner_module, "RECORDS_INTERVAL", 30)
        store.create_realtime_session(Ticker, ["1"])
        timeouts = []
        read = store.read_entries
        monkeypatch.setattr(
            store,
            "read_entries",
            lambda positions, timeout, count: (
                timeouts.append(timeout) or read(positions, timeout, count)
            ),
        )

        runner.step()
        runner.step()

        assert timeouts[0] <= 0
        assert 0.25 < timeouts[1] <= 0.5

    def test_an_idle_session_still_renews_its_claim(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "SESSION_RENEW_INTERVAL", 0.05)
        monkeypatch.setattr(runner_module, "CLAIM_TTL", 1)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        runner.step()
        time.sleep(0.3)

        runner.step()

        assert store.redis_conn.pttl(store.session_key(session_id, "claim")) > 900

    def test_a_backlog_is_applied_a_few_entries_a_pass(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "MAX_PASS_ENTRIES", 2)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        runner.step()
        for move in "abcde":
            add(session_id, message(0, "1", move))

        runner.step()
        first = moves(session_id)
        runner.step()

        assert (first, moves(session_id)) == (["a", "b"], ["a", "b", "c", "d"])

    def test_a_session_that_ends_is_let_go(self, runner, published):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        add(session_id, message(0, "1", "stop"))

        runner.step()

        assert session_id not in runner.sessions
        assert store.running_sessions() == []
        assert jobs("high") == [("dallinger.realtime.jobs.write_ending", (session_id,))]

    def test_records_are_queued_every_interval(self, runner, published, monkeypatch):
        monkeypatch.setattr(runner_module, "RECORDS_INTERVAL", 0.3)
        monkeypatch.setattr(runner_module, "SESSION_RENEW_INTERVAL", 0.05)
        quiet, busy = [
            store.create_realtime_session(TurnTally, ["1"]) for _ in range(2)
        ]
        job = "dallinger.realtime.jobs.write_records"
        runner.step()
        # A runner taking over a session queues a job for it at once.
        assert jobs("default") == [(job, (quiet,)), (job, (busy,))]
        for session_id in (quiet, busy):
            store.start_writing_records(session_id)
        add(busy, message(0, "1", "a"))
        runner.step()
        assert list(published[-1]) == [busy]
        time.sleep(0.1)
        runner.step()
        assert list(published[-1]) == [quiet, busy]
        assert len(jobs("default")) == 2

        time.sleep(0.3)
        runner.step()
        time.sleep(0.3)
        runner.step()

        assert jobs("default")[2:] == [(job, (busy,))]

    def test_a_session_gets_no_second_job_until_its_first_starts_or_expires(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "RECORDS_INTERVAL", 0)
        monkeypatch.setattr(runner_module, "RECORDS_QUEUED_TTL", 0.3)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        runner.step()
        add(session_id, message(0, "1", "a"))
        runner.step()
        runner.step()
        assert len(jobs("default")) == 1

        time.sleep(0.3)
        add(session_id, message(0, "1", "b"))
        runner.step()
        runner.step()

        assert len(jobs("default")) == 2

    def test_an_idle_runner_waits_to_claim_new_sessions(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "CLAIM_INTERVAL", 0.2)
        started = time.monotonic()
        runner.step()
        assert time.monotonic() - started >= 0.15
        session_id = store.create_realtime_session(TurnTally, ["1"])

        runner.step()

        assert list(runner.sessions) == [session_id]

    def test_a_runner_with_sessions_still_claims_every_interval(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "CLAIM_INTERVAL", 0.2)
        timeouts = []
        read = store.read_entries
        monkeypatch.setattr(
            store,
            "read_entries",
            lambda positions, timeout, count: (
                timeouts.append(timeout) or read(positions, timeout, count)
            ),
        )
        store.create_realtime_session(TurnTally, ["1"])

        runner.step()
        runner.step()

        assert max(timeouts) <= 0.2


def holder(session_id):
    claim = store.redis_conn.get(store.session_key(session_id, "claim"))
    return None if claim is None else claim.decode().split(":", 1)[1]


def handover(session_id, runner):
    """Claim the session for a runner that stops without giving it up."""
    store.redis_conn.delete(store.session_key(session_id, "claim"))
    store.claim(session_id, runner, 30)
    store.redis_conn.delete(store.session_key(session_id, "claim"))


class TestOwnership:
    def test_runners_split_the_sessions_without_a_handover(
        self, runner, published, realtime_experiment
    ):
        """The first runner claims every session, then gives the second its
        own once it sees the second running.
        """
        other = Runner(store.experiment_games(), name="other")
        sessions = [store.create_realtime_session(TurnTally, ["1"]) for _ in range(10)]
        runner.step()
        other.step()
        runner.next_claim = 0
        runner.step()

        other.next_claim = 0
        other.step()

        held = {**{each: runner.name for each in runner.sessions}}
        held.update({each: other.name for each in other.sessions})
        assert sorted(held) == sessions
        assert len(held) == len(runner.sessions) + len(other.sessions)
        assert set(held.values()) == {runner.name, other.name}
        assert [holder(each) for each in sessions] == [held[each] for each in sessions]

    def test_only_the_sessions_of_a_runner_that_leaves_change_hands(self):
        sessions = range(1, 301)
        three = {each: runner_module.owner(each, ["a", "b", "c"]) for each in sessions}
        two = {each: runner_module.owner(each, ["a", "b"]) for each in sessions}

        assert all(two[each] == three[each] for each in sessions if three[each] != "c")
        assert all(70 < list(three.values()).count(runner) < 130 for runner in "abc")

    def test_a_stopped_runner_gives_its_sessions_up(self, runner, published):
        sessions = [store.create_realtime_session(TurnTally, ["1"]) for _ in "ab"]
        thread = threading.Thread(target=runner.run)
        thread.start()
        deadline = time.monotonic() + 5
        while len(runner.sessions) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

        runner.stop()
        thread.join(5)

        assert not thread.is_alive()
        assert [holder(session_id) for session_id in sessions] == [None, None]
        assert store.mark_runner_alive("other", store.server_time(), 30) == ["other"]


class TestLostClaims:
    def test_a_step_longer_than_a_claim_renews_the_claims(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "CLAIM_TTL", 0.5)
        monkeypatch.setattr(runner_module, "HEARTBEAT_TTL", 0.5)
        monkeypatch.setattr(runner_module, "SESSION_RENEW_INTERVAL", 0.15)
        sessions = [store.create_realtime_session(Sleeper, ["1"]) for _ in range(4)]
        runner.step()
        for session_id in sessions:
            add(session_id, message(0, "1", "a"))

        runner.step()

        assert [moves(session_id) for session_id in sessions] == [["a"]] * 4
        assert sorted(runner.sessions) == sessions
        assert runner.name in store.mark_runner_alive("other", store.server_time(), 30)

    def test_a_lost_claim_sends_no_views_and_drops_the_session(
        self, runner, published, monkeypatch
    ):
        kept, stolen = [store.create_realtime_session(TurnTally, ["1"]) for _ in "ab"]
        runner.step()
        for session_id in (kept, stolen):
            add(session_id, join(0, "1"))
        store.redis_conn.delete(store.session_key(stolen, "claim"))
        store.claim(stolen, "another runner", 30)

        runner.step()

        assert list(published[-1]) == [kept]
        assert list(runner.sessions) == [kept]
        assert store.realtime_state(stolen)["log"] == []


class TestFailures:
    def test_a_failing_session_is_logged_and_the_others_play_on(
        self, runner, published, caplog
    ):
        failing, other = [
            store.create_realtime_session(Crasher, ["1"]) for _ in range(2)
        ]
        add(failing, message(0, "1", "crash"))
        add(other, message(0, "1", "a"))

        with caplog.at_level(logging.ERROR, logger=runner_module.__name__):
            runner.step()
        add(other, message(0, "1", "b"))
        runner.step()

        assert store.running_sessions() == [other]
        assert moves(other) == ["a", "b"]
        [logged] = caplog.records
        assert logged.getMessage().startswith(
            "Session {} of crasher failed:".format(failing)
        )
        assert "KeyError: 'no such move'" in logged.getMessage()

    def test_a_session_ended_as_failed_from_outside_isnt_logged_again(
        self, runner, published, caplog
    ):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        store.end_realtime_session(session_id, FAILED)

        with caplog.at_level(logging.ERROR, logger=runner_module.__name__):
            runner.step()

        assert store.running_sessions() == []
        assert caplog.records == []

    @pytest.mark.parametrize("handovers, outcome", [(2, None), (3, True), (4, False)])
    def test_a_session_that_changes_runners_too_often_fails(
        self, runner, published, handovers, outcome
    ):
        """Past the limit, the runner failing the session stopped too, so it
        ends without game code.
        """
        session_id = store.create_realtime_session(TurnTally, ["1"])
        for number in range(handovers):
            handover(session_id, "stopped {}".format(number))

        runner.step()

        ended = store.redis_conn.get(store.session_key(session_id, "final"))
        if outcome is None:
            assert ended is None
            assert store.running_sessions() == [session_id]
            return
        assert store.running_sessions() == []
        [*_, end] = [
            json.loads(fields[b"record"])
            for _, fields in store.redis_conn.xrange(
                store.session_key(session_id, "records")
            )
        ]
        assert "changed runners {} times without".format(handovers) in end["error"]
        assert (end["outcome"] is not None) == outcome

    @pytest.mark.parametrize(
        "field, value, error",
        [
            ("saved", "not a session", "JSONDecodeError"),
            ("game", "removed", "No game type of the experiment has the channel"),
            (None, None, "The session's state in redis can't be read: KeyError"),
        ],
    )
    def test_a_session_that_cannot_be_played_fails_in_the_store(
        self, runner, published, field, value, error
    ):
        broken, other = [
            store.create_realtime_session(TurnTally, ["1"]) for _ in range(2)
        ]
        state_key = store.session_key(broken, "state")
        if field is None:
            store.redis_conn.delete(state_key)
        else:
            store.redis_conn.hset(state_key, field, value)
        add(broken, message(0, "1", "a"))
        add(other, message(0, "1", "a"))

        runner.step()

        assert store.running_sessions() == [other]
        assert moves(other) == ["a"]
        final = store.redis_conn.get(store.session_key(broken, "final"))
        assert json.loads(final) == {"reason": FAILED, "views": {}}
        [(_, fields)] = store.redis_conn.xrange(store.session_key(broken, "records"))
        record = json.loads(fields[b"record"])
        assert (record["type"], record["reason"]) == ("end", FAILED)
        assert error in record["error"]
        assert store.redis_conn.xlen(store.session_key(broken, "entries")) == 0

    def test_a_session_whose_stream_dropped_entries_fails(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(store, "MAX_ENTRIES", 10)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        for n in range(300):
            add(session_id, message(0, "1", n))

        runner.step()

        final = json.loads(store.redis_conn.get(store.session_key(session_id, "final")))
        assert final["reason"] == FAILED
        records = store.redis_conn.xrange(store.session_key(session_id, "records"))
        error = json.loads(records[-1][1][b"record"])["error"]
        assert "dropped" in error
        assert store.realtime_state(session_id)["log"] == []

    def test_an_entry_that_waited_too_long_fails_the_session(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "MAX_ENTRY_WAIT", 0.1)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        add(session_id, message(0, "1", "a"))
        time.sleep(0.2)
        add(session_id, message(0, "1", "b"))

        runner.step()

        assert store.running_sessions() == []
        assert store.realtime_state(session_id)["log"] == []
        records = store.redis_conn.xrange(store.session_key(session_id, "records"))
        *messages, _ = [json.loads(fields[b"record"]) for _, fields in records]
        assert [(each["payload"], each["status"]) for each in messages] == [
            ("a", "failed"),
            ("b", "failed"),
        ]


def test_a_time_limit_ends_before_the_claims_it_started_with_expire():
    """Game code can run past its time limit until the runner gives up on
    it, and the runner extends its claims before each session's pass, so
    each claim has at least this long left.
    """
    claim_left = runner_module.CLAIM_TTL - runner_module.SESSION_RENEW_INTERVAL
    assert GIVE_UP_AFTER * MAX_TIME_LIMIT < claim_left


def test_a_runner_that_loses_redis_stops_and_leaves_its_claims(
    runner, published, monkeypatch
):
    session_id = store.create_realtime_session(TurnTally, ["1"])
    runner.step()
    monkeypatch.setattr(
        store, "read_entries", Mock(side_effect=RedisConnectionError("gone"))
    )

    with pytest.raises(RedisConnectionError):
        runner.run()

    assert holder(session_id) == runner.name


def test_a_runner_refuses_redis_before_7(runner, monkeypatch):
    monkeypatch.setattr(
        store.redis_conn, "info", lambda section: {"redis_version": "6.0.16"}
    )

    runner.stop()

    with pytest.raises(RuntimeError, match="needs redis 7.0 or later"):
        runner.run()


class TestSlowPasses:
    def test_a_pass_within_its_tick_logs_nothing(
        self, runner, published, monkeypatch, caplog
    ):
        monkeypatch.setattr(runner_module, "SLOW", 30)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        add(session_id, message(0, "1", "a"))

        with caplog.at_level(logging.WARNING, logger=runner_module.__name__):
            runner.step()

        assert caplog.records == []

    def test_the_shortest_tick_sets_the_limit_and_the_slowest_three_are_named(
        self, runner, published, monkeypatch, caplog
    ):
        monkeypatch.setattr(runner_module, "SLOW", 30)
        slow = [store.create_realtime_session(Paced, ["1"])] + [
            store.create_realtime_session(Sleeper, ["1"]) for _ in range(2)
        ]
        fast = store.create_realtime_session(TurnTally, ["1"])
        for session_id in slow + [fast]:
            add(session_id, message(0, "1", "a"))

        with caplog.at_level(logging.WARNING, logger=runner_module.__name__):
            runner.step()

        [warning] = [record.getMessage() for record in caplog.records]
        for session_id in slow:
            assert "session {} of".format(session_id) in warning
        assert "session {} of".format(fast) not in warning

    def test_slow_steps_are_reported_at_most_every_interval(
        self, runner, published, monkeypatch, caplog
    ):
        monkeypatch.setattr(runner_module, "SLOW", 0)
        monkeypatch.setattr(runner_module, "SESSION_RENEW_INTERVAL", 0.01)
        store.create_realtime_session(TurnTally, ["1"])

        with caplog.at_level(logging.WARNING, logger=runner_module.__name__):
            runner.step()
            time.sleep(0.05)
            runner.step()

        assert len(published) == 2
        assert len(caplog.records) == 1


class TestDelivery:
    """A runner in a thread, delivering through a web process's listener."""

    @pytest.fixture
    def backend(self):
        backend = sockets.ChatBackend()

        def connect(participant_id, scope=None):
            ws = Mock()
            client = sockets.Client(ws, participant_id=participant_id, scope=scope)
            backend.clients_by_participant.setdefault(participant_id, set()).add(client)
            return ws

        backend.connect = connect
        backend.listener = sockets.DirectChannel(backend, REALTIME_SESSION_CHANNEL)
        return backend

    @pytest.mark.timeout(20)
    def test_views_reach_the_right_pages(self, runner, backend, monkeypatch):
        monkeypatch.setattr(runner_module, "CLAIM_INTERVAL", 0.05)
        current = backend.connect("1", scope="page")
        stale = backend.connect("1", scope="old page")
        unscoped = backend.connect("2")
        elsewhere = backend.connect("2", scope="other page")
        outsider = backend.connect("3")
        pubsub = store.redis_conn.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(REALTIME_SESSION_CHANNEL)
        thread = threading.Thread(target=runner.run)
        thread.start()
        try:
            session_id = store.create_realtime_session(TurnTally, ["1", "2"])
            add(session_id, join(0, "1"))
            add(session_id, join(0, "2", scope=None))
            add(session_id, message(0, "1", "a", number=1))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not acknowledged(current):
                message_ = pubsub.get_message(timeout=0.1)
                if message_ is not None:
                    backend.listener.relay(message_)
                gevent.wait(timeout=1)
        finally:
            runner.stop()
            thread.join(5)
            pubsub.close()

        assert not thread.is_alive()
        assert acknowledged(current)
        for ws in (unscoped, elsewhere):
            assert {frame["session_id"] for frame in frames(ws)} == {session_id}
            assert {frame["view"]["view"]["for"] for frame in frames(ws)} == {"2"}
        for ws in (stale, outsider):
            ws.send.assert_not_called()


def frames(ws):
    sent = [call.args[0] for call in ws.send.mock_calls]
    assert all(each.startswith(REALTIME_SESSION_CHANNEL + ":") for each in sent)
    return [json.loads(each.split(":", 1)[1]) for each in sent]


def acknowledged(ws):
    return any(
        frame["type"] == "realtime_view"
        and frame["view"]["last_processed"] == 1
        and frame["view"]["view"]["for"] == "1"
        for frame in frames(ws)
    )
