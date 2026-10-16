import json
import random

import pytest

from dallinger.realtime import RealtimeGame, Sent, core
from dallinger.realtime.core import new_session, parse_message, run_pass
from dallinger.realtime.game import FAILED, FINISHED, MAX_DURATION
from tests.realtime.helpers import (
    CLOCK,
    Restless,
    Tally,
    TurnTally,
    error,
    join,
    leave,
    log,
    message,
    play,
    session,
    socket_entry,
    started,
    views_by_page,
    with_deadline,
)


def test_a_game_with_only_the_required_methods_plays_on_the_defaults():
    class Minimal(RealtimeGame):
        channel = "minimal"
        tick_rate = 4

        def initial_state(self, players):
            return {"moves": []}

        def apply(self, state, player_id, message, now, sent):
            state["moves"].append(message)

        def view(self, state, player_id):
            return state

    game = Minimal()
    entries = [
        join(0, "1"),
        message(0.1, "1", "a"),
        leave(0.3, "1"),
        join(0.4, "1"),
        {"type": "end", "time": 0.6, "reason": "stopped"},
    ]

    result = play(game, new_session(game, ["1", "9"], bots=["9"]), entries, 0.6)

    assert result.ended["outcome"] is None
    assert result.ended["views"] == {"1": {"moves": ["a"]}}
    assert result.records[-1]["state"] == {"moves": ["a"]}


class TestNewSession:
    def test_members_are_strings_and_the_first_tick_is_one_interval_in(self):
        loaded = json.loads(new_session(Tally(), [1, 2], bots=[2]))

        assert loaded["state"] == {"players": ["1", "2"], "log": []}
        assert loaded["members"] == ["1", "2"]
        assert loaded["bots"] == ["2"]
        assert loaded["bot_messages"] == {"2": 0}
        assert loaded["next_tick"] == 0.25

    def test_bots_must_be_members(self):
        with pytest.raises(ValueError, match="Every bot must be a member"):
            new_session(Tally(), ["1"], bots=["2"])


class TestParseMessage:
    @pytest.mark.parametrize(
        "data, payload, sent",
        [
            (
                '{"envelope": {"number": 3, "browser_time": 5.5, "view_time": 2},'
                ' "payload": {"move": "left"}}',
                {"move": "left"},
                Sent(3, 5.5, 2),
            ),
            ('{"move": "left"}', {"move": "left"}, Sent()),
            ("left", "left", Sent()),
            ("NaN", "NaN", Sent()),
            ("[1e999]", "[1e999]", Sent()),
            (
                '{"envelope": {}, "payload": 1, "extra": 2}',
                {"envelope": {}, "payload": 1, "extra": 2},
                Sent(),
            ),
            ('{"envelope": 7, "payload": 1}', {"envelope": 7, "payload": 1}, Sent()),
            (
                '{"envelope": {"number": true, "browser_time": "5",'
                ' "view_time": "5"}, "payload": 1}',
                1,
                Sent(),
            ),
            ('{"envelope": {"browser_time": false}, "payload": 1}', 1, Sent()),
            ('{"envelope": {"number": 2147483647}, "payload": 1}', 1, Sent(2**31 - 1)),
            ('{"envelope": {"number": 2147483648}, "payload": 1}', 1, Sent()),
            ('{"envelope": {"number": -1}, "payload": 1}', 1, Sent()),
            ('{"envelope": {"number": 0}, "payload": 1}', 1, Sent(0)),
            (
                '{"envelope": {"browser_time": 1' + "0" * 400 + '}, "payload": 1}',
                1,
                Sent(),
            ),
        ],
    )
    def test_parse(self, data, payload, sent):
        assert parse_message(data) == (payload, sent)


