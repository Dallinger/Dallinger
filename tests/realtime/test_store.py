import json
import threading
import time

import pytest
from redis import ConnectionError as RedisConnectionError
from redis.client import Pipeline

from dallinger import db
from dallinger.models import RealtimeSession
from dallinger.realtime import store
from dallinger.realtime.core import run_pass
from dallinger.realtime.game import RealtimeGame
from tests.realtime.helpers import CLOCK, Tally, TurnTally, jobs, message

pytestmark = pytest.mark.usefixtures("redis_conn", "realtime_experiment")


def entries_of(session_id):
    return [
        entry_id.decode()
        for entry_id, _ in store.redis_conn.xrange(
            store.session_key(session_id, "entries")
        )
    ]


def records_of(session_id):
    return [
        json.loads(fields[b"record"])
        for _, fields in store.redis_conn.xrange(
            store.session_key(session_id, "records")
        )
    ]


def claim_ttl(session_id):
    return store.redis_conn.pttl(store.session_key(session_id, "claim"))


def claim_token(session_id, runner, ttl):
    claimed = store.claim(session_id, runner, ttl)
    return None if claimed is None else claimed[0]


def expire_claim(session_id):
    store.redis_conn.delete(store.session_key(session_id, "claim"))


def epoch(token):
    return int(token.split(":")[0])


def play_entries(session_id, entry_ids, now=1):
    """Run a pass over a session's entries, as a runner would."""
    items = dict(store.redis_conn.xrange(store.session_key(session_id, "entries")))
    entries = []
    for entry_id in entry_ids:
        entry = store.read_entry(entry_id, items[entry_id.encode()])
        entry["time"] = now
        entries.append(entry)
    saved = store.load_session(session_id)["saved"]
    return run_pass(TurnTally(), saved, entries, now, CLOCK)


def add_message(session_id, participant, payload):
    entry = message(0, participant, payload)
    del entry["time"], entry["received"]
    return store.add_entry(session_id, entry)


