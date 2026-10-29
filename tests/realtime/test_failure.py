import json
import multiprocessing
import signal
import sys
import threading
import time

import pytest

from dallinger.realtime import Reject
from dallinger.realtime.core import fail_session, new_session, run_pass
from dallinger.realtime.game import FAILED
from tests.realtime.helpers import (
    CLOCK,
    Restless,
    TurnTally,
    error,
    join,
    leave,
    log,
    message,
    play,
    session,
    started,
    views_by_page,
)


class Crashing(Restless):
    def apply(self, state, player_id, message, now, sent):
        if message == "crash":
            raise KeyError("no such move")
        super().apply(state, player_id, message, now, sent)


class TestFailure:
    def test_a_raising_method_ends_the_session_at_its_state_before_the_pass(self):
        game = Crashing()
        saved = started(game, members=["1", "2", "4", "9"], bots=["9"])
        entries = [
            message(1, "1", "effect", number=4),
            message(2, "1", "crash", number=5),
            join(3, "3"),
            join(3, "3", scope="tab"),
            leave(3, "3", scope="tab"),
            leave(3, "2"),
            message(4, "1", "a", number=6),
        ]

        result = play(game, saved, entries, 5)

        assert session(result)["state"] == json.loads(saved)["state"]
        assert [
            (each["type"], each["time"], each.get("status")) for each in result.records
        ] == [
            ("message", 1, "failed"),
            ("message", 2, "failed"),
            ("message", 4, "failed"),
            ("end", 5, None),
        ]
        end = result.records[-1]
        assert end["outcome"] == {"reason": FAILED, "moves": 5}
        assert end["error"] == result.ended["error"]
        assert "in apply" in error(result)
        assert "KeyError: 'no such move'" in error(result)
        assert set(result.ended["views"]) == {"1", "2", "4"}
        assert {
            page: (view["ended"], view["last_processed"], view["view"])
            for page, view in views_by_page(result).items()
        } == {
            ("1", "page"): ("failed", 6, {"for": "1", "log": log(result)}),
            ("3", "page"): ("failed", None, {"for": "3", "log": log(result)}),
            ("4", "page"): ("failed", None, {"for": "4", "log": log(result)}),
        }

    def test_game_code_calling_sys_exit_fails_only_its_session(self):
        class Exiting(Crashing):
            def apply(self, state, player_id, message, now, sent):
                sys.exit(3)

        result = play(Exiting(), started(Crashing()), [message(1, "1", "a")], 1)

        assert "SystemExit: 3" in error(result)
        assert result.ended["outcome"] == {"reason": FAILED, "moves": 2}

    @pytest.mark.parametrize(
        "method, outcome, view",
        [
            (
                "outcome",
                None,
                {"for": "1", "log": [["join", "1", 0], ["join", "2", 0]]},
            ),
            ("view", {"reason": FAILED, "moves": 2}, None),
        ],
    )
    def test_a_failed_ending_whose_method_raises_gets_none(self, method, outcome, view):
        def raising(self, *args):
            raise RuntimeError("broken too")

        game = type("Fragile", (Crashing,), {method: raising})()

        result = play(game, started(Crashing()), [message(1, "1", "crash")], 1)

        assert result.ended["outcome"] == outcome
        assert result.ended["views"]["1"] == view
        assert views_by_page(result)[("1", "page")]["view"] == view

    @pytest.mark.parametrize(
        "stop", [{"type": "end", "time": 2, "reason": "stopped"}, message(4, "2", "b")]
    )
    def test_the_failed_record_stops_where_the_pass_would_have(self, stop):
        class Limited(Crashing):
            max_duration = 3

        game = Limited()
        entries = [message(1, "1", "crash"), stop, message(2.5, "1", "c")]

        result = play(game, started(game), entries, 5)

        assert [(each["type"], each["time"]) for each in result.records] == [
            ("message", 1),
            ("end", 5),
        ]

    def test_a_failure_opens_no_page_after_the_join_timeout(self):
        class Unjoined(Crashing):
            join_timeout = 3

        game = Unjoined()

        result = fail_session(
            game, new_session(game, ["1"]), [join(4, "1")], 5, CLOCK, KeyError("x")
        )

        assert session(result)["pages"] == []

    @pytest.mark.parametrize(
        "method, returned, named",
        [
            ("view", {1, 2}, "Bad.view's return value"),
            ("outcome", {1, 2}, "Bad.outcome's return value"),
            ("bot", float("inf"), "Bad.bot's return value"),
            ("apply", Reject({1, 2}), "Bad.apply's Reject reason"),
        ],
    )
    def test_a_value_that_is_not_json_fails_naming_its_method(
        self, method, returned, named
    ):
        def returning(self, *args):
            if isinstance(returned, Exception):
                raise returned
            return returned

        game = type("Bad", (TurnTally,), {method: returning})()
        saved = new_session(game, ["1", "9"], bots=["9"])

        result = play(game, saved, [join(0, "1"), message(1, "1", "stop")], 1)

        assert "{} isn't JSON".format(named) in error(result)

    def test_an_effect_payload_that_is_not_json_fails_naming_queue_effect(self):
        class Leaky(TurnTally):
            def apply(self, state, player_id, message, now, sent):
                self.queue_effect("scored", {1, 2})

        game = Leaky()

        result = play(game, started(game), [message(1, "1", "a")], 1)

        assert "queue_effect's payload isn't JSON" in error(result)

    def test_an_initial_state_that_is_not_json_raises_naming_its_method(self):
        game = type("Bad", (TurnTally,), {"initial_state": lambda self, p: {1, 2}})()

        with pytest.raises(ValueError, match="Bad.initial_state's return value"):
            new_session(game, ["1"])

    def test_a_session_can_be_failed_without_a_pass(self):
        game = TurnTally()
        saved = started(game)
        entries = [message(1, "1", "a", number=1)]

        result = fail_session(
            game, saved, entries, 3, CLOCK, RuntimeError("lost entries")
        )

        assert error(result) == "RuntimeError: lost entries\n"
        assert result.next_due is None
        assert result.ended["time"] == 3
        assert result.ended["outcome"] == {"reason": FAILED, "moves": 2}
        assert session(result)["state"] == json.loads(saved)["state"]
        assert [(each["type"], each.get("status")) for each in result.records] == [
            ("message", "failed"),
            ("end", None),
        ]
        views = views_by_page(result)
        assert set(views) == {("1", "page"), ("2", "page")}
        assert views["1", "page"]["last_processed"] == 1

    def test_entries_that_cannot_be_read_are_left_out_of_the_failure(self):
        game = TurnTally()

        result = fail_session(
            game, started(game), [{"type": "message"}], 3, CLOCK, RuntimeError("x")
        )

        assert [each["type"] for each in result.records] == ["end"]
        assert set(views_by_page(result)) == {("1", "page"), ("2", "page")}

    def test_a_session_without_its_game_type_fails_without_game_code(self):
        saved = started(TurnTally())

        result = fail_session(None, saved, [], 3, CLOCK, RuntimeError("no game"))

        assert result.records == [
            {
                "sequence": 1,
                "type": "end",
                "time": 0,
                "reason": FAILED,
                "outcome": None,
                "state": json.loads(saved)["state"],
                "error": "RuntimeError: no game\n",
            }
        ]
        assert result.ended["views"] == {}
        assert session(result)["ended"] == result.ended
        assert session(result)["record_number"] == 1
        assert result.views == []

    def test_a_session_that_cannot_be_read_is_kept_as_it_is(self):
        result = fail_session(TurnTally(), "[]", [], 3, CLOCK, RuntimeError("x"))

        assert result.saved == "[]"
        [record] = result.records
        assert [record[key] for key in ("sequence", "time")] == [None, None]
        assert result.ended["reason"] == FAILED

    def test_a_time_limit_outside_the_main_thread_raises(self):
        game = TurnTally()
        raised = []

        def play_in_thread():
            try:
                run_pass(game, started(game), [], 1, CLOCK, time_limit=1)
            except RuntimeError as error:
                raised.append(str(error))

        thread = threading.Thread(target=play_in_thread)
        thread.start()
        thread.join(10)

        assert not thread.is_alive()
        assert raised == ["A time limit only works in the main thread."]


