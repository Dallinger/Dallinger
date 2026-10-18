import json
import time
from unittest.mock import Mock, patch

import gevent
import pytest
from gevent.event import Event
from redis import ConnectionError as RedisConnectionError
from simple_websocket import ConnectionClosed

from dallinger.experiment_server import socket_admission
from dallinger.experiment_server import sockets as sockets_module
from dallinger.realtime import session_sockets, store
from dallinger.realtime.core import run_pass
from dallinger.realtime.jobs import write_ending
from tests.realtime.helpers import CLOCK, TurnTally

pytestmark = pytest.mark.usefixtures("redis_conn", "realtime_experiment")

SUBSCRIBE_CONFIRMATION = {
    "type": "subscribe",
    "pattern": None,
    "channel": b"",
    "data": 1,
}


class Other(TurnTally):
    channel = "other"


class Limited(TurnTally):
    channel = "limited"
    # Slow enough that nothing refills during a test.
    max_messages_per_second = 0.001
    message_burst = 3


@pytest.fixture
def pubsub():
    pubsub = Mock()
    pubsub.listen.return_value = [SUBSCRIBE_CONFIRMATION]
    return pubsub


@pytest.fixture
def sockets(pubsub, monkeypatch):
    sockets = sockets_module
    monkeypatch.setattr(sockets, "redis_conn", Mock())
    sockets.redis_conn.pubsub.return_value = pubsub
    monkeypatch.setattr(sockets, "chat_backend", sockets.ChatBackend())
    monkeypatch.setattr(socket_admission, "_process_experiment", None)
    monkeypatch.setattr(sockets, "_process_games", None)
    yield sockets
    gevent.wait()


@pytest.fixture
def warning():
    with patch.object(session_sockets.logger, "warning") as warning:
        yield warning


def scripted(*frames):
    """A socket that receives ``frames`` and then closes."""
    ws = Mock(close_reason=None, close_message=None, connected=True)
    remaining = list(frames)

    def receive():
        if not remaining:
            ws.connected = False
            return None
        return remaining.pop(0)

    ws.receive = Mock(side_effect=receive)
    return ws


class Parked:
    """Waits in ``receive()`` on an event until closed, as simple_websocket's
    socket does.
    """

    close_reason = None
    close_message = None

    def __init__(self):
        self.connected = True
        self.event = Event()
        self.closed_with = None

    def receive(self):
        while self.connected:
            self.event.wait()
            self.event.clear()
        raise ConnectionClosed(self.close_reason, self.close_message)

    def close(self, reason=None, message=None):
        self.closed_with = (reason, message)
        self.connected = False


def chat(sockets, ws, **args):
    with patch.object(sockets, "request", Mock(args=args)):
        sockets.chat(ws)


def entries(session_id):
    return [
        json.loads(fields[b"entry"])
        for _, fields in store.redis_conn.xrange(
            store.session_key(session_id, "entries")
        )
    ]


def relayed(sockets):
    return [
        call.args
        for call in sockets.redis_conn.publish.mock_calls
        if call.args[0] != sockets.CONTROL_CHANNEL
    ]


def types_of(session_id):
    return [each["type"] for each in entries(session_id)]


def session_of(game_type=TurnTally):
    return str(store.create_realtime_session(game_type, ["1", "2", "9"], bots=["9"]))


def end_session(session_id):
    """End a session as a runner would, saving a pass over an end entry."""
    session_id = int(session_id)
    token, _ = store.claim(session_id, "test", 30)
    saved = store.load_session(session_id)["saved"]
    ending = [{"type": "end", "time": 0, "reason": "abandoned"}]
    result = run_pass(TurnTally(), saved, ending, 0, CLOCK)
    assert store.save_passes([(session_id, token, [], result)], 30) == []


def sent_frames(ws):
    return [call.args[0] for call in ws.send.mock_calls]


def time_frame(frame):
    return "dallinger_time:" + json.dumps(frame)


REQUEST = time_frame({"type": "request", "id": 7})

REPORT = time_frame(
    {"type": "clock", "browser_time": 5000, "server_time": 900.5, "round_trip": 0}
)