class TestSessions:
    def test_a_new_session_is_saved_for_runners(self):
        session_id = store.create_realtime_session(
            TurnTally, [1, " 2 ", "09"], bots=[9]
        )
        other_id = store.create_realtime_session(TurnTally, ["3"])

        assert session_id != other_id
        assert store.running_sessions() == sorted([session_id, other_id])
        loaded = store.load_session(session_id)
        assert loaded["game"] == "tally"
        assert loaded["position"] is None
        assert json.loads(loaded["saved"])["bots"] == ["9"]
        assert store.realtime_state(session_id) == {
            "players": ["1", "2", "9"],
            "log": [],
        }
        assert store.session_members(session_id) == {
            "1": False,
            "2": False,
            "9": True,
        }
        row = db.session.get(RealtimeSession, session_id)
        assert (row.game_type, row.members, row.bots, row.status) == (
            "tally",
            [1, 2, 9],
            [9],
            "running",
        )

    def test_a_session_starts_whatever_the_callers_transaction_does(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        db.session.rollback()

        assert store.running_sessions() == [session_id]
        assert db.session.get(RealtimeSession, session_id).status == "running"

    def test_a_session_redis_cant_take_is_marked_failed(self, monkeypatch):
        def lose_redis(pipe, *args, **kwargs):
            raise RedisConnectionError("lost")

        monkeypatch.setattr(Pipeline, "execute", lose_redis)

        with pytest.raises(RedisConnectionError):
            store.create_realtime_session(TurnTally, ["1"])

        (row,) = db.session.query(RealtimeSession)
        assert row.status == "failed"
        assert "ConnectionError: lost" in row.error

    def test_recreating_the_database_deletes_the_sessions_but_not_the_runners(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        add_message(session_id, "1", "a")
        claim_token(session_id, "runner", 30)
        store.mark_runner_alive("runner", store.server_time(), 30)

        db.init_db(drop_all=True).commit()

        assert store.redis_conn.keys("realtime:*") == [store.RUNNERS.encode()]

    def test_recreating_another_database_keeps_the_sessions(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        other = db.create_db_engine(db.db_url)

        db.init_db(drop_all=True, bind=other)
        other.dispose()

        assert store.running_sessions() == [session_id]

    def test_bots_move_in_the_order_given(self):
        bots = ["7", "3", "5", "2", "6", "4"]
        session_id = store.create_realtime_session(TurnTally, ["1"] + bots, bots=bots)

        assert json.loads(store.load_session(session_id)["saved"])["bots"] == bots

    def test_only_the_experiments_game_types_can_start(self, realtime_experiment):
        class SameChannel(TurnTally):
            pass

        for game_type in (SameChannel, Tally, RealtimeGame, "tally"):
            with pytest.raises(ValueError, match="isn't one of the experiment's"):
                store.create_realtime_session(game_type, ["1"])
        realtime_experiment.channel = "tally"
        with pytest.raises(ValueError, match="is the experiment's channel"):
            store.create_realtime_session(TurnTally, ["1"])
        assert store.running_sessions() == []

    def test_a_session_needs_distinct_participant_ids(self):
        refused = [
            ([], (), "at least one player"),
            ([1, "01"], (), "players repeat"),
            (["1", True], (), "True in the players"),
            (["1", "2"], ["2", 2], "bots repeat"),
            (["1", "2"], [2.0], "2.0 in the bots"),
        ]
        for players, bots, error in refused:
            with pytest.raises(ValueError, match=error):
                store.create_realtime_session(TurnTally, players, bots)
        assert RealtimeSession.query.count() == 0

    def test_an_unknown_session_has_no_state(self):
        with pytest.raises(KeyError) as raised:
            store.realtime_state(1)
        assert raised.value.args == (1,)
        with pytest.raises(KeyError):
            store.end_realtime_session(1, "abandoned")
        assert entries_of(1) == []
        with pytest.raises(KeyError):
            store.realtime_result(1)

    def test_ending_a_session_adds_an_end_entry(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        with pytest.raises(ValueError):
            store.end_realtime_session(session_id, "")
        store.end_realtime_session(session_id, "abandoned")

        (entry_id,) = entries_of(session_id)
        result = play_entries(session_id, [entry_id])
        assert result.ended["reason"] == "abandoned"

    def test_a_stream_keeps_its_newest_entries(self, monkeypatch):
        monkeypatch.setattr(store, "MAX_ENTRIES", 10)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        added = [add_message(session_id, "1", n) for n in range(300)]

        kept = entries_of(session_id)
        assert 10 <= len(kept) < 300
        assert kept == added[-len(kept) :]

    def test_dropped_messages_are_counted(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        assert store.count_dropped(session_id) == 1
        assert store.count_dropped(session_id, 3) == 4


class TestClaims:
    def test_a_held_claim_cannot_be_taken(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        claim_token(session_id, "a", 30)

        assert claim_token(session_id, "b", 30) is None
        assert 29000 < claim_ttl(session_id) <= 30000

    def test_claims_are_released_together_and_lost_ones_named(self):
        held, stolen = [store.create_realtime_session(TurnTally, ["1"]) for _ in "ab"]
        tokens = {
            session_id: claim_token(session_id, "a", 30)
            for session_id in (held, stolen)
        }
        expire_claim(stolen)
        claim_token(stolen, "b", 30)

        assert store.release_session_claims(tokens) == [stolen]
        assert claim_ttl(held) == -2
        assert claim_ttl(stolen) > 29000

    def test_the_epoch_counts_claims(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        first = claim_token(session_id, "a", 30)
        assert claim_token(session_id, "a", 30) is None
        store.release_session_claims({session_id: first})
        second = claim_token(session_id, "a", 30)

        assert epoch(second) == epoch(first) + 1

    def test_only_a_claim_made_after_one_expired_is_a_handover(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        released, counted = store.claim(session_id, "a", 30)
        store.release_session_claims({session_id: released})
        counts = [counted, store.claim(session_id, "b", 30)[1]]
        expire_claim(session_id)
        counts.append(store.claim(session_id, "b", 30)[1])
        expire_claim(session_id)
        counts.append(store.claim(session_id, "c", 30)[1])

        assert counts == [0, 0, 1, 2]

    def test_a_save_starts_the_count_of_handovers_again(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        claim_token(session_id, "a", 30)
        expire_claim(session_id)
        token, counted = store.claim(session_id, "b", 30)
        store.save_passes([(session_id, token, [], play_entries(session_id, []))], 30)
        expire_claim(session_id)

        assert [counted, store.claim(session_id, "c", 30)[1]] == [1, 1]

    def test_claims_are_extended_together_and_lost_ones_named(self):
        kept, stolen = [store.create_realtime_session(TurnTally, ["1"]) for _ in "ab"]
        tokens = {
            session_id: claim_token(session_id, "a", 30)
            for session_id in (kept, stolen)
        }
        expire_claim(stolen)
        claim_token(stolen, "b", 30)

        assert store.extend_session_claims(tokens, 60) == [stolen]
        assert claim_ttl(kept) > 59000
        assert claim_ttl(stolen) <= 30000

    def test_runners_count_until_their_heartbeats_expire_or_they_stop(self):
        clock = store.server_time()
        store.mark_runner_alive("a", clock, 5)
        store.mark_runner_alive("b", clock, 1)
        assert store.mark_runner_alive("c", clock, 5) == ["a", "b", "c"]
        store.remove_runner("c")

        assert store.mark_runner_alive("a", clock + 2, 5) == ["a"]

    def test_the_server_clock_is_the_one_that_stamps_entries(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        before = store.server_time()
        entry_id = add_message(session_id, "1", "a")

        received = store.read_entry(entry_id, {b"entry": b"{}"})["received"]
        assert before - 0.001 <= received <= store.server_time()


class TestSave:
    def test_a_save_writes_the_pass_and_trims_applied_entries(self):
        session_id = store.create_realtime_session(TurnTally, ["1", "2"])
        token = claim_token(session_id, "a", 30)
        applied = [add_message(session_id, "1", "up"), add_message(session_id, "2", 1)]
        unapplied = add_message(session_id, "1", "late")
        result = play_entries(session_id, applied)

        assert store.save_passes([(session_id, token, applied, result)], 60) == []
        loaded = store.load_session(session_id)
        assert loaded["saved"] == result.saved
        assert loaded["position"] == applied[-1]
        assert loaded["applied"] == 2
        assert store.realtime_state(session_id)["log"] == [["1", "up", 1], ["2", 1, 1]]
        assert entries_of(session_id) == [unapplied]
        assert records_of(session_id) == result.records
        assert claim_ttl(session_id) > 59000
        assert store.running_sessions() == [session_id]

    def test_a_pass_without_entries_keeps_the_position(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        token = claim_token(session_id, "a", 30)
        applied = add_message(session_id, "1", "up")
        store.save_passes(
            [(session_id, token, [applied], play_entries(session_id, [applied]))], 30
        )
        result = play_entries(session_id, [], now=2)

        store.save_passes([(session_id, token, [], result)], 30)
        assert store.load_session(session_id)["position"] == applied
        assert store.load_session(session_id)["applied"] == 1
        assert json.loads(store.load_session(session_id)["saved"])["time"] == 2

    def test_a_session_that_ended_leaves_the_running_set_with_its_final_views(self):
        session_id = store.create_realtime_session(TurnTally, ["1", "9"], bots=["9"])
        token = claim_token(session_id, "a", 30)
        store.end_realtime_session(session_id, "abandoned")
        result = play_entries(session_id, entries_of(session_id))

        store.save_passes([(session_id, token, entries_of(session_id), result)], 30)
        assert store.running_sessions() == []
        assert claim_ttl(session_id) == -2
        assert not store.redis_conn.exists(store.session_key(session_id, "unreleased"))
        assert claim_token(session_id, "b", 30) is None
        final = store.redis_conn.get(store.session_key(session_id, "final"))
        assert json.loads(final) == {
            "reason": "abandoned",
            "views": {"1": {"for": "1", "log": []}},
        }
        store.end_realtime_session(session_id, "again")
        assert entries_of(session_id) == []

    def test_a_save_holding_a_stale_epoch_fails(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        stale = claim_token(session_id, "a", 30)
        applied = add_message(session_id, "1", "up")
        result = play_entries(session_id, [applied])
        before = store.load_session(session_id)
        expire_claim(session_id)
        claim_token(session_id, "a", 30)

        assert store.save_passes([(session_id, stale, [applied], result)], 60) == [
            session_id
        ]
        assert store.load_session(session_id) == before
        assert entries_of(session_id) == [applied]
        assert records_of(session_id) == []
        assert claim_ttl(session_id) <= 30000

    def test_a_save_without_a_claim_fails(self):
        (session_id,) = sessions = [store.create_realtime_session(TurnTally, ["1"])]
        ((_, token, applied, result),) = claimed_passes(sessions)
        store.release_session_claims({session_id: token})

        assert store.save_passes([(session_id, None, applied, result)], 60) == [
            session_id
        ]
        assert entries_of(session_id) == applied

    def test_a_claim_stolen_during_the_save_aborts_it(self, monkeypatch):
        """Of three sessions, the second has lost its claim before the save
        and the third loses it just before the transaction runs. Only the
        first is saved.
        """
        kept, stale, stolen = sessions = [
            store.create_realtime_session(TurnTally, [str(n)]) for n in range(3)
        ]
        passes = claimed_passes(sessions)
        before = {session_id: store.load_session(session_id) for session_id in sessions}
        expire_claim(stale)
        thieves = steal_on_first_call(monkeypatch, "multi", stolen)

        assert store.save_passes(passes, 60) == [stale, stolen]
        assert store.load_session(kept)["saved"] == passes[0][3].saved
        for session_id in (stale, stolen):
            assert store.load_session(session_id) == before[session_id]
            assert records_of(session_id) == []
        claim_key = store.session_key(stolen, "claim")
        assert store.redis_conn.get(claim_key).decode() == thieves[0]
        assert claim_ttl(stolen) <= 30000

    def test_only_a_save_that_ends_a_session_queues_its_final_job(self, monkeypatch):
        """Of three sessions, the first and second end, but the second loses
        its claim just before the transaction runs. The third plays on.
        """
        ended, stolen, running = sessions = [
            store.create_realtime_session(TurnTally, [str(n)]) for n in range(3)
        ]
        passes = claimed_passes(sessions, ["stop", "stop", "up"])
        steal_on_first_call(monkeypatch, "multi", stolen)

        assert store.save_passes(passes, 60) == [stolen]
        assert store.running_sessions() == [stolen, running]
        assert jobs("high") == [("dallinger.realtime.jobs.write_ending", (ended,))]

    def test_claims_are_checked_after_they_are_watched(self, monkeypatch):
        (session_id,) = sessions = [store.create_realtime_session(TurnTally, ["1"])]
        passes = claimed_passes(sessions)
        before = store.load_session(session_id)
        steal_on_first_call(monkeypatch, "watch", session_id)

        assert store.save_passes(passes, 60) == [session_id]
        assert store.load_session(session_id) == before


class TestReading:
    def test_one_read_returns_each_sessions_entries_after_its_position(self):
        first, second, quiet = [
            store.create_realtime_session(TurnTally, ["1"]) for _ in range(3)
        ]
        old = add_message(second, "1", "old")
        added = {first: [add_message(first, "1", n) for n in range(2)]}
        added[second] = [add_message(second, "1", "new")]

        read = store.read_entries({first: None, second: old, quiet: None}, 1)

        assert {
            session_id: [entry_id for entry_id, _ in items]
            for session_id, items in read.items()
        } == added
        assert store.read_entry(*read[second][0])["data"] == '"new"'

    def test_a_read_waits_for_the_first_entry(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        adding = threading.Timer(0.2, add_message, (session_id, "1", "late"))
        started = time.monotonic()
        adding.start()

        read = store.read_entries({session_id: None}, 5)

        assert len(read[session_id]) == 1
        assert 0.15 < time.monotonic() - started < 2

    @pytest.mark.timeout(10)
    @pytest.mark.parametrize("timeout", [0.2, 0])
    def test_a_read_with_nothing_new_returns_after_its_timeout(self, timeout):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        started = time.monotonic()

        assert store.read_entries({session_id: None}, timeout) == {}
        assert max(timeout, 0) <= time.monotonic() - started < max(timeout, 0) + 0.5

    def test_a_read_shorter_than_a_millisecond_still_returns(self):
        """Redis takes a block of 0 to mean no timeout at all."""
        session_id = store.create_realtime_session(TurnTally, ["1"])
        reader = threading.Thread(
            target=store.read_entries, args=({session_id: None}, 0.0001), daemon=True
        )

        reader.start()
        reader.join(1)

        assert not reader.is_alive()

    def test_entries_dropped_unapplied_are_counted(self, monkeypatch):
        monkeypatch.setattr(store, "MAX_ENTRIES", 10)
        session_id = store.create_realtime_session(TurnTally, ["1"])
        token = claim_token(session_id, "a", 30)
        applied = [add_message(session_id, "1", n) for n in range(5)]
        result = play_entries(session_id, applied)
        store.save_passes([(session_id, token, applied, result)], 30)
        assert store.lost_entries({session_id: 5}) == {session_id: 0}

        for n in range(300):
            add_message(session_id, "1", n)

        assert store.lost_entries({session_id: 5}) == {
            session_id: 300 - len(entries_of(session_id))
        }

    def test_a_handover_neither_loses_nor_repeats_an_entry(self):
        """Runner a saves one pass, then plays another whose save fails
        because b has taken the session. b starts from a's last save.
        """
        session_id = store.create_realtime_session(TurnTally, ["1"])
        sent = iter(range(100))

        def send(count):
            for _ in range(count):
                add_message(session_id, "1", next(sent))

        def play(token):
            loaded = store.load_session(session_id)
            items = store.read_entries({session_id: loaded["position"]}, 0)
            entries = [store.read_entry(*item) for item in items[session_id]]
            for entry in entries:
                entry["time"] = 1
            result = run_pass(TurnTally(), loaded["saved"], entries, 1, CLOCK)
            applied = [entry_id for entry_id, _ in items[session_id]]
            return store.save_passes([(session_id, token, applied, result)], 30)

        a = claim_token(session_id, "a", 30)
        send(3)
        assert play(a) == []
        send(4)
        expire_claim(session_id)
        b = claim_token(session_id, "b", 30)
        assert play(a) == [session_id]
        send(2)
        assert play(b) == []

        moves = [each[1] for each in store.realtime_state(session_id)["log"]]
        assert moves == list(range(9))
        assert store.load_session(session_id)["applied"] == 9
        assert entries_of(session_id) == []


def claimed_passes(sessions, payloads=None):
    """Claim each session and play a pass over one new message, ``"up"``
    unless ``payloads`` gives each session's.
    """
    passes = []
    for session_id, payload in zip(sessions, payloads or ["up"] * len(sessions)):
        token = claim_token(session_id, "a", 30)
        applied = add_message(session_id, "1", payload)
        passes.append(
            (session_id, token, [applied], play_entries(session_id, [applied]))
        )
    return passes


def steal_on_first_call(monkeypatch, name, session_id):
    """Have another runner take the session's claim when a pipeline's method
    ``name`` is first called, and return a list that gets the thief's token.
    """
    method = getattr(Pipeline, name)
    thieves = []

    def steal_first(pipe, *args):
        if not thieves:
            expire_claim(session_id)
            thieves.append(claim_token(session_id, "b", 30))
        return method(pipe, *args)

    monkeypatch.setattr(Pipeline, name, steal_first)
    return thieves
