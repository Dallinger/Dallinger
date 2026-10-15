import json
import time

import pytest
from redis.client import Pipeline

from dallinger.realtime import store
from dallinger.realtime.core import run_pass
from dallinger.realtime.game import RealtimeGame
from tests.realtime.helpers import CLOCK, TurnTally, message

pytestmark = pytest.mark.usefixtures("redis_conn")


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

    def test_bots_move_in_the_order_given(self):
        bots = ["7", "3", "5", "2", "6", "4"]
        session_id = store.create_realtime_session(TurnTally, ["1"] + bots, bots=bots)

        assert json.loads(store.load_session(session_id)["saved"])["bots"] == bots

    def test_an_invalid_game_type_is_refused(self):
        class Unchanneled(TurnTally):
            channel = None

        with pytest.raises(ValueError, match="channel"):
            store.create_realtime_session(Unchanneled, ["1"])
        with pytest.raises(ValueError):
            store.create_realtime_session(RealtimeGame, ["1"])
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
        assert store.redis_conn.get(store.SESSION_IDS) is None

    def test_an_unknown_session_has_no_state(self):
        with pytest.raises(KeyError) as raised:
            store.realtime_state(1)
        assert raised.value.args == (1,)
        with pytest.raises(KeyError):
            store.end_realtime_session(1, "abandoned")
        assert entries_of(1) == []

    def test_ending_a_session_adds_an_end_entry(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        with pytest.raises(ValueError):
            store.end_realtime_session(session_id, "")
        before = time.time()
        store.end_realtime_session(session_id, "abandoned")

        (entry_id,) = entries_of(session_id)
        result = play_entries(session_id, [entry_id])
        assert result.ended["reason"] == "abandoned"
        fields = dict(store.redis_conn.xrange(store.session_key(session_id, "entries")))
        entry = store.read_entry(entry_id, fields[entry_id.encode()])
        assert before - 0.001 <= entry["received"] <= time.time()

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
        token = store.claim(session_id, "a", 30)

        assert store.claim(session_id, "b", 30) is None
        assert 29000 < claim_ttl(session_id) <= 30000
        assert store.renew(session_id, token, 60)
        assert claim_ttl(session_id) > 59000

    def test_a_renewal_after_another_runners_claim_fails(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        stale = store.claim(session_id, "a", 30)
        expire_claim(session_id)
        token = store.claim(session_id, "b", 30)

        assert not store.renew(session_id, stale, 60)
        assert not store.release(session_id, stale)
        assert claim_ttl(session_id) <= 30000
        assert store.release(session_id, token)
        assert claim_ttl(session_id) == -2

    def test_the_epoch_counts_claims(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        first = store.claim(session_id, "a", 30)
        assert store.claim(session_id, "a", 30) is None
        store.release(session_id, first)
        second = store.claim(session_id, "a", 30)

        assert epoch(second) == epoch(first) + 1

    def test_an_expired_claim_can_be_taken(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        stale = store.claim(session_id, "a", 0.05)
        deadline = time.monotonic() + 2
        while claim_ttl(session_id) != -2 and time.monotonic() < deadline:
            time.sleep(0.01)
        token = store.claim(session_id, "b", 30)

        assert token is not None
        assert epoch(token) > epoch(stale)


class TestSave:
    def test_a_save_writes_the_pass_and_trims_applied_entries(self):
        session_id = store.create_realtime_session(TurnTally, ["1", "2"])
        token = store.claim(session_id, "a", 30)
        applied = [add_message(session_id, "1", "up"), add_message(session_id, "2", 1)]
        unapplied = add_message(session_id, "1", "late")
        result = play_entries(session_id, applied)

        assert store.save_passes([(session_id, token, applied[-1], result)], 60) == []
        loaded = store.load_session(session_id)
        assert loaded["saved"] == result.saved
        assert loaded["position"] == applied[-1]
        assert store.realtime_state(session_id)["log"] == [["1", "up", 1], ["2", 1, 1]]
        assert entries_of(session_id) == [unapplied]
        assert records_of(session_id) == result.records
        assert claim_ttl(session_id) > 59000
        assert store.running_sessions() == [session_id]

    def test_a_pass_without_entries_keeps_the_position(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        token = store.claim(session_id, "a", 30)
        applied = add_message(session_id, "1", "up")
        store.save_passes(
            [(session_id, token, applied, play_entries(session_id, [applied]))], 30
        )
        result = play_entries(session_id, [], now=2)

        store.save_passes([(session_id, token, None, result)], 30)
        assert store.load_session(session_id)["position"] == applied
        assert json.loads(store.load_session(session_id)["saved"])["time"] == 2

    def test_a_session_that_ended_leaves_the_running_set_with_its_final_views(self):
        session_id = store.create_realtime_session(TurnTally, ["1", "9"], bots=["9"])
        token = store.claim(session_id, "a", 30)
        store.end_realtime_session(session_id, "abandoned")
        result = play_entries(session_id, entries_of(session_id))

        store.save_passes([(session_id, token, entries_of(session_id)[0], result)], 30)
        assert store.running_sessions() == []
        final = store.redis_conn.get(store.session_key(session_id, "final"))
        assert json.loads(final) == {
            "reason": "abandoned",
            "views": {"1": {"for": "1", "log": []}},
        }
        store.end_realtime_session(session_id, "again")
        assert entries_of(session_id) == []

    def test_a_save_holding_a_stale_epoch_fails(self):
        session_id = store.create_realtime_session(TurnTally, ["1"])
        stale = store.claim(session_id, "a", 30)
        applied = add_message(session_id, "1", "up")
        result = play_entries(session_id, [applied])
        before = store.load_session(session_id)
        expire_claim(session_id)
        store.claim(session_id, "a", 30)

        assert store.save_passes([(session_id, stale, applied, result)], 60) == [
            session_id
        ]
        assert store.load_session(session_id) == before
        assert entries_of(session_id) == [applied]
        assert records_of(session_id) == []
        assert claim_ttl(session_id) <= 30000

    def test_a_save_without_a_claim_fails(self):
        (session_id,) = sessions = [store.create_realtime_session(TurnTally, ["1"])]
        ((_, token, applied, result),) = claimed_passes(sessions)
        store.release(session_id, token)

        assert store.save_passes([(session_id, None, applied, result)], 60) == [
            session_id
        ]
        assert entries_of(session_id) == [applied]

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

    def test_claims_are_checked_after_they_are_watched(self, monkeypatch):
        (session_id,) = sessions = [store.create_realtime_session(TurnTally, ["1"])]
        passes = claimed_passes(sessions)
        before = store.load_session(session_id)
        steal_on_first_call(monkeypatch, "watch", session_id)

        assert store.save_passes(passes, 60) == [session_id]
        assert store.load_session(session_id) == before


def claimed_passes(sessions):
    """Claim each session and play a pass over one new message."""
    passes = []
    for session_id in sessions:
        token = store.claim(session_id, "a", 30)
        applied = add_message(session_id, "1", "up")
        passes.append((session_id, token, applied, play_entries(session_id, [applied])))
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
            thieves.append(store.claim(session_id, "b", 30))
        return method(pipe, *args)

    monkeypatch.setattr(Pipeline, name, steal_first)
    return thieves