class TestSessionSockets:
    def test_a_players_frames_reach_the_session_between_its_join_and_leave(
        self, sockets
    ):
        session_id = session_of()
        ws = scripted("tally:up", "custom:hello", "tally:down")

        chat(sockets, ws, session=session_id, participant_id="1", scope="page")

        ws.close.assert_not_called()
        added = entries(session_id)
        socket_id = added[0]["socket"]
        page = {"participant": "1", "scope": "page"}
        assert added == [
            {"type": "join", **page, "socket": socket_id},
            {"type": "message", **page, "data": "up"},
            {"type": "message", **page, "data": "down"},
            {"type": "leave", **page, "socket": socket_id},
        ]
        assert relayed(sockets) == [("custom", "hello")]

    def test_game_frames_never_reach_the_experiment(self, sockets):
        session_id = session_of()
        ws = scripted("tally:up", "custom:hello")
        experiment = Mock()

        with (
            patch.object(socket_admission, "resolve_participant_id", return_value="1"),
            patch.object(socket_admission, "Experiment", return_value=experiment),
            patch.object(sockets, "request", Mock(args={"session": session_id})),
        ):
            sockets.experiment_socket(ws)

        handled = [
            call.kwargs["channel_name"]
            for call in experiment.handle_websocket_message.mock_calls
        ]
        assert handled == ["custom"]
        assert types_of(session_id) == ["join", "message", "leave"]

    @pytest.mark.parametrize(
        "args",
        [
            {"participant_id": "3"},
            {"participant_id": None},
            {"participant_id": "1", "session": "one"},
        ],
        ids=["not a member", "no participant", "not a number"],
    )
    def test_a_socket_that_isnt_a_players_is_refused(self, sockets, args):
        session_id = session_of()
        ws = scripted("tally:up")

        chat(sockets, ws, **{"session": session_id, **args})

        ws.close.assert_called_once_with(
            sockets.REFUSED_CLOSE_CODE, "not a player in this session"
        )
        ws.receive.assert_not_called()
        assert entries(session_id) == []

    def test_a_failed_lookup_asks_the_client_to_retry(self, sockets):
        session_id = session_of()
        ws = scripted("tally:up")

        with patch.object(
            store, "player_game_channel", side_effect=RedisConnectionError()
        ):
            chat(sockets, ws, session=session_id, participant_id="1")

        ws.close.assert_called_once_with(
            sockets.UNAVAILABLE_CLOSE_CODE, "session lookup failed"
        )

    def test_invalid_game_types_close_every_socket(self, sockets, realtime_experiment):
        realtime_experiment.realtime_games = [TurnTally, TurnTally]
        ws = scripted("custom:hello")

        chat(sockets, ws, channel="custom")

        ws.close.assert_called_once_with(
            sockets.UNAVAILABLE_CLOSE_CODE, "experiment unavailable"
        )
        assert relayed(sockets) == []

    def test_a_frame_on_another_game_types_channel_is_dropped(
        self, sockets, realtime_experiment, warning
    ):
        realtime_experiment.realtime_games = [TurnTally, Other]
        session_id = session_of()
        ws = scripted("other:up", "other:up")

        chat(sockets, ws, session=session_id, participant_id="1")

        assert relayed(sockets) == []
        assert all(each["type"] != "message" for each in entries(session_id))
        assert len(warning.call_args_list) == 1

    def test_frames_over_the_rate_limit_are_dropped_with_a_warning(
        self, sockets, realtime_experiment, warning
    ):
        realtime_experiment.realtime_games = [Limited]
        session_id = session_of(Limited)
        ws = scripted(*["limited:{}".format(n) for n in range(5)])

        chat(sockets, ws, session=session_id, participant_id="1")

        messages = [e["data"] for e in entries(session_id) if e["type"] == "message"]
        assert messages == ["0", "1", "2"]
        (call,) = warning.call_args_list
        assert "rate limit" in call.args[-1]

    def test_a_message_redis_refuses_is_dropped_and_the_socket_kept(
        self, sockets, warning
    ):
        session_id = session_of()
        ws = scripted("tally:lost", "tally:kept")
        add_entry = store.add_entry

        def refuse_first_message(session_id, entry):
            if entry.get("data") == "lost":
                raise RedisConnectionError()
            return add_entry(session_id, entry)

        with patch.object(store, "add_entry", side_effect=refuse_first_message):
            chat(sockets, ws, session=session_id, participant_id="1")

        ws.close.assert_not_called()
        assert [e.get("data") for e in entries(session_id)] == [None, "kept", None]
        assert warning.call_args.kwargs["exc_info"]

    def test_each_socket_of_a_page_has_its_own_id(self, sockets):
        session_id = session_of()
        for _ in range(2):
            chat(sockets, scripted(), session=session_id, participant_id="1")

        joins = [
            each["socket"] for each in entries(session_id) if each["type"] == "join"
        ]
        assert len(set(joins)) == 2

    @pytest.mark.timeout(10)
    def test_the_join_waits_for_the_direct_listener(self, sockets, pubsub):
        session_id = session_of()
        confirm = Event()

        def withheld_listen():
            confirm.wait()
            yield SUBSCRIBE_CONFIRMATION
            Event().wait()
            yield {}

        pubsub.listen.side_effect = withheld_listen
        ws = scripted()

        with patch.object(sockets, "SUBSCRIPTION_TIMEOUT_SECS", 30):
            serving = gevent.spawn(
                chat, sockets, ws, session=session_id, participant_id="1"
            )
            gevent.sleep(0.05)
            assert entries(session_id) == []

            confirm.set()
            serving.join(timeout=5)

        assert types_of(session_id) == ["join", "leave"]

    @pytest.mark.timeout(10)
    def test_a_socket_closed_while_it_waits_never_joins(self, sockets, pubsub):
        session_id = session_of()
        confirm = Event()

        def withheld_listen():
            confirm.wait()
            yield SUBSCRIBE_CONFIRMATION
            Event().wait()
            yield {}

        pubsub.listen.side_effect = withheld_listen
        ws = scripted("tally:up")

        with patch.object(sockets, "SUBSCRIPTION_TIMEOUT_SECS", 30):
            serving = gevent.spawn(
                chat, sockets, ws, session=session_id, participant_id="1"
            )
            gevent.sleep(0.05)
            ws.connected = False
            confirm.set()
            serving.join(timeout=5)

        assert entries(session_id) == []

    @pytest.mark.timeout(10)
    def test_a_socket_with_no_session_closed_while_it_waits_isnt_served(
        self, sockets, pubsub
    ):
        confirm = Event()

        def withheld_listen():
            confirm.wait()
            yield SUBSCRIBE_CONFIRMATION
            Event().wait()
            yield {}

        pubsub.listen.side_effect = withheld_listen
        ws = scripted("custom:hello")

        with (
            patch.object(sockets, "SUBSCRIPTION_TIMEOUT_SECS", 30),
            patch.object(sockets, "publish_control_event") as control_event,
        ):
            serving = gevent.spawn(
                chat, sockets, ws, channel="custom", participant_id="1"
            )
            gevent.sleep(0.05)
            ws.connected = False
            confirm.set()
            serving.join(timeout=5)

        events = [call.args[0].get("event") for call in control_event.mock_calls]
        assert "connected" not in events

    def test_a_join_redis_refuses_asks_the_client_to_retry(self, sockets):
        session_id = session_of()
        ws = scripted("tally:up")

        with patch.object(store, "add_entry", side_effect=RedisConnectionError()):
            chat(sockets, ws, session=session_id, participant_id="1")

        ws.close.assert_called_once_with(
            sockets.UNAVAILABLE_CLOSE_CODE, "session join failed"
        )
        ws.receive.assert_not_called()

    def test_a_leave_redis_refuses_is_logged(self, sockets):
        session_id = session_of()
        ws = scripted()
        add_entry = store.add_entry

        def refuse_leaves(session_id, entry):
            if entry["type"] == "leave":
                raise RedisConnectionError()
            return add_entry(session_id, entry)

        with (
            patch.object(store, "add_entry", side_effect=refuse_leaves),
            patch.object(sockets.app.logger, "exception") as exception,
        ):
            chat(sockets, ws, session=session_id, participant_id="1")

        assert "leave" in exception.call_args.args[0]
        assert "1" not in sockets.chat_backend.clients_by_participant