class TestTimeOrder:
    def test_messages_are_applied_around_ticks_in_time_order(self):
        game = Tally()

        result = play(
            game,
            started(game),
            [message(0.2, "1", "a"), message(0.25, "2", "b"), message(0.3, "1", "c")],
            0.3,
        )

        assert log(result)[2:] == [
            ["1", "a", 0.2],
            ["2", "b", 0.25],
            ["tick", 0.25],
            ["1", "c", 0.3],
        ]

    def test_every_missed_tick_runs_at_its_own_time(self):
        game = Tally()

        result = play(game, started(game), [], 0.8)

        assert log(result)[2:] == [["tick", 0.25], ["tick", 0.5], ["tick", 0.75]]
        assert session(result)["next_tick"] == 1.0
        assert session(result)["time"] == 0.8

    def test_entry_times_are_kept_within_the_pass(self):
        game = TurnTally()
        saved = play(game, started(game), [], 1).saved

        result = play(
            game, saved, [message(0.5, "1", "early"), message(9, "1", "late")], 2
        )

        assert log(result)[2:] == [["1", "early", 1], ["1", "late", 2]]

    def test_the_session_clock_never_goes_back(self):
        game = TurnTally()
        saved = play(game, started(game), [], 2).saved

        result = play(game, saved, [message(1, "1", "a")], 1)

        assert log(result)[-1] == ["1", "a", 2]
        assert session(result)["time"] == 2

    def test_a_deadline_ticks_once_at_its_own_time(self):
        game = TurnTally()

        first = play(game, with_deadline(started(game), 1.5), [], 2)
        second = play(game, first.saved, [], 3)

        assert log(first)[2:] == [["tick", 1.5]]
        assert log(second) == log(first)

    @pytest.mark.parametrize(
        "game_type, deadline, max_duration, next_due",
        [
            (Tally, None, None, 0.5),
            (Tally, 0.4, None, 0.4),
            (Tally, None, 0.45, 0.45),
            (TurnTally, None, None, None),
            (TurnTally, 2, 9, 2),
        ],
    )
    def test_a_pass_says_when_the_next_tick_is_due(
        self, game_type, deadline, max_duration, next_due
    ):
        game = type("Timed", (game_type,), {"max_duration": max_duration})()
        first = play(game, with_deadline(started(game), 0.25), [], 0.25)

        result = play(game, with_deadline(first.saved, deadline), [], 0.3)

        assert result.next_due == next_due

    def test_an_ended_session_has_nothing_due(self):
        game = Tally()

        result = play(game, started(game), [message(0.1, "1", "stop")], 0.1)

        assert result.next_due is None

    def test_a_deadline_in_the_past_ticks_at_once(self):
        game = TurnTally()
        saved = play(game, started(game), [], 4).saved

        result = play(game, with_deadline(saved, 1.5), [], 5)

        assert log(result)[2:] == [["tick", 4]]


class TestViews:
    def test_a_pass_with_a_tick_sends_each_page_one_tick_view(self):
        game = Tally()

        result = play(game, started(game), [message(0.2, "1", "a", number=1)], 0.3)

        views = views_by_page(result)
        assert len(result.views) == 2
        assert views["1", "page"]["kind"] == "tick"
        assert views["1", "page"]["last_processed"] == 1
        assert views["2", "page"]["last_processed"] is None
        assert views["2", "page"]["view"] == {"for": "2", "log": log(result)}

    def test_a_message_view_goes_to_the_sender_only(self):
        game = Tally()

        result = play(game, started(game), [message(0.1, "1", "a", number=1)], 0.2)

        assert result.views == [
            {
                "participant": "1",
                "scope": "page",
                "view": {
                    "kind": "message",
                    "number": 2,
                    "time": 0.2,
                    "clock": CLOCK,
                    "last_processed": 1,
                    "rejected": [],
                    "ended": None,
                    "view": {"for": "1", "log": log(result)},
                },
            }
        ]

    def test_message_views_can_be_turned_off(self):
        game = type("Quiet", (Tally,), {"send_views_on_messages": False})()

        first = play(game, started(game), [message(0.1, "1", "a", number=1)], 0.2)
        second = play(game, first.saved, [], 0.3)

        assert first.views == []
        assert session(first)["view_number"] == 1
        assert views_by_page(second)["1", "page"]["last_processed"] == 1

    def test_without_ticks_a_change_sends_everyone_a_view(self):
        game = TurnTally()

        changed = play(game, started(game), [message(1, "1", "a", number=1)], 1)
        rejected = play(game, changed.saved, [message(2, "1", "bad", number=2)], 2)

        assert set(views_by_page(changed)) == {("1", "page"), ("2", "page")}
        assert set(views_by_page(rejected)) == {("1", "page")}

    def test_without_ticks_the_sender_gets_a_view_even_with_message_views_off(self):
        game = type("Quiet", (TurnTally,), {"send_views_on_messages": False})()

        result = play(game, started(game), [message(1, "1", "bad", number=1)], 1)

        assert set(views_by_page(result)) == {("1", "page")}

    def test_a_join_gets_its_page_a_view(self):
        game = Tally()

        result = play(game, started(game), [join(0.1, "1", scope="tab")], 0.2)

        assert set(views_by_page(result)) == {("1", "tab")}