class Slow(TurnTally):
    time_limit = 0.5

    def apply(self, state, player_id, message, now, sent):
        if message == "crash":
            raise KeyError("no such move")
        if message == "spin":
            while True:
                try:
                    time.sleep(0.01)
                except Exception:
                    pass
        if message == "trap":
            while True:
                try:
                    time.sleep(0.01)
                except BaseException:
                    pass
        if message == "dodge":
            try:
                while True:
                    time.sleep(0.01)
            except BaseException:
                raise Reject("too slow")
        if message == "slow":
            time.sleep(0.15)
        super().apply(state, player_id, message, now, sent)


class SlowEnding(Slow):
    def outcome(self, state, reason):
        while True:
            time.sleep(0.01)


def play_with_time_limit(sessions, game_type=Slow):
    """Play each list of messages as a session, all in one process."""
    game = game_type()
    results = []
    for messages in sessions:
        entries = [message(1 + n, "1", each) for n, each in enumerate(messages)]
        results.append(
            run_pass(game, started(game), entries, 5, CLOCK, game.time_limit)
        )
    # A timer left running would kill this process before it could return.
    time.sleep(game.time_limit)
    return results


def fail_with_time_limit():
    game = SlowEnding()
    result = fail_session(
        game, started(game), [], 5, CLOCK, RuntimeError("lost"), game.time_limit
    )
    time.sleep(game.time_limit)
    return result