class TestTimeChannel:
    def test_a_time_request_is_answered_on_its_socket(self, sockets):
        session_id = session_of()
        ws = scripted(REQUEST)
        before = time.time()

        # Redis's clock, read once at the join, is 50 seconds ahead.
        with patch.object(store, "server_time", lambda: time.time() + 50):
            chat(sockets, ws, session=session_id, participant_id="1")

        (sent,) = sent_frames(ws)
        channel, _, answer = sent.partition(":")
        answer = json.loads(answer)
        assert (channel, answer["type"], answer["id"]) == ("dallinger_time", "time", 7)
        assert before + 50 <= answer["clock"] <= time.time() + 50
        assert types_of(session_id) == ["join", "leave"]
        assert relayed(sockets) == []

    def test_a_time_request_is_answered_without_redis(self):
        page = session_sockets.SessionSocket(1, TurnTally(), "1", "page", "a page")

        with patch.object(store, "redis_conn", Mock(spec=[])):
            answer = page.handle_frame("dallinger_time", REQUEST.partition(":")[2])

        assert json.loads(answer.partition(":")[2])["id"] == 7

    def test_a_socket_with_no_session_gets_no_answer(self, sockets, warning):
        ws = scripted(REQUEST, REPORT)

        chat(sockets, ws, channel="custom", participant_id="1")

        ws.send.assert_not_called()
        assert relayed(sockets) == []
        assert warning.call_count == 1

    def test_a_clock_report_is_added_to_the_session(self, sockets):
        session_id = session_of()
        ws = scripted(REPORT)

        chat(sockets, ws, session=session_id, participant_id="1", scope="page")

        assert entries(session_id)[1] == {
            "type": "clock",
            "participant": "1",
            "scope": "page",
            "browser_time": 5000.0,
            "server_time": 900.5,
            "round_trip": 0.0,
        }

    @pytest.mark.parametrize(
        "data",
        [
            "not json",
            "[1]",
            '{"type": "other", "browser_time": 1, "server_time": 2, "round_trip": 0}',
            '{"type": "clock", "browser_time": 1, "server_time": 2}',
            '{"type": "clock", "browser_time": "1", "server_time": 2, "round_trip": 0}',
            '{"type": "clock", "browser_time": true, "server_time": 2, '
            '"round_trip": 0}',
            '{"type": "clock", "browser_time": NaN, "server_time": 2, "round_trip": 0}',
            '{"type": "clock", "browser_time": 1' + "0" * 400 + ', "server_time": 2, '
            '"round_trip": 0}',
            '{"type": "clock", "browser_time": 1, "server_time": 2, '
            '"round_trip": -0.5}',
            "[" * 1000000,
            '{"type": "request"}',
            '{"type": "request", "id": true}',
        ],
        ids=[
            "not JSON",
            "not an object",
            "unknown type",
            "missing value",
            "string",
            "boolean",
            "NaN",
            "too large for a float",
            "negative round trip",
            "nested too deeply",
            "request without an id",
            "request with a boolean id",
        ],
    )
    def test_a_bad_frame_is_dropped_with_a_warning(self, sockets, warning, data):
        session_id = session_of()
        ws = scripted("dallinger_time:" + data)

        chat(sockets, ws, session=session_id, participant_id="1")

        ws.send.assert_not_called()
        assert types_of(session_id) == ["join", "leave"]
        assert warning.call_count == 1

    def test_reports_count_against_the_rate_limit_and_requests_dont(
        self, sockets, realtime_experiment, warning
    ):
        realtime_experiment.realtime_games = [Limited]
        session_id = session_of(Limited)
        ws = scripted("limited:0", REPORT, REPORT, REPORT, REQUEST)

        chat(sockets, ws, session=session_id, participant_id="1")

        assert types_of(session_id) == ["join", "message", "clock", "clock", "leave"]
        assert len(sent_frames(ws)) == 1
        assert "rate limit" in warning.call_args.args[-1]