class TestAcknowledgements:
    def test_the_last_number_is_kept_rather_than_the_highest(self):
        game = TurnTally()

        result = play(
            game,
            started(game),
            [message(1, "1", "a", number=5), message(2, "1", "b", number=1)],
            2,
        )

        assert views_by_page(result)["1", "page"]["last_processed"] == 1

    def test_numbers_are_kept_per_page(self):
        game = TurnTally()

        result = play(
            game,
            started(game),
            [
                join(1, "1", scope="tab"),
                message(1, "1", "a", number=4, scope="tab"),
                message(1, "1", "b", number=9),
            ],
            1,
        )

        views = views_by_page(result)
        assert views["1", "tab"]["last_processed"] == 4
        assert views["1", "page"]["last_processed"] == 9

    def test_a_frame_without_an_envelope_is_applied_but_not_acknowledged(self):
        game = TurnTally()

        first = play(game, started(game), [message(1, "1", "a", number=3)], 1)
        second = play(game, first.saved, [message(2, "1", "bad")], 2)
        third = play(game, second.saved, [message(3, "1", "b")], 3)

        assert views_by_page(second)["1", "page"]["rejected"] == []
        assert views_by_page(third)["1", "page"]["last_processed"] == 3
        assert log(third)[-1] == ["1", "b", 3]
        assert third.records[0]["number"] is None

    def test_a_rejection_goes_out_with_the_next_view_only(self):
        game = Tally()

        first = play(game, started(game), [message(0.1, "1", "bad", number=1)], 0.2)
        second = play(game, first.saved, [], 0.3)

        assert views_by_page(first)["1", "page"]["rejected"] == [
            {"number": 1, "reason": {"code": "bad"}}
        ]
        assert views_by_page(first)["1", "page"]["last_processed"] == 1
        assert views_by_page(second)["1", "page"]["rejected"] == []
        assert first.records[0]["status"] == "rejected"
        assert first.records[0]["reason"] == {"code": "bad"}


class TestJoinAndLeave:
    def test_on_join_and_on_leave_follow_a_players_first_and_last_socket(self):
        game = TurnTally()

        result = play(
            game,
            new_session(game, ["1", "2"]),
            [
                join(1, "1", socket="a"),
                join(2, "1", socket="b"),
                join(2, "1", socket="b"),
                join(3, "1", scope="tab", socket="c"),
                leave(4, "1", socket="a"),
                leave(4, "1", socket="a"),
                leave(5, "1", scope="tab", socket="c"),
                leave(5, "1", socket="c"),
                leave(6, "1", socket="b"),
                leave(7, "1", socket="b"),
                join(8, "1", socket="d"),
            ],
            8,
        )

        assert log(result) == [["join", "1", 1], ["leave", "1", 6], ["join", "1", 8]]
        assert session(result)["pages"] == [
            {
                "participant": "1",
                "scope": "page",
                "sockets": ["d"],
                "last_processed": None,
                "rejected": [],
            }
        ]

    def test_a_page_that_left_gets_no_view(self):
        game = Tally()

        result = play(
            game,
            started(game),
            [join(0.1, "1", scope="tab"), leave(0.1, "1", scope="tab")],
            0.2,
        )

        assert result.views == []


def test_an_unknown_entry_fails_the_session():
    game = TurnTally()

    result = play(game, started(game), [{"type": "spin", "time": 1}], 1)

    assert "Unknown entry type 'spin'" in error(result)


@pytest.mark.parametrize("reason", ["", 3])
def test_an_end_entry_without_a_reason_fails_the_session(reason):
    game = TurnTally()
    entry = {"type": "end", "time": 1, "reason": reason}

    result = play(game, started(game), [entry], 1)

    assert "reason must be a non-empty string" in error(result)


