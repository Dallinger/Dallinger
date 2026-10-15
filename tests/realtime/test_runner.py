import json
import logging
import threading
import time
from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import Mock

import gevent
import pytest
from redis import ConnectionError as RedisConnectionError
from redis import ResponseError
from rq import Queue

from dallinger.db import DIRECT_CHANNEL
from dallinger.experiment_server import sockets
from dallinger.realtime import runner as runner_module
from dallinger.realtime import store
from dallinger.realtime.core import session_time
from dallinger.realtime.game import FAILED, MAX_TIME_LIMIT
from dallinger.realtime.runner import Runner
from dallinger.realtime.time_limit import GIVE_UP_AFTER
from tests.realtime.helpers import Tally, TurnTally, add, handovers, join, message

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


class SlowFailure(TurnTally):
    channel = "slow_failure"

    def apply(self, state, player_id, message, now, sent):
        time.sleep(0.25)
        raise KeyError("no such move")

    def outcome(self, state, reason):
        time.sleep(0.25)
        return super().outcome(state, reason)

    def view(self, state, player_id):
        time.sleep(0.25)
        return super().view(state, player_id)


@pytest.fixture
def runner(realtime_experiment):
    realtime_experiment.realtime_games = [
        TurnTally,
        Ticker,
        Sleeper,
        Paced,
        Crasher,
        SlowFailure,
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


def jobs(queue):
    return [
        (job.func_name, job.args)
        for job in Queue(queue, connection=store.redis_conn).jobs
    ]


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
        token, _ = store.claim(session_id, "earlier", 30, 60)
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
        """The runner's last passes as it stops are capped too."""
        monkeypatch.setattr(runner_module, "MAX_PASS_ENTRIES", 2)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        runner.step()
        for move in "abcde":
            add(session_id, message(0, "1", move))

        runner.step()
        first = moves(session_id)
        runner.let_go()

        assert (first, moves(session_id)) == (["a", "b"], ["a", "b", "c", "d"])

    def test_a_session_that_ends_is_let_go(self, runner, published):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        add(session_id, message(0, "1", "stop"))

        runner.step()

        assert session_id not in runner.sessions
        assert store.running_sessions() == []
        assert jobs("high") == [
            ("dallinger.realtime.jobs.write_records", (session_id,))
        ]

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
    store.claim(session_id, runner, 30, 60)
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
        assert [handovers(each) for each in sessions] == [0] * 10

    def test_only_the_sessions_of_a_runner_that_leaves_change_hands(self):
        sessions = range(1, 301)
        three = {each: runner_module.owner(each, ["a", "b", "c"]) for each in sessions}
        two = {each: runner_module.owner(each, ["a", "b"]) for each in sessions}

        assert all(two[each] == three[each] for each in sessions if three[each] != "c")
        assert all(70 < list(three.values()).count(runner) < 130 for runner in "abc")

    def test_a_stopped_runner_gives_its_sessions_up(
        self, runner, published, monkeypatch
    ):
        """Its last passes renew its heartbeat as they go."""
        monkeypatch.setattr(runner_module, "SESSION_RENEW_INTERVAL", 0)
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

    @pytest.mark.parametrize("released_by", ["balancing", "stopping"])
    def test_a_session_given_up_is_saved_as_it_was_then(
        self, runner, published, released_by
    ):
        """The runner taking it over goes on from then, rather than from the
        last pass. One session ends in that pass.
        """
        sessions = [store.create_realtime_session(TurnTally, ["1"]) for _ in range(8)]
        runner.step()
        time.sleep(0.3)
        if released_by == "balancing":
            given_up = [
                each
                for each in sessions
                if runner_module.owner(each, [runner.name, "other"]) == "other"
            ]
        else:
            given_up = sessions
        ending, messaged, *idle = given_up
        store.end_realtime_session(ending, "abandoned")
        add(messaged, message(0, "1", "a"))

        if released_by == "balancing":
            store.mark_runner_alive("other", store.server_time(), 30)
            runner.next_claim = 0
            runner.step()
            assert sorted(runner.sessions) == sorted(set(sessions) - set(given_up))
        else:
            runner.let_go()

        assert idle
        assert ending not in store.running_sessions()
        assert moves(messaged) == ["a"]
        for session_id in [messaged, *idle]:
            assert holder(session_id) is None
            assert session_time(store.load_session(session_id)["saved"]) >= 0.3

    def test_a_stopping_runner_gives_up_the_sessions_it_has_no_time_to_play(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "SHUTDOWN_PLAY_TIME", 0.1)
        sessions = [store.create_realtime_session(Sleeper, ["1"]) for _ in range(3)]
        runner.step()
        for session_id in sessions:
            add(session_id, message(0, "1", "a"))

        runner.let_go()

        assert [moves(each) for each in sessions] == [["a"], [], []]
        assert [holder(each) for each in sessions] == [None] * 3


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

    @pytest.mark.parametrize("failed_by", ["a message", "handovers"])
    def test_claims_are_extended_before_each_time_limit_of_a_pass(
        self, runner, published, monkeypatch, failed_by
    ):
        """Without that, the slow failing session's pass outlasts the other
        session's claim. A session that changed runners too often fails
        before applying a message, but its outcome and final views are slow.
        """
        monkeypatch.setattr(runner_module, "CLAIM_TTL", 0.4)
        monkeypatch.setattr(runner_module, "SESSION_RENEW_INTERVAL", 0.05)
        failing = store.create_realtime_session(SlowFailure, ["1"])
        idle = store.create_realtime_session(TurnTally, ["1"])
        if failed_by == "handovers":
            for number in range(runner_module.MAX_HANDOVERS):
                handover(failing, "stopped {}".format(number))
        else:
            runner.step()
            add(failing, message(0, "1", "a"))

        runner.step()

        assert store.running_sessions() == [idle]
        assert list(runner.sessions) == [idle]

    @pytest.mark.parametrize("error", [RedisConnectionError, ResponseError])
    def test_a_redis_error_between_time_limits_leaves_the_session_as_it_was(
        self, runner, published, monkeypatch, error
    ):
        monkeypatch.setattr(runner_module, "SESSION_RENEW_INTERVAL", 0)
        session_id = store.create_realtime_session(Crasher, ["1"])
        runner.step()
        add(session_id, message(0, "1", "crash"))
        extend = store.extend_session_claims
        calls = []

        def failing_after_the_first(tokens, ttl):
            calls.append(tokens)
            if len(calls) > 1:
                raise error("gone")
            return extend(tokens, ttl)

        monkeypatch.setattr(store, "extend_session_claims", failing_after_the_first)

        with pytest.raises(error):
            runner.step()

        assert store.running_sessions() == [session_id]

    def test_a_lost_claim_sends_no_views_and_drops_the_session(
        self, runner, published, monkeypatch
    ):
        kept, stolen = [store.create_realtime_session(TurnTally, ["1"]) for _ in "ab"]
        runner.step()
        for session_id in (kept, stolen):
            add(session_id, join(0, "1"))
        store.redis_conn.delete(store.session_key(stolen, "claim"))
        store.claim(stolen, "another runner", 30, 60)

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
        assert (
            "changed runners {} times in 60 seconds".format(handovers) in end["error"]
        )
        assert (end["outcome"] is not None) == outcome

    def test_only_recent_handovers_count(self, runner, published, monkeypatch):
        monkeypatch.setattr(runner_module, "HANDOVER_WINDOW", 0.2)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        for number in range(runner_module.MAX_HANDOVERS):
            handover(session_id, "stopped {}".format(number))
        time.sleep(0.3)

        runner.step()

        assert store.running_sessions() == [session_id]
        assert list(runner.sessions) == [session_id]

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


class TestLostRedis:
    def test_a_runner_plays_on_from_what_redis_saved_once_it_is_back(
        self, runner, published, monkeypatch, caplog
    ):
        """Redis goes away after a save, before its views are sent, and stays
        away for two more tries.
        """
        monkeypatch.setattr(runner_module, "CLAIM_TTL", 0.2)
        monkeypatch.setattr(runner_module, "REDIS_RETRY_INTERVAL", 0.05)
        outage = []
        failed_at = []
        publish = runner_module.publish_views
        server_time = store.server_time

        def failing(call):
            def wrapped(*args):
                if outage:
                    outage.pop()
                    failed_at.append(time.monotonic())
                    raise RedisConnectionError("gone")
                return call(*args)

            return wrapped

        monkeypatch.setattr(runner_module, "publish_views", failing(publish))
        monkeypatch.setattr(store, "server_time", failing(server_time))
        session_id = store.create_realtime_session(TurnTally, ["1"])
        add(session_id, message(0, "1", "a"))
        runner.step()
        outage.extend([True] * 3)
        add(session_id, message(0, "1", "b"))
        thread = threading.Thread(target=runner.run)

        with caplog.at_level(logging.INFO, logger=runner_module.__name__):
            thread.start()
            deadline = time.monotonic() + 5
            while outage and time.monotonic() < deadline:
                time.sleep(0.01)
            add(session_id, message(0, "1", "c"))
            while moves(session_id) != ["a", "b", "c"] and time.monotonic() < deadline:
                time.sleep(0.01)
            runner.stop()
            thread.join(5)

        assert not thread.is_alive()
        assert moves(session_id) == ["a", "b", "c"]
        assert any(session_id in batch for batch in published[1:])
        assert all(later - earlier >= 0.05 for earlier, later in pairwise(failed_at))
        assert [
            record.getMessage().split(":")[0]
            for record in caplog.records
            if "redis" in record.getMessage()
        ] == [
            "Runner test-runner lost its connection to redis, and stops playing "
            "its sessions until it's back",
            "Runner test-runner reached redis again.",
        ]

    def test_a_runner_keeps_the_claims_it_still_holds_after_an_outage(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "REDIS_RETRY_INTERVAL", 0)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        runner.step()
        token = runner.sessions[session_id].token
        runner.lose_redis(RedisConnectionError("gone"))

        runner.step()

        assert runner.sessions[session_id].token == token
        assert runner.held == {}
        assert handovers(session_id) == 0

    def test_a_claim_made_just_before_an_outage_is_resumed(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "REDIS_RETRY_INTERVAL", 0)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        load = store.load_session
        monkeypatch.setattr(
            store, "load_session", Mock(side_effect=RedisConnectionError)
        )
        with pytest.raises(RedisConnectionError):
            runner.step()
        runner.lose_redis(RedisConnectionError("gone"))
        monkeypatch.setattr(store, "load_session", load)

        runner.step()

        assert list(runner.sessions) == [session_id]
        assert handovers(session_id) == 0

    def test_a_resumed_session_still_fails_for_changing_runners_too_often(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "REDIS_RETRY_INTERVAL", 0)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        for number in range(runner_module.MAX_HANDOVERS):
            handover(session_id, "stopped {}".format(number))
        load = store.load_session
        monkeypatch.setattr(
            store, "load_session", Mock(side_effect=RedisConnectionError)
        )
        with pytest.raises(RedisConnectionError):
            runner.step()
        runner.lose_redis(RedisConnectionError("gone"))
        monkeypatch.setattr(store, "load_session", load)

        runner.step()

        assert store.running_sessions() == []

    def test_a_release_cut_short_by_an_outage_is_finished_after_it(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "REDIS_RETRY_INTERVAL", 0)
        sessions = [store.create_realtime_session(TurnTally, ["1"]) for _ in range(10)]
        runner.step()
        store.mark_runner_alive("other", store.server_time(), 30)
        runner.next_claim = 0
        release = store.release_session_claims
        monkeypatch.setattr(
            store, "release_session_claims", Mock(side_effect=RedisConnectionError)
        )
        with pytest.raises(RedisConnectionError):
            runner.step()
        runner.lose_redis(RedisConnectionError("gone"))
        monkeypatch.setattr(store, "release_session_claims", release)

        runner.step()

        others = [
            each
            for each in sessions
            if runner_module.owner(each, [runner.name, "other"]) == "other"
        ]
        assert others
        assert [holder(each) for each in others] == [None] * len(others)

    def test_runners_back_from_a_long_outage_take_back_their_own_sessions(
        self, runner, published, monkeypatch
    ):
        """The outage outlasts every claim and heartbeat."""
        monkeypatch.setattr(runner_module, "REDIS_RETRY_INTERVAL", 0)
        monkeypatch.setattr(runner_module, "HEARTBEAT_TTL", 0.3)
        monkeypatch.setattr(runner_module, "CLAIM_INTERVAL", 0.05)
        other = Runner(store.experiment_games(), name="other")
        sessions = [store.create_realtime_session(TurnTally, ["1"]) for _ in range(10)]
        store.mark_runner_alive(other.name, store.server_time(), 30)
        runner.step()
        other.step()
        assert runner.sessions and other.sessions
        for session_id in sessions:
            store.redis_conn.delete(store.session_key(session_id, "claim"))
        store.redis_conn.delete(store.RUNNERS)
        runner.lose_redis(RedisConnectionError("gone"))
        other.lose_redis(RedisConnectionError("gone"))

        runner.step()
        claimed_first = dict(runner.sessions)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            other.step()
            runner.step()

        assert claimed_first == {}
        names = [runner.name, other.name]
        assert [holder(each) for each in sessions] == [
            runner_module.owner(each, names) for each in sessions
        ]
        assert [handovers(each) for each in sessions] == [0] * 10

    def test_a_runner_stopped_during_an_outage_gives_up_the_claims_it_held(
        self, runner, published, monkeypatch
    ):
        monkeypatch.setattr(runner_module, "REDIS_RETRY_INTERVAL", 0)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        runner.step()
        runner.lose_redis(RedisConnectionError("gone"))
        runner.stop()

        runner.run()

        assert holder(session_id) is None

    def test_a_runner_that_cannot_reach_redis_as_it_stops_says_so(
        self, runner, published, monkeypatch, caplog
    ):
        store.create_realtime_session(TurnTally, ["1"])
        runner.step()

        def unreachable(tokens):
            raise RedisConnectionError("gone")

        monkeypatch.setattr(store, "release_session_claims", unreachable)
        runner.stop()

        with caplog.at_level(logging.WARNING, logger=runner_module.__name__):
            runner.run()

        assert "couldn't give up its sessions" in caplog.text


def test_a_time_limit_ends_before_the_claims_it_started_with_expire():
    """Game code can run past its time limit until the runner gives up on
    it, and the runner extends its claims each time the limit starts again,
    so each claim has at least this long left.
    """
    claim_left = runner_module.CLAIM_TTL - runner_module.SESSION_RENEW_INTERVAL
    assert GIVE_UP_AFTER * MAX_TIME_LIMIT < claim_left


def test_a_stopping_runner_is_done_before_docker_kills_it():
    """A pass that starts just before the shutdown limit can still run its
    three time limits.
    """
    last_pass = 3 * GIVE_UP_AFTER * MAX_TIME_LIMIT
    assert runner_module.SHUTDOWN_PLAY_TIME + last_pass < 10


def test_a_runner_refuses_redis_before_7(runner, monkeypatch):
    monkeypatch.setattr(
        store.redis_conn, "info", lambda section: {"redis_version": "6.0.16"}
    )

    runner.stop()

    with pytest.raises(RuntimeError, match="needs redis 7.0 or later"):
        runner.run()


class TestSlowPasses:
    @pytest.mark.parametrize(
        "game_type, slow, logged",
        [(TurnTally, 0, True), (TurnTally, 30, False), (Paced, 30, True)],
    )
    def test_a_pass_longer_than_a_tick_names_its_slowest_sessions(
        self, runner, published, monkeypatch, caplog, game_type, slow, logged
    ):
        monkeypatch.setattr(runner_module, "SLOW", slow)
        session_id = store.create_realtime_session(game_type, ["1"])
        add(session_id, message(0, "1", "a"))

        with caplog.at_level(logging.WARNING, logger=runner_module.__name__):
            runner.step()

        warnings = [record.getMessage() for record in caplog.records]
        if logged:
            [warning] = warnings
            name = "session {} of {}".format(session_id, game_type.channel)
            assert name in warning
        else:
            assert warnings == []

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
        backend.listener = sockets.DirectChannel(backend)
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
        pubsub.subscribe(DIRECT_CHANNEL)
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
    assert all(each.startswith(DIRECT_CHANNEL + ":") for each in sent)
    return [json.loads(each.split(":", 1)[1]) for each in sent]


def acknowledged(ws):
    return any(
        frame["type"] == "realtime_view"
        and frame["view"]["last_processed"] == 1
        and frame["view"]["view"]["for"] == "1"
        for frame in frames(ws)
    )