class TestEndedSessions:
    @pytest.mark.parametrize("saved", [False, True], ids=["unsaved", "saved"])
    def test_a_page_joining_an_ended_session_gets_its_ending(
        self, sockets, warning, saved
    ):
        session_id = session_of()
        end_session(session_id)
        if saved:
            write_ending(int(session_id))
        ws = scripted("tally:late", REPORT)

        chat(sockets, ws, session=session_id, participant_id="1")

        (sent,) = sent_frames(ws)
        channel, _, payload = sent.partition(":")
        ending = {
            "session_id": int(session_id),
            "reason": "abandoned",
            "view": {"for": "1", "log": []},
        }
        if saved:
            ending.update(type="realtime_saved", status="ended")
        else:
            ending.update(type="realtime_ended")
        assert (channel, json.loads(payload)) == ("dallinger_direct", ending)
        assert entries(session_id) == []
        ws.close.assert_not_called()
        assert "has ended" in warning.call_args.args[-1]

    def test_a_page_joining_a_session_whose_ending_expired_is_refused(self, sockets):
        session_id = session_of()
        end_session(session_id)
        ws = scripted("tally:late")

        with patch.object(store, "load_ending", return_value=None):
            chat(sockets, ws, session=session_id, participant_id="1")

        ws.close.assert_called_once_with(
            sockets.REFUSED_CLOSE_CODE, "not a player in this session"
        )
        ws.send.assert_not_called()