class TestEndings:
    def test_a_finished_game_ends_and_drops_later_entries(self):
        game = TurnTally()

        result = play(
            game,
            new_session(game, ["1", "2"]),
            [
                join(0, "1"),
                message(1, "1", "stop", number=1),
                message(2, "1", "after", number=2),
            ],
            3,
        )

        assert log(result) == [["join", "1", 0], ["1", "stop", 1]]
        assert result.ended == {
            "time": 1,
            "reason": FINISHED,
            "outcome": {"reason": FINISHED, "moves": 2},
            "views": {
                "1": {"for": "1", "log": log(result)},
                "2": {"for": "2", "log": log(result)},
            },
            "error": None,
        }
        assert session(result)["ended"] == result.ended
        assert result.records[-1] == {
            "sequence": 2,
            "type": "end",
            "time": 1,
            "reason": FINISHED,
            "outcome": {"reason": FINISHED, "moves": 2},
            "state": session(result)["state"],
            "error": None,
        }
        [final] = result.views
        assert final["view"]["ended"] == FINISHED
        assert final["view"]["last_processed"] == 1

    def test_a_deadline_tick_can_end_the_game(self):
        class Timer(TurnTally):
            def tick(self, state, now):
                state["log"].append(["timer", "stop"])

        game = Timer()

        result = play(
            game, with_deadline(started(game), 1.5), [message(1.6, "1", "late")], 2
        )

        assert result.ended["time"] == 1.5
        assert log(result)[-1] == ["timer", "stop"]

    def test_max_duration_ends_the_game_on_the_session_clock(self):
        game = type("Timed", (Tally,), {"max_duration": 0.5})()

        result = play(
            game, started(game), [message(0.4, "1", "a"), message(0.5, "1", "b")], 0.9
        )

        assert log(result)[2:] == [["tick", 0.25], ["1", "a", 0.4]]
        assert result.ended["reason"] == MAX_DURATION
        assert result.ended["time"] == 0.5
        assert session(result)["time"] == 0.9
        assert result.views[0]["view"]["time"] == 0.9

    def test_max_duration_ends_a_pass_with_nothing_to_do(self):
        game = type("Timed", (TurnTally,), {"max_duration": 2})()

        assert play(game, started(game), [], 2).ended["reason"] == MAX_DURATION

    def test_an_end_entry_passes_its_reason_to_outcome(self):
        game = TurnTally()

        result = play(
            game,
            started(game),
            [{"type": "end", "time": 1, "reason": "abandoned"}, message(1, "1", "a")],
            1,
        )

        assert result.ended["outcome"] == {"reason": "abandoned", "moves": 2}
        assert len(result.views) == 2

    def test_an_ended_session_takes_no_more_entries(self):
        game = TurnTally()
        ended = play(game, started(game), [message(1, "1", "stop")], 1).saved

        result = play(game, ended, [message(2, "1", "a")], 2)

        assert result.saved == ended
        assert (result.views, result.records, result.ended) == ([], [], None)
        assert result.next_due is None


class Bot(Tally):
    def bot(self, view, player_id, now):
        view["log"].append("changed by the bot")
        return {"bot": player_id}


class TurnBot(TurnTally):
    """Answers each move someone else makes."""

    def bot(self, view, player_id, now):
        moves = [each for each in view["log"] if each[0] not in ("join", "leave")]
        if moves and moves[-1][0] != player_id:
            return {"bot": player_id}
        return None


