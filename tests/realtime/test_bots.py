from unittest import mock

import pytest

from dallinger import db
from dallinger.bots import HighPerformanceBotBase
from dallinger.models import RealtimeSession
from tests.realtime.helpers import TurnTally, create_session

pytestmark = pytest.mark.usefixtures("redis_conn", "realtime_experiment")


@pytest.fixture
def bot():
    bot = HighPerformanceBotBase(
        "https://dallinger.io/ad?assignment_id=a1&worker_id=w1&hit_id=h1"
    )
    bot.participant_id = 1
    return bot


def end(session_id, status="ended"):
    with db.session_factory() as own:
        own.query(RealtimeSession).filter_by(id=session_id).update({"status": status})
        own.commit()


def waits_while(bot, *steps, **options):
    """Call wait_for_realtime_sessions, running each step in place of a wait,
    and return its result and how many times it waited.
    """
    pending = list(steps)

    def sleep(seconds):
        if not pending:
            raise AssertionError("waited after the last step")
        pending.pop(0)()

    with mock.patch("dallinger.bots.gevent.sleep", side_effect=sleep) as slept:
        result = bot.wait_for_realtime_sessions(TurnTally, **options)
    return result, slept.call_count


@pytest.mark.parametrize("status", ["ended", "failed"])
def test_a_bot_waits_until_its_session_is_over(bot, status):
    session_id = create_session(TurnTally, ["1", "2"])

    result, waits = waits_while(bot, lambda: None, lambda: end(session_id, status))

    assert (result, waits) == (True, 2)


def test_a_bot_waits_for_its_session_to_start(bot):
    create_session(TurnTally, ["2", "3"])
    started = []

    def start():
        started.append(create_session(TurnTally, ["1", "2"]))

    result, waits = waits_while(bot, start, lambda: end(started[0]))

    assert (result, waits) == (True, 2)


def test_a_bot_waits_until_none_of_its_sessions_is_running(bot):
    first = create_session(TurnTally, ["1", "2"])
    second = create_session(TurnTally, ["1", "2"])
    end(second)

    result, waits = waits_while(bot, lambda: end(first))

    assert (result, waits) == (True, 1)


def test_a_bot_gives_up_after_the_timeout(bot):
    create_session(TurnTally, ["1", "2"])
    bot.log = mock.Mock()

    with mock.patch("dallinger.bots.time.monotonic", side_effect=[0, 5, 10]):
        result, waits = waits_while(bot, lambda: None, timeout=10)

    assert (result, waits) == (False, 1)
    bot.log.assert_called_once_with("Gave up waiting for real-time sessions to end.")


def test_a_bot_holds_no_transaction_open_while_it_waits(bot):
    session_id = create_session(TurnTally, ["1", "2"])
    in_transaction = []

    def check():
        in_transaction.append(db.session().in_transaction())
        end(session_id)

    waits_while(bot, check)

    assert in_transaction == [False]