class TestRateLimit:
    def test_drops_are_warned_about_at_most_once_a_second(self, warning):
        now = [0.0]
        dropping = session_sockets.NoSession("a page")
        with patch.object(session_sockets.time, "monotonic", lambda: now[0]):
            for now[0] in (0.0, 0.5, 1.0):
                dropping.handle_frame("tally", "up")

        assert warning.call_count == 2

    def test_a_bucket_refills_at_its_rate_up_to_its_capacity(self):
        now = [0.0]
        with patch.object(session_sockets.time, "monotonic", lambda: now[0]):
            bucket = session_sockets.TokenBucket(rate=2, capacity=3)
            assert [bucket.take() for _ in range(4)] == [True, True, True, False]

            now[0] += 0.5
            assert [bucket.take() for _ in range(2)] == [True, False]

            now[0] += 100
            assert [bucket.take() for _ in range(4)] == [True, True, True, False]


class TestShutdown:
    @pytest.mark.timeout(10)
    def test_closing_every_socket_lets_each_add_its_leave(self, sockets):
        session_id = session_of()
        player, bystander = Parked(), Parked()
        serving = [
            gevent.spawn(chat, sockets, player, session=session_id, participant_id="1"),
            gevent.spawn(chat, sockets, bystander, channel="custom"),
        ]
        gevent.sleep(0.05)

        sockets.chat_backend.close_all()
        gevent.joinall(serving, timeout=5)

        assert all(each.dead for each in serving)
        going_away = (sockets.GOING_AWAY_CLOSE_CODE, "server shutting down")
        assert player.closed_with == bystander.closed_with == going_away
        assert types_of(session_id) == ["join", "leave"]
        assert not sockets.chat_backend.open_clients

    @pytest.mark.timeout(10)
    def test_a_stuck_socket_doesnt_hold_up_the_others(self, sockets):
        released = Event()
        stuck = [Mock(), Mock()]
        for ws in stuck:
            ws.close.side_effect = lambda *args: released.wait()
            sockets.chat_backend.open_clients.add(sockets.Client(ws))

        closing = gevent.spawn(sockets.chat_backend.close_all)
        gevent.sleep(0.05)

        assert all(ws.close.called for ws in stuck)
        released.set()
        closing.join()

    def test_a_socket_set_up_during_shutdown_is_closed_at_once(self, sockets):
        session_id = session_of()
        lookup = store.player_game_channel

        def shut_down_during_lookup(*args):
            sockets.chat_backend.close_all()
            return lookup(*args)

        ws = scripted("tally:up")
        with patch.object(
            store, "player_game_channel", side_effect=shut_down_during_lookup
        ):
            chat(sockets, ws, session=session_id, participant_id="1")

        ws.close.assert_called_once_with(
            sockets.GOING_AWAY_CLOSE_CODE, "server shutting down"
        )
        assert entries(session_id) == []