class TestBots:
    def test_a_bot_plays_on_each_tick_with_a_copy_of_its_view(self):
        game = Bot()

        saved = started(game, members=["1", "9"], bots=["9"])

        result = play(game, saved, [message(0.1, "1", "a")], 0.5)

        assert log(result)[1:] == [
            ["1", "a", 0.1],
            ["tick", 0.25],
            ["9", {"bot": "9"}, 0.25],
            ["tick", 0.5],
            ["9", {"bot": "9"}, 0.5],
        ]
        assert result.records[2] == {
            "sequence": 3,
            "type": "message",
            "time": 0.5,
            "participant": "9",
            "scope": None,
            "payload": {"bot": "9"},
            "number": 2,
            "browser_time": CLOCK,
            "view_time": 0.5,
            "received": CLOCK,
            "status": "accepted",
            "reason": None,
        }
        assert set(views_by_page(result)) == {("1", "page")}

    def test_without_ticks_bots_move_at_the_start_and_answer_each_other(self):
        class Rally(TurnBot):
            def bot(self, view, player_id, now):
                moves = view["log"]
                if len(moves) < 4 and (not moves or moves[-1][0] != player_id):
                    return {"bot": player_id}
                return None

        game = Rally()

        result = play(game, new_session(game, ["8", "9"], bots=["8", "9"]), [], 1)

        assert log(result) == [
            ["8", {"bot": "8"}, 0],
            ["9", {"bot": "9"}, 0],
            ["8", {"bot": "8"}, 0],
            ["9", {"bot": "9"}, 0],
        ]

    def test_without_ticks_bots_answer_joins_and_leaves(self):
        game = Restless()
        saved = started(game, members=["1", "9"], bots=["9"])

        result = play(game, saved, [leave(1, "1"), join(2, "1")], 2)

        assert log(result)[2:] == [
            ["leave", "1", 1],
            ["9", "move", 1],
            ["join", "1", 2],
            ["9", "move", 2],
        ]

    def test_bots_move_at_the_start_of_the_first_pass_only(self):
        game = Restless()
        first = play(game, new_session(game, ["9"], bots=["9"]), [], 5)

        second = play(game, first.saved, [], 6)

        assert log(first) == log(second) == [["9", "move", 0]]

    def test_a_rejected_bot_move_is_not_tried_again(self):
        class Stubborn(TurnTally):
            def bot(self, view, player_id, now):
                return "bad"

        game = Stubborn()
        saved = started(game, members=["1", "9"], bots=["9"])

        result = play(game, saved, [message(1, "1", "a")], 1)

        assert [(each["participant"], each["status"]) for each in result.records] == [
            ("1", "accepted"),
            ("9", "rejected"),
        ]

    def test_bots_that_never_stop_fail_the_session(self, monkeypatch):
        monkeypatch.setattr(core, "MAX_BOT_ROUNDS", 5)
        game = TurnBot()
        saved = started(game, members=["1", "8", "9"], bots=["8", "9"])

        result = play(game, saved, [message(1, "1", "a")], 1)

        assert "TurnBot's bots were still moving after 5 rounds" in error(result)

    def test_a_bot_does_not_play_once_the_game_is_over(self):
        game = TurnBot()
        saved = started(game, members=["1", "9"], bots=["9"])

        result = play(game, saved, [message(1, "1", "stop")], 1)

        assert log(result)[1:] == [["1", "stop", 1]]
        assert set(result.ended["views"]) == {"1"}