def trap_when_ready(ready):
    ready.set()
    # A time-out that lands in the trap's except clause escapes it and ends
    # the session, so trap again until the process exits.
    while True:
        play_with_time_limit([["trap"]])


def previous_handler():
    pass


def handler_after_a_pass():
    signal.signal(signal.SIGALRM, previous_handler)
    play_with_time_limit([["crash"]])
    return signal.getsignal(signal.SIGALRM) is previous_handler


#: Seconds a spawned process may take to import Dallinger and the tests.
IMPORT_WAIT = 120


@pytest.fixture(scope="module")
def in_main_thread():
    """Run a function in another process's main thread, where the time
    limit's signal works.
    """
    with multiprocessing.get_context("spawn").Pool(1) as pool:
        # The worker imports Dallinger first, which a loaded machine slows down,
        # so each test's own wait covers only its own work.
        pool.apply_async(previous_handler).get(IMPORT_WAIT)
        yield lambda function, *args: pool.apply_async(function, args).get(10)


# Each test starts a process that imports Dallinger and runs past real time limits.
@pytest.mark.slow
class TestTimeLimit:
    def test_a_spinning_session_fails_unscored_while_the_next_plays_on(
        self, in_main_thread
    ):
        spinning, next_one = in_main_thread(
            play_with_time_limit, [["a", "spin"], ["a", "b"]]
        )

        assert (
            "TimeLimitExceeded: Slow.apply was running when the session used up "
            "its 0.5 seconds." in error(spinning)
        )
        assert spinning.ended["outcome"] is None
        assert spinning.ended["views"] == {"1": None, "2": None}
        assert next_one.ended is None
        assert log(next_one)[2:] == [["1", "a", 1], ["1", "b", 2]]

    def test_game_code_that_turns_the_time_limit_into_a_rejection_still_fails(
        self, in_main_thread
    ):
        [result] = in_main_thread(play_with_time_limit, [["dodge"]])

        assert (
            "TimeLimitExceeded: The session had used up its 0.5 seconds before "
            "Slow.save_message ran." in error(result)
        )

    def test_game_code_that_catches_every_exception_ends_the_process(self):
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        process = context.Process(target=trap_when_ready, args=(ready,))
        process.start()
        try:
            assert ready.wait(IMPORT_WAIT)
            process.join(10)
        finally:
            if process.exitcode is None:
                process.kill()

        assert process.exitcode == 1

    def test_the_limit_is_for_all_the_calls_in_a_pass(self, in_main_thread):
        once, four_times = in_main_thread(
            play_with_time_limit, [["slow"], ["slow"] * 4]
        )

        assert once.ended is None
        assert "TimeLimitExceeded" in error(four_times)

    def test_a_spinning_outcome_leaves_no_time_for_the_final_views(
        self, in_main_thread
    ):
        [result] = in_main_thread(play_with_time_limit, [["crash"]], SlowEnding)

        assert result.ended["outcome"] is None
        assert result.ended["views"] == {"1": None, "2": None}

    def test_a_session_failed_without_a_pass_has_the_limit_too(self, in_main_thread):
        result = in_main_thread(fail_with_time_limit)

        assert result.ended["outcome"] is None
        assert result.ended["views"] == {"1": None, "2": None}

    def test_the_previous_signal_handler_is_restored(self, in_main_thread):
        assert in_main_thread(handler_after_a_pass)
