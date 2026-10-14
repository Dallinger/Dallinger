import json
import multiprocessing
import signal
import threading
import time

import pytest

from dallinger.realtime import Reject
from dallinger.realtime.core import new_session, run_pass
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
        assert end["outcome"] == {"reason": FAILED, "moves": 4}
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

    def test_an_initial_state_that_is_not_json_raises_naming_its_method(self):
        game = type("Bad", (TurnTally,), {"initial_state": lambda self, p: {1, 2}})()

        with pytest.raises(ValueError, match="Bad.initial_state's return value"):
            new_session(game, ["1"])

    def test_state_from_another_version_is_migrated(self):
        class Renamed(TurnTally):
            state_version = 2

            def migrate_state(self, state, from_version):
                return {"log": state["moves"] + [["migrated from", from_version]]}

        old = json.loads(started(TurnTally()))
        old["state"] = {"moves": [["1", "a", 0]]}

        result = play(Renamed(), json.dumps(old), [], 1)

        assert session(result)["state_version"] == 2
        assert log(result) == [["1", "a", 0], ["migrated from", 1]]
        assert {
            page: view["view"]["log"] for page, view in views_by_page(result).items()
        } == {
            ("1", "page"): log(result),
            ("2", "page"): log(result),
        }

    def test_a_session_that_fails_after_migrating_is_scored_on_the_migrated_state(
        self,
    ):
        class Renamed(Crashing):
            state_version = 2

            def migrate_state(self, state, from_version):
                return {"log": state["moves"]}

        old = json.loads(started(TurnTally()))
        old["state"] = {"moves": [["1", "a", 0]]}

        result = play(Renamed(), json.dumps(old), [message(1, "1", "crash")], 1)

        assert result.ended["outcome"] == {"reason": FAILED, "moves": 1}
        assert session(result)["state_version"] == 2

    def test_state_from_another_version_fails_without_reading_it(self):
        class Calling(TurnTally):
            state_version = 2

            def __init__(self):
                self.migrations = []

            def migrate_state(self, state, from_version):
                self.migrations.append(from_version)
                return super().migrate_state(state, from_version)

            def outcome(self, state, reason):
                return "read the old state"

            def view(self, state, player_id):
                return "read the old state"

        game = Calling()
        saved = started(TurnTally())

        result = play(game, saved, [message(1, "1", "a")], 1)

        assert "Calling can't read state saved with state_version 1" in error(result)
        assert game.migrations == [1]
        assert result.ended["outcome"] is None
        assert result.ended["views"] == {"1": None, "2": None}
        assert session(result)["state"] == json.loads(saved)["state"]

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
        thread.join()

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


def previous_handler():
    pass


def handler_after_a_pass():
    signal.signal(signal.SIGALRM, previous_handler)
    play_with_time_limit([["crash"]])
    return signal.getsignal(signal.SIGALRM) is previous_handler


@pytest.fixture(scope="module")
def in_main_thread():
    """Run a function in another process's main thread, where the time
    limit's signal works.
    """
    with multiprocessing.get_context("spawn").Pool(1) as pool:
        yield lambda function, *args: pool.apply_async(function, args).get(10)


# Each test starts a process that imports Dallinger and runs past real time limits.
@pytest.mark.slow
class TestTimeLimit:
    def test_a_spinning_session_fails_and_is_scored_while_the_next_plays_on(
        self, in_main_thread
    ):
        spinning, next_one = in_main_thread(
            play_with_time_limit, [["a", "spin"], ["a", "b"]]
        )

        assert (
            "TimeLimitExceeded: Slow.apply was running when the session used up "
            "its 0.5 seconds." in error(spinning)
        )
        assert spinning.ended["outcome"] == {"reason": FAILED, "moves": 2}
        assert next_one.ended is None
        assert log(next_one)[2:] == [["1", "a", 1], ["1", "b", 2]]

    def test_game_code_that_turns_the_time_limit_into_a_rejection_still_fails(
        self, in_main_thread
    ):
        [result] = in_main_thread(play_with_time_limit, [["dodge"]])

        assert (
            "TimeLimitExceeded: Slow.is_over was running when the session used up"
            in error(result)
        )

    def test_game_code_that_catches_every_exception_ends_the_process(self):
        process = multiprocessing.get_context("spawn").Process(
            target=play_with_time_limit, args=([["trap"]],)
        )
        process.start()
        process.join(10)
        if process.exitcode is None:
            process.kill()

        assert process.exitcode == 1

    def test_the_limit_is_for_all_the_calls_in_a_pass(self, in_main_thread):
        once, four_times = in_main_thread(
            play_with_time_limit, [["slow"], ["slow"] * 4]
        )

        assert once.ended is None
        assert "TimeLimitExceeded" in error(four_times)

    def test_a_spinning_outcome_leaves_the_final_views(self, in_main_thread):
        [result] = in_main_thread(play_with_time_limit, [["crash"]], SlowEnding)

        assert result.ended["outcome"] is None
        assert result.ended["views"]["1"] == {"for": "1", "log": log(result)}

    def test_the_previous_signal_handler_is_restored(self, in_main_thread):
        assert in_main_thread(handler_after_a_pass)