class TestRecords:
    def test_effects_follow_their_message_unless_it_is_rejected(self):
        game = TurnTally()

        result = play(
            game,
            started(game),
            [message(1, "1", "effect"), message(2, "2", "effect and reject")],
            2,
        )

        assert [(each["type"], each["sequence"]) for each in result.records] == [
            ("message", 1),
            ("effect", 2),
            ("message", 3),
        ]
        assert result.records[1] == {
            "sequence": 2,
            "type": "effect",
            "time": 1,
            "name": "scored",
            "payload": {"by": "1"},
        }

    def test_an_effect_keeps_its_payload_as_queued(self):
        class Echo(TurnTally):
            def apply(self, state, player_id, message, now, sent):
                self.queue_effect("logged", state["log"])
                state["log"].append("after")

        game = Echo()
        result = play(game, started(game), [message(1, "1", "a")], 1)

        assert result.records[1]["payload"] == log(result)[:-1]

    def test_tick_on_join_and_on_leave_can_queue_effects(self):
        class Noisy(TurnTally):
            def tick(self, state, now):
                self.queue_effect("tick", now)

            def on_join(self, state, player_id, now):
                self.queue_effect("join", now)

            def on_leave(self, state, player_id, now):
                self.queue_effect("leave", now)

        game = Noisy()
        saved = with_deadline(new_session(game, ["1"]), 2)

        result = play(game, saved, [join(1, "1"), leave(3, "1")], 3)

        assert [(each["name"], each["payload"]) for each in result.records] == [
            ("join", 1),
            ("tick", 2),
            ("leave", 3),
        ]

    @pytest.mark.parametrize(
        "method",
        ["next_deadline", "view", "is_over", "outcome", "bot", "save_message"],
    )
    def test_only_methods_that_change_the_state_can_queue_effects(self, method):
        def queueing(self, *args):
            self.queue_effect("queried", {})

        game = type("Querying", (TurnTally,), {method: queueing})()
        saved = new_session(game, ["1", "9"], bots=["9"])

        result = play(game, saved, [join(1, "1"), message(1, "1", "stop")], 1)

        assert "queue_effect only works in apply, tick" in error(result)

    def test_a_checkpoint_is_recorded_every_interval(self):
        class Often(TurnTally):
            checkpoint_interval = 2

        game = Often()

        early = play(game, started(game), [], 1)
        first = play(game, early.saved, [], 3)
        soon_after = play(game, first.saved, [], 4)
        second = play(game, soon_after.saved, [], 5)

        assert early.records == []
        assert first.records == [
            {
                "sequence": 1,
                "type": "checkpoint",
                "time": 3,
                "state": session(first)["state"],
            }
        ]
        assert soon_after.records == []
        assert [(each["type"], each["time"]) for each in second.records] == [
            ("checkpoint", 5)
        ]

    def test_checkpoints_can_be_turned_off(self):
        class Unchecked(TurnTally):
            checkpoint_interval = None

        game = Unchecked()

        result = play(game, started(game), [], 1000)

        assert result.records == []

    def test_save_message_decides_which_messages_are_saved(self):
        class Picky(TurnTally):
            def save_message(self, state, player_id, message, rejection):
                if rejection is not None:
                    return rejection.reason == {"code": "bad"}
                return state["log"][-1][1] in ("keep", "stop")

        game = Picky()
        entries = [
            message(1, "1", "a"),
            message(2, "1", "keep"),
            message(3, "2", "effect", number=1),
            message(4, "2", "bad", number=2),
            message(5, "2", "effect and reject", number=3),
            message(6, "1", "stop"),
        ]

        result = play(game, started(game), entries, 6)

        assert [
            (each["sequence"], each["type"], each["time"], each.get("status"))
            for each in result.records
        ] == [
            (1, "message", 2, "accepted"),
            (2, "effect", 3, None),
            (3, "message", 4, "rejected"),
            (4, "message", 6, "accepted"),
            (5, "end", 6, None),
        ]
        assert session(result)["record_number"] == 5
        view = views_by_page(result)["2", "page"]
        assert view["last_processed"] == 3
        assert view["rejected"] == [
            {"number": 2, "reason": {"code": "bad"}},
            {"number": 3, "reason": {"code": "effect and reject"}},
        ]

    @pytest.mark.parametrize("answer", [None, 1])
    def test_save_message_must_answer_true_or_false(self, answer):
        class Vague(TurnTally):
            def save_message(self, state, player_id, message, rejection):
                return answer

        game = Vague()

        result = play(game, started(game), [message(1, "1", "a")], 1)

        assert "Vague.save_message returned {!r}, not True".format(answer) in (
            error(result)
        )

    def test_a_failed_pass_saves_its_messages_whatever_save_message_says(self):
        class Forgetful(TurnTally):
            def save_message(self, state, player_id, message, rejection):
                if message == "boom":
                    raise RuntimeError("boom")
                return False

        game = Forgetful()
        entries = [message(1, "1", "a"), message(2, "1", "boom")]

        result = play(game, started(game), entries, 2)

        assert "RuntimeError: boom" in error(result)
        assert [(each["type"], each.get("status")) for each in result.records] == [
            ("message", "failed"),
            ("message", "failed"),
            ("end", None),
        ]
        assert result.records[-1]["reason"] == FAILED

    def test_a_message_is_recorded_as_it_arrived(self):
        class Keeper(TurnTally):
            def apply(self, state, player_id, message, now, sent):
                message["kept"] = True
                state["kept"] = message

            def save_message(self, state, player_id, message, rejection):
                return message == {"move": 1}

        game = Keeper()
        result = play(game, started(game), [message(1, "1", {"move": 1})], 1)

        assert result.records[0]["payload"] == {"move": 1}
        assert session(result)["state"]["kept"] == {"move": 1, "kept": True}


class TestJsonRoundTrip:
    def test_a_state_holding_nan_fails_the_session(self):
        class Broken(TurnTally):
            def apply(self, state, player_id, message, now, sent):
                state["bad"] = float("nan")

        game = Broken()

        result = play(game, started(game), [message(1, "1", "a")], 1)

        assert "Broken's state isn't JSON: Out of range float" in error(result)

    def test_views_and_records_share_nothing(self):
        game = TurnTally()
        entries = [join(1, "1", scope="other"), message(1, "1", "stop")]
        result = play(game, started(game), entries, 1)

        result.records[-1]["state"]["log"].append("later")
        result.views[0]["view"]["view"]["log"].append("later")

        assert len(result.views) == 3
        assert ["later" in each["view"]["view"]["log"] for each in result.views] == [
            True,
            False,
            False,
        ]


class Seeded(Bot):
    """Plays the same way from the same state, using deadlines, effects and a bot."""

    def initial_state(self, players):
        return {"log": [], "seed": 1, "deadline": None}

    def apply(self, state, player_id, message, now, sent):
        if message == "deadline":
            state["deadline"] = now + 0.6
        super().apply(state, player_id, message, now, sent)

    def tick(self, state, now):
        state["seed"] = state["seed"] * 48271 % 2147483647
        super().tick(state, now)

    def bot(self, view, player_id, now):
        return "effect" if (view["seed"] + view["moves"]) % 3 == 0 else None

    def view(self, state, player_id):
        return {"seed": state["seed"], "moves": len(state["log"])}

    def is_over(self, state):
        return False


MEMBERS = ["1", "2", "3", "9"]


def script(seed):
    """Entries from players 1 to 3 over 10 seconds, split into passes. Odd
    seeds end the session with an end entry.
    """
    rng = random.Random(seed)
    entries = []
    numbers = {}
    time = 0
    while time < 10:
        time = round(time + rng.choice([0.01, 0.07, 0.25, 0.4]), 2)
        player = rng.choice("123")
        scope = rng.choice(["page", "tab"])
        kind = rng.choice(["message"] * 6 + ["join", "leave"])
        if kind == "message":
            numbers[player, scope] = numbers.get((player, scope), 0) + 1
            payload = rng.choice(["a", "b", "bad", "effect", "deadline"])
            entries.append(
                message(time, player, payload, numbers[player, scope], scope)
            )
        else:
            socket = rng.choice(["a", "b"])
            entries.append(socket_entry(kind, time, player, scope, socket))
    if seed % 2:
        at = rng.randrange(len(entries))
        end = {"type": "end", "time": entries[at]["time"], "reason": "ended"}
        entries.insert(at, end)
    passes = []
    start = 0
    while start < len(entries):
        stop = start + rng.randint(1, 5)
        passes.append(entries[start:stop])
        start = stop
    return passes


def played(game, saved, passes):
    """Play each list of entries as one pass, timed at its last entry."""
    results = []
    for entries in passes:
        result = run_pass(game, saved, entries, entries[-1]["time"], CLOCK)
        results.append(result)
        saved = result.saved
    return results


@pytest.mark.parametrize("tick_rate", [4, 0])
class TestReplay:
    @pytest.mark.parametrize("seed", range(3))
    def test_resuming_from_any_saved_session_plays_the_same(self, tick_rate, seed):
        game_type = type(
            "Limited", (Seeded,), {"max_duration": 9, "tick_rate": tick_rate}
        )
        passes = script(seed)
        whole = played(game_type(), new_session(game_type(), MEMBERS, ["9"]), passes)

        for k in range(1, len(passes)):
            assert played(game_type(), whole[k - 1].saved, passes[k:]) == whole[k:]

    @pytest.mark.parametrize("seed", range(3))
    def test_splitting_entries_into_passes_does_not_change_the_game(
        self, tick_rate, seed
    ):
        game = type("Paced", (Seeded,), {"tick_rate": tick_rate})()
        passes = script(seed)
        entries = [entry for each in passes for entry in each]
        saved = new_session(game, MEMBERS, ["9"])

        split = played(game, saved, passes)
        whole = run_pass(game, saved, entries, entries[-1]["time"], CLOCK)

        def without_checkpoints(records):
            return [
                {key: value for key, value in each.items() if key != "sequence"}
                for each in records
                if each["type"] != "checkpoint"
            ]

        assert session(split[-1])["state"] == session(whole)["state"]
        assert without_checkpoints(
            [record for each in split for record in each.records]
        ) == without_checkpoints(whole.records)
