import json
import numbers
import socket
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import gevent
import pytest
from gevent.event import Event
from simple_websocket import ConnectionClosed


def parking_listen():
    """A pubsub stream that blocks forever, as a real socket read does."""
    Event().wait()
    yield {}


@pytest.fixture
def pubsub():
    pubsub = Mock()
    pubsub.listen.return_value = []
    return pubsub


@pytest.fixture
def redis(pubsub):
    conn = Mock()
    conn.pubsub.return_value = pubsub
    return conn


@pytest.fixture
def sockets(redis):
    from dallinger.experiment_server import sockets

    sockets.redis_conn = redis
    # use a separate ChatBackend for each test
    sockets.chat_backend = sockets.ChatBackend()
    sockets._process_experiment = None

    yield sockets

    # make sure all greenlets complete
    gevent.wait()


@pytest.fixture
def chat(sockets):
    return sockets.chat_backend


@pytest.fixture
def channel(sockets):
    sockets.chat_backend.channels["test"] = channel = sockets.Channel("test")
    yield channel
    channel.stop()
    sockets.chat_backend.channels.pop("test", None)


@pytest.fixture
def client(sockets):
    ws = Mock()
    ws.close_reason = "Unexpected"
    ws.close_message = "Mock message"
    return sockets.Client(ws)


@pytest.fixture
def registered(sockets):
    """Build a connection for a participant and make it addressable."""

    def build(participant_id, scope=None):
        ws = Mock()
        ws.close_reason = None
        ws.close_message = None
        client = sockets.Client(ws, participant_id=participant_id, scope=scope)
        sockets.chat_backend.register(client)
        return client

    return build


@pytest.fixture
def mockclient():
    client = Mock()
    client.client_info.return_value = '{"class": "MockClient"}'
    return client


@pytest.fixture
def yielding_socket():
    class YieldingSocket:
        """Parks in ``receive()`` on a gevent ``Event``.

        Under gunicorn's gevent worker ``simple_websocket`` builds its
        ``threading.Event`` after monkeypatching, so production ``receive()``
        waits on this same cooperative primitive.
        """

        def __init__(self):
            self.message_ready = Event()
            self.connected = True
            self.close_reason = None
            self.close_message = None

        def receive(self):
            self.message_ready.wait()
            self.connected = False
            return "custom:delivered"

    return YieldingSocket()


@pytest.fixture
def scripted_socket():
    def build(*frames):
        ws = Mock()
        ws.close_reason = None
        ws.close_message = None
        ws.connected = True
        remaining = list(frames)

        def receive():
            if not remaining:
                ws.connected = False
                return None
            return remaining.pop(0)

        ws.receive = Mock(side_effect=receive)
        return ws

    return build


@pytest.fixture
def mocksocket():
    class MockSocket(Mock):
        """``connected`` is a property because a Mock attribute cannot return
        ``True`` once and ``False`` afterwards.
        """

        calls = []

        receive = Mock()
        receive.return_value = None

        @property
        def connected(self):
            if self.calls:
                return False
            self.calls.append("called")
            return True

    return MockSocket()


class TestChannel:
    def test_subscribes_to_redis(self, sockets, pubsub):
        sockets.Channel("custom").start()
        gevent.wait()
        pubsub.subscribe.assert_called_once_with([b"custom"])

    def test_listen(self, sockets, mockclient):
        sockets.redis_conn.pubsub.return_value = pubsub = Mock()
        pubsub.listen.return_value = [
            {"type": "message", "channel": b"quorum", "data": b"Calloo! Callay!"}
        ]

        channel = sockets.Channel("custom")
        channel.subscribe(mockclient)
        channel.start()
        gevent.wait()  # wait for event loop

        mockclient.send.assert_called_once_with("quorum:Calloo! Callay!")

    @pytest.mark.timeout(10)
    def test_failed_subscribe_is_retried(self, sockets, pubsub, mockclient):
        pubsub.subscribe.side_effect = [sockets.ConnectionError("no redis"), None]
        pubsub.listen.return_value = [
            {"type": "message", "channel": b"custom", "data": b"after retry"}
        ]
        channel = sockets.Channel("custom")
        channel.RECONNECT_DELAY_SECS = 0
        channel.subscribe(mockclient)

        channel.start()
        gevent.wait(timeout=1)

        assert pubsub.subscribe.call_count == 2
        mockclient.send.assert_called_once_with("custom:after retry")

    def test_listen_closes_pubsub(self, sockets, pubsub):
        sockets.Channel("custom").start()
        gevent.wait()
        pubsub.close.assert_called_once_with()

    @pytest.mark.timeout(10)
    def test_relay_resumes_after_lost_connection(self, sockets, pubsub, mockclient):
        pubsub.listen.side_effect = [
            sockets.ConnectionError("dropped"),
            iter(
                [{"type": "message", "channel": b"custom", "data": b"after reconnect"}]
            ),
        ]
        channel = sockets.Channel("custom")
        channel.RECONNECT_DELAY_SECS = 0
        channel.subscribe(mockclient)

        channel.start()
        gevent.wait(timeout=1)

        mockclient.send.assert_called_once_with("custom:after reconnect")

    def test_reconnect_delay_doubles_up_to_the_cap(self, sockets, pubsub):
        pubsub.listen.side_effect = [
            sockets.ConnectionError("one"),
            sockets.ConnectionError("two"),
            sockets.ConnectionError("three"),
            iter([]),
        ]
        channel = sockets.Channel("custom")
        channel.RECONNECT_DELAY_SECS = 1
        channel.MAX_RECONNECT_DELAY_SECS = 2
        delays = []

        with patch.object(sockets.gevent, "sleep", delays.append):
            channel.listen()

        assert delays == [1, 2, 2]

    @pytest.mark.timeout(10)
    def test_timeout_is_retried_like_a_lost_connection(
        self, sockets, pubsub, mockclient
    ):
        pubsub.listen.side_effect = [
            sockets.RedisTimeoutError("slow"),
            iter([{"type": "message", "channel": b"custom", "data": b"after retry"}]),
        ]
        channel = sockets.Channel("custom")
        channel.RECONNECT_DELAY_SECS = 0
        channel.subscribe(mockclient)

        channel.start()
        gevent.wait(timeout=1)

        mockclient.send.assert_called_once_with("custom:after retry")

    def test_protocol_error_stops_the_relay(self, sockets, pubsub):
        from redis.exceptions import ResponseError

        pubsub.listen.side_effect = ResponseError("bad command")
        channel = sockets.Channel("custom")

        with patch.object(sockets.gevent, "sleep") as sleep:
            channel.listen()

        # Retrying would raise the same error, so the relay gives up.
        sleep.assert_not_called()
        assert pubsub.listen.call_count == 1
        pubsub.close.assert_called_once_with()

    @pytest.mark.timeout(10)
    def test_stop_closes_pubsub(self, sockets, pubsub, mockclient):
        pubsub.listen.side_effect = parking_listen
        channel = sockets.Channel("custom")
        channel.subscribe(mockclient)
        channel.start()
        gevent.sleep(0)

        channel.stop()

        pubsub.close.assert_called_once_with()

    def test_one_traceback_per_outage(self, sockets, pubsub, mockclient):
        def flaky_stream():
            yield {"type": "message", "channel": b"custom", "data": b"back"}
            raise sockets.ConnectionError("dropped again")

        pubsub.listen.side_effect = [
            sockets.ConnectionError("one"),
            sockets.ConnectionError("two"),
            flaky_stream(),
            iter([]),
        ]
        channel = sockets.Channel("custom")
        channel.subscribe(mockclient)

        logger = sockets.app.logger
        with (
            patch.object(logger, "exception") as traceback,
            patch.object(logger, "warning") as oneliner,
            patch.object(sockets.gevent, "sleep"),
        ):
            channel.listen()

        # Two outages, so two tracebacks; the repeat inside the first is a
        # single line, and a delivered message resets the count.
        assert traceback.call_count == 2
        assert oneliner.call_count == 1

    def test_resubscribe_confirmation_does_not_reset_the_backoff(self, sockets, pubsub):
        def flapping_stream():
            yield {"type": "subscribe", "channel": b"custom", "data": 1}
            raise sockets.ConnectionError("dropped again")

        pubsub.listen.side_effect = [
            sockets.ConnectionError("one"),
            flapping_stream(),
            iter([]),
        ]
        channel = sockets.Channel("custom")
        channel.RECONNECT_DELAY_SECS = 1
        channel.MAX_RECONNECT_DELAY_SECS = 8
        delays = []

        logger = sockets.app.logger
        with (
            patch.object(logger, "exception") as traceback,
            patch.object(logger, "warning") as oneliner,
            patch.object(sockets.gevent, "sleep", delays.append),
        ):
            channel.listen()

        # The zeroes are the loop's cooperative yields, not retry waits.
        assert [d for d in delays if d] == [1, 2]
        assert traceback.call_count == 1
        assert oneliner.call_count == 1

    @pytest.mark.timeout(10)
    def test_relay_loop_yields_between_buffered_messages(
        self, sockets, pubsub, mockclient
    ):
        order = []

        def buffered_stream():
            for payload in (b"one", b"two"):
                order.append("read {}".format(payload.decode("utf-8")))
                yield {"type": "message", "channel": b"custom", "data": payload}

        pubsub.listen.side_effect = buffered_stream
        mockclient.send.side_effect = order.append
        channel = sockets.Channel("custom")
        channel.subscribe(mockclient)

        channel.start()
        gevent.wait([channel.greenlet], timeout=1)

        # ``relay`` only spawns senders, and a burst already in the socket
        # buffer reads without blocking, so the sends run only if the loop
        # hands the hub back between messages.
        assert order == ["read one", "custom:one", "read two", "custom:two"]

    def test_protocol_error_on_subscribe_stops_the_relay(self, sockets, pubsub):
        from redis.exceptions import ResponseError

        pubsub.subscribe.side_effect = ResponseError("bad channel")

        with patch.object(sockets.gevent, "sleep") as sleep:
            sockets.Channel("custom").listen()

        # Retrying would raise the same error, so the relay gives up.
        sleep.assert_not_called()
        pubsub.listen.assert_not_called()
        pubsub.close.assert_called_once_with()

    @pytest.mark.timeout(10)
    def test_relay_loop_yields_while_waiting(self, sockets, pubsub, mockclient):
        message_ready = Event()

        def blocking_listen():
            message_ready.wait()
            yield {"type": "message", "channel": b"custom", "data": b"payload"}

        pubsub.listen.side_effect = blocking_listen
        channel = sockets.Channel("custom")
        channel.subscribe(mockclient)
        order = []

        channel.start()
        gevent.spawn(order.append, "other greenlet")
        gevent.sleep(0)

        # The relay is parked inside ``pubsub.listen()``, so the hub was free
        # to run another greenlet without an explicit sleep in the loop.
        assert order == ["other greenlet"]
        assert not channel.greenlet.ready()

        message_ready.set()
        gevent.wait([channel.greenlet], timeout=1)

        assert channel.greenlet.ready()
        mockclient.send.assert_called_once_with("custom:payload")

    def test_stop(self, channel):
        channel.start()
        channel.stop()
        assert channel.greenlet is None

    def test_subscribe_sends_control_message(self, sockets, mockclient):
        channel = sockets.Channel("custom")
        channel.subscribe(mockclient)
        # Calling subscribe sends a control message
        assert sockets.redis_conn.publish.call_count == 1
        assert sockets.redis_conn.publish.mock_calls[0].args[0] == "dallinger_control"
        msg_data = json.loads(sockets.redis_conn.publish.mock_calls[0].args[1])
        assert msg_data["type"] == "channel"
        assert msg_data["event"] == "subscribed"
        assert msg_data["channel"] == "custom"

    def test_unsubscribe_sends_control_message(self, sockets, mockclient):
        channel = sockets.Channel("custom")
        channel.subscribe(mockclient)
        channel.unsubscribe(mockclient)

        # Calling unsubscribe sends a control message
        assert sockets.redis_conn.publish.call_count == 2
        assert sockets.redis_conn.publish.mock_calls[1].args[0] == "dallinger_control"
        msg_data = json.loads(sockets.redis_conn.publish.mock_calls[1].args[1])
        assert msg_data["type"] == "channel"
        assert msg_data["event"] == "unsubscribed"
        assert msg_data["channel"] == "custom"


class TestChatBackend:
    def test_subscribe_to_new_channel_registers_client_for_channel(
        self, chat, mockclient
    ):
        chat.subscribe(mockclient, "custom")
        assert mockclient in chat.channels["custom"].clients

    def test_subscribe_wont_duplicate_channel(
        self, sockets, chat, channel, pubsub, mockclient
    ):
        chat.subscribe(mockclient, channel.name)
        pubsub.subscribe.assert_not_called()

    def test_unsubscribe_drops_emptied_channel(self, chat, mockclient):
        chat.subscribe(mockclient, "quorum")
        chat.unsubscribe(mockclient)
        assert "quorum" not in chat.channels

    @pytest.mark.timeout(10)
    def test_concurrent_unsubscribe_does_not_raise(
        self, sockets, chat, pubsub, mockclient
    ):
        other = Mock()
        other.client_info.return_value = '{"class": "MockClient"}'
        pubsub.listen.side_effect = parking_listen
        # A real publish is a socket write, so it reaches the hub.
        sockets.redis_conn.publish.side_effect = lambda *args: gevent.sleep(0)
        chat.subscribe(mockclient, "quorum")
        chat.subscribe(other, "quorum")
        gevent.sleep(0)

        unsubscribes = [
            gevent.spawn(chat.unsubscribe, mockclient),
            gevent.spawn(chat.unsubscribe, other),
        ]
        gevent.joinall(unsubscribes, timeout=5)

        assert [g.exception for g in unsubscribes] == [None, None]
        assert "quorum" not in chat.channels

    @pytest.mark.timeout(10)
    def test_subscribe_during_unsubscribe_gets_a_live_channel(
        self, sockets, chat, pubsub, mockclient
    ):
        late = Mock()
        late.client_info.return_value = '{"class": "MockClient"}'
        pubsub.listen.side_effect = parking_listen
        chat.subscribe(mockclient, "quorum")
        doomed = chat.channels["quorum"]
        gevent.sleep(0)

        racers = [
            gevent.spawn(chat.unsubscribe, mockclient),
            gevent.spawn(chat.subscribe, late, "quorum"),
        ]
        gevent.joinall(racers, timeout=5)

        assert late not in doomed.clients
        assert chat.channels["quorum"].clients == [late]
        assert chat.channels["quorum"].greenlet is not None

        chat.channels["quorum"].stop()

    @pytest.mark.timeout(10)
    def test_unsubscribe_drops_channel_when_control_publish_fails(
        self, sockets, chat, pubsub, mockclient
    ):
        pubsub.listen.side_effect = parking_listen
        chat.subscribe(mockclient, "quorum")
        gevent.sleep(0)
        channel = chat.channels["quorum"]
        sockets.redis_conn.publish.side_effect = sockets.ConnectionError("no redis")

        chat.unsubscribe(mockclient)

        assert "quorum" not in chat.channels
        assert channel.greenlet is None

    def test_unsubscribe_keeps_channel_with_remaining_clients(self, chat, mockclient):
        other = Mock()
        other.client_info.return_value = '{"class": "MockClient"}'
        chat.subscribe(mockclient, "quorum")
        chat.subscribe(other, "quorum")

        chat.unsubscribe(mockclient)

        assert chat.channels["quorum"].clients == [other]

    def test_channel_that_stops_listening_is_dropped(self, chat, sockets, pubsub):
        from redis.exceptions import ResponseError

        pubsub.listen.side_effect = ResponseError("bad command")
        chat.channels["quorum"] = channel = sockets.Channel("quorum")

        channel.listen()

        assert "quorum" not in chat.channels

    def test_forget_keeps_a_channel_replaced_under_the_same_name(self, chat, sockets):
        dead = sockets.Channel("quorum")
        chat.channels["quorum"] = live = sockets.Channel("quorum")

        chat.forget(dead)

        assert chat.channels["quorum"] is live

    @pytest.mark.timeout(10)
    def test_subscribe_after_a_dead_listener_gets_a_live_one(
        self, chat, sockets, pubsub, mockclient
    ):
        from redis.exceptions import ResponseError

        pubsub.listen.side_effect = ResponseError("bad command")
        chat.subscribe(mockclient, "quorum")
        gevent.wait(timeout=1)

        pubsub.listen.side_effect = None
        pubsub.listen.return_value = [
            {"type": "message", "channel": b"quorum", "data": b"back"}
        ]
        late = Mock()
        late.client_info.return_value = '{"class": "MockClient"}'
        chat.subscribe(late, "quorum")
        gevent.wait(timeout=1)

        # The dead channel is gone, so this client is relaying on a new one.
        late.send.assert_called_once_with("quorum:back")
        mockclient.send.assert_not_called()


@pytest.mark.slow
class TestClient:
    def test_send(self, client):
        client.send("message")
        client.ws.send.assert_called_once_with("message")

    def test_publish_sends_control_message(self, sockets, client):
        # Disconnect client to prevent the loop
        client.ws.connected = False
        client.publish()

        # Calling publish sends a control message about the WebSocket connection
        assert sockets.redis_conn.publish.call_count == 1
        assert sockets.redis_conn.publish.mock_calls[0].args[0] == "dallinger_control"
        msg_data = json.loads(sockets.redis_conn.publish.mock_calls[0].args[1])
        assert msg_data["type"] == "websocket"
        assert msg_data["event"] == "connected"

    def test_teardown_covers_the_connected_event(self, sockets, chat, mocksocket):
        client = sockets.Client(mocksocket)
        chat.subscribe(client, "special")
        events = []

        def fail_on_connect(payload):
            events.append(payload["event"])
            if payload["event"] == "connected":
                raise RuntimeError("boom")

        with patch.object(sockets, "publish_control_event", fail_on_connect):
            with pytest.raises(RuntimeError):
                client.publish()

        # ``chat()`` subscribes before calling ``publish()``, so a failure
        # anywhere inside it still has to unsubscribe.
        assert events == ["connected", "unsubscribed"]
        assert "special" not in chat.channels

    def test_send_exception_unsubscribes_client(self, client, channel):
        client.ws.send.side_effect = socket.error()
        client.ws.close_reason = "Socket Error"
        client.ws.close_message = "SimulatedError"
        channel.subscribe(client)
        with pytest.raises(ConnectionClosed) as e:
            client.send("message")
            assert e.reason == "Socket Error"
            assert e.message == "SimulatedError"
        assert client not in channel.clients

    def test_connection_closed_unsubscribes_client(self, client, channel):
        closed_error = ConnectionClosed("Closed Error", "Closed")
        client.ws.send.side_effect = closed_error
        channel.subscribe(client)
        with pytest.raises(ConnectionClosed) as e:
            client.send("message")
            assert e is closed_error
        assert client not in channel.clients

    def test_send_exception_sends_control_message(self, sockets, client, channel):
        closed_error = ConnectionClosed("Closed Error", "Closed")
        client.ws.send.side_effect = closed_error
        channel.subscribe(client)

        with pytest.raises(ConnectionClosed):
            client.send("message")

        # We should have three calls publishing messages on redis
        #
        # 1. The subscribe message on the control channel from
        #    ``TestChannel.test_subscribe_sends_control_message``
        # 2. The unsubscribe mesage on the control channel from
        #    ``TestChannel.test_unsubscribe_sends_control_message``
        # 3. A websocket disconnect message on the control channel resulting
        #    from the error raised in `ws.send()`

        assert sockets.redis_conn.publish.call_count == 3

        # Let's look at that second one
        assert sockets.redis_conn.publish.mock_calls[2].args[0] == "dallinger_control"
        msg_data = json.loads(sockets.redis_conn.publish.mock_calls[2].args[1])
        assert msg_data["type"] == "websocket"
        assert msg_data["event"] == "disconnected"

    def test_closed_socket_unsubscribes_client(self, client, channel):
        channel.subscribe(client)
        client.ws.connected = False

        client.publish()

        assert client not in channel.clients

    def test_message_without_channel_prefix_is_discarded(self, sockets, mocksocket):
        mocksocket.receive.return_value = "no separator here"

        sockets.Client(mocksocket).publish()

        # Only the "connected" control message; the malformed frame is dropped.
        assert sockets.redis_conn.publish.call_count == 1

    @pytest.mark.timeout(10)
    def test_message_with_empty_channel_prefix_is_discarded(self, sockets, mocksocket):
        mocksocket.receive.return_value = ":payload"

        sockets.Client(mocksocket).publish()

        # Only the "connected" control message; redis would accept a publish
        # to "" and no one would ever read it.
        assert sockets.redis_conn.publish.call_count == 1

    def test_client_may_not_publish_to_the_control_channel(self, sockets, mocksocket):
        mocksocket.receive.return_value = 'dallinger_control:{"event": "forged"}'

        sockets.Client(mocksocket).publish()

        # The only control-channel publish is the server's own "connected"
        # event; the client's frame was dropped.
        assert sockets.redis_conn.publish.call_count == 1
        sent = json.loads(sockets.redis_conn.publish.mock_calls[0].args[1])
        assert sent["event"] == "connected"

    @pytest.mark.timeout(10)
    def test_receive_loop_yields_while_waiting(self, sockets, yielding_socket):
        client = sockets.Client(yielding_socket)
        order = []

        publisher = gevent.spawn(client.publish)
        gevent.spawn(order.append, "other greenlet")
        gevent.sleep(0)

        # The loop is parked inside ``receive()``, so the hub was free to run
        # another greenlet without an explicit sleep before each read.
        assert order == ["other greenlet"]
        assert not publisher.ready()

        yielding_socket.message_ready.set()
        publisher.join(timeout=1)

        assert publisher.successful()
        assert sockets.redis_conn.publish.mock_calls[-1].args == (
            "custom",
            "delivered",
        )

    def test_receive_exception_unsubscribes_client(self, client, channel):
        closed_error = ConnectionClosed("Closed Error", "Closed")
        client.ws.receive.side_effect = closed_error
        channel.subscribe(client)
        with pytest.raises(ConnectionClosed) as e:
            client.publish()
            assert e is closed_error
        assert client not in channel.clients

    def test_receive_exception_sends_control_messages(self, sockets, client, channel):
        closed_error = ConnectionClosed("Closed Error", "Closed")
        client.ws.receive.side_effect = closed_error
        channel.subscribe(client)

        with pytest.raises(ConnectionClosed):
            client.publish()

        # We should have four calls publishing messages on redis
        #
        # 1. The subscribe message on the control channel from
        #    ``TestChannel.test_subscribe_sends_control_message``
        # 2. A websocket connected message on the control channel sent before
        #    entering the receive loop in `client.publish()`.
        #    See `TestClient.test_publish_control_messages`
        # 3. The unsubscribe mesage on the control channel from
        #    ``TestChannel.test_unsubscribe_sends_control_message``
        # 4. A websocket disconnected message on the control channel resulting
        #    from the error raised during `ws.receive()`.

        assert sockets.redis_conn.publish.call_count == 4

        # Let's check the third message with the websocket client disonnection
        # resulting from the error raised in `ws.receive()`
        assert sockets.redis_conn.publish.mock_calls[3].args[0] == "dallinger_control"
        msg_data = json.loads(sockets.redis_conn.publish.mock_calls[3].args[1])
        assert msg_data["type"] == "websocket"
        assert msg_data["event"] == "disconnected"


class TestChatEndpoint:
    def test_chat_subscribes_to_requested_channel(self, sockets, mocksocket):
        ws = mocksocket
        subscribed = []

        def record_subscription():
            subscribed.extend(
                c
                for c in sockets.chat_backend.channels["special"].clients
                if c.ws is ws
            )
            return None

        ws.receive = Mock(side_effect=record_subscription)
        sockets.request = Mock()
        sockets.request.args = {"channel": "special"}
        sockets.chat(ws)

        assert len(subscribed) == 1

    def test_chat_unsubscribes_when_socket_closes(self, sockets, mocksocket):
        ws = mocksocket
        ws.receive.return_value = None
        sockets.request = Mock()
        sockets.request.args = {"channel": "special"}

        sockets.chat(ws)

        assert "special" not in sockets.chat_backend.channels

    def test_chat_publishes_message_to_requested_channel(self, sockets, mocksocket):
        ws = mocksocket
        ws.receive.return_value = "special:incoming message!"
        sockets.request = Mock()
        sockets.request.args = {"channel": "special"}
        sockets.chat(ws)

        relayed = [
            call.args
            for call in sockets.redis_conn.publish.mock_calls
            if call.args[0] != sockets.CONTROL_CHANNEL
        ]
        assert relayed == [("special", "incoming message!")]


@pytest.mark.slow
class TestExperimentSocket:
    def sync_client(self, sockets, ws, experiment, **kwargs):
        return sockets.Client(ws, experiment=experiment, **kwargs)

    def relayed(self, sockets):
        """Everything published to redis but the connect/disconnect events."""
        return [
            call.args
            for call in sockets.redis_conn.publish.mock_calls
            if call.args[0] != sockets.CONTROL_CHANNEL
        ]

    def test_frame_reaches_the_experiment_and_not_redis(self, sockets, scripted_socket):
        exp = Mock()
        client = self.sync_client(
            sockets,
            scripted_socket('game:{"action": "rock"}'),
            exp,
            participant_id="42",
            scope="page-7",
        )

        client.publish()

        call = exp.handle_websocket_message.mock_calls[0]
        assert call.args == ('{"action": "rock"}',)
        assert call.kwargs["channel_name"] == "game"
        assert call.kwargs["participant_id"] == "42"
        assert call.kwargs["scope"] == "page-7"
        # Comparable with a Dallinger DateTime column, which is naive.
        assert call.kwargs["receive_time"].tzinfo is None
        assert self.relayed(sockets) == []

    def test_session_is_removed_after_every_frame(self, sockets, scripted_socket):
        exp = Mock()
        client = self.sync_client(sockets, scripted_socket("game:one", "game:two"), exp)

        with patch.object(sockets, "session") as session:
            client.publish()

        assert exp.handle_websocket_message.call_count == 2
        assert session.remove.call_count == 2

    def test_failing_handler_keeps_the_connection_open(self, sockets, scripted_socket):
        exp = Mock()
        exp.handle_websocket_message.side_effect = [ValueError("boom"), None]
        client = self.sync_client(sockets, scripted_socket("game:one", "game:two"), exp)

        with patch.object(sockets, "session") as session:
            with patch.object(sockets.app, "logger") as logger:
                client.publish()

        assert exp.handle_websocket_message.call_count == 2
        assert session.remove.call_count == 2
        logger.exception.assert_called_once()

    def test_binary_frame_closes_the_connection(self, sockets, scripted_socket):
        exp = Mock()
        ws = scripted_socket(b'game:{"action": "rock"}', "game:never read")
        client = self.sync_client(sockets, ws, exp)

        client.publish()

        ws.close.assert_called_once_with(
            sockets.UNSUPPORTED_DATA_CLOSE_CODE, "text frames only"
        )
        exp.handle_websocket_message.assert_not_called()
        assert ws.receive.call_count == 1

    def test_binary_frame_announces_the_disconnect(self, sockets, scripted_socket):
        client = self.sync_client(sockets, scripted_socket(b"game:payload"), Mock())

        client.publish()

        events = [
            json.loads(call.args[1])
            for call in sockets.redis_conn.publish.mock_calls
            if call.args[0] == sockets.CONTROL_CHANNEL
        ]
        assert [event["event"] for event in events] == ["connected", "disconnected"]
        assert events[-1]["reason"] == sockets.UNSUPPORTED_DATA_CLOSE_CODE
        assert events[-1]["message"] == "text frames only"

    def test_binary_frame_closes_under_the_send_lock(self, sockets, scripted_socket):
        # ``send`` and ``close`` write to the same socket with no coordination
        # of their own inside simple_websocket, and a relay greenlet spawned by
        # ``Channel.relay`` can be inside ``send`` when this close runs.
        ws = scripted_socket(b"game:payload")
        client = sockets.Client(ws)
        held = []
        ws.close.side_effect = lambda *args: held.append(client.send_lock.locked())

        client.publish()

        assert held == [True]

    def test_control_channel_frame_never_reaches_the_handler(
        self, sockets, scripted_socket
    ):
        exp = Mock()
        client = self.sync_client(
            sockets, scripted_socket('dallinger_control:{"event": "forged"}'), exp
        )

        client.publish()

        exp.handle_websocket_message.assert_not_called()

    def test_malformed_frame_never_reaches_the_handler(self, sockets, scripted_socket):
        exp = Mock()
        client = self.sync_client(sockets, scripted_socket("no separator"), exp)

        client.publish()

        exp.handle_websocket_message.assert_not_called()

    def test_handler_can_restore_the_broadcast(self, sockets, scripted_socket):
        from dallinger import db
        from dallinger.experiment import Experiment

        class Republishing(Experiment):
            def __init__(self):
                # Experiment.__init__ wants a database; only the publish path
                # is under test here.
                pass

            def handle_websocket_message(self, message, *, channel_name, **kwargs):
                self.publish_to_subscribers(message, "chat_broadcast")

        frame = 'chat:{"text": "hi"}'

        sockets.Client(scripted_socket(frame)).publish()
        relayed_payload = self.relayed(sockets)[0][1]
        sockets.redis_conn.publish.reset_mock()

        client = self.sync_client(sockets, scripted_socket(frame), Republishing())
        with patch.object(db, "redis_conn", sockets.redis_conn):
            client.publish()

        # Subscribers get the payload the relay would have sent them, on a
        # channel the experiment is not itself subscribed to.
        assert self.relayed(sockets) == [("chat_broadcast", relayed_payload)]

    def test_a_client_without_an_experiment_relays_to_redis(
        self, sockets, scripted_socket
    ):
        client = sockets.Client(scripted_socket("game:payload"))

        client.publish()

        assert sockets.redis_conn.publish.mock_calls[-1].args == ("game", "payload")


@pytest.mark.slow
class TestClientInfo:
    def test_reports_the_connection_scope(self, sockets):
        client = sockets.Client(
            Mock(), worker_id="w1", participant_id="42", scope="page-7"
        )

        assert client.client_info() == {
            "class": "dallinger.experiment_server.sockets.Client",
            "worker_id": "w1",
            "participant_id": "42",
            "scope": "page-7",
        }

    def test_control_events_carry_the_scope(self, sockets, scripted_socket):
        # An experiment tracking connections sees the scope at connect time,
        # not only once that connection sends a frame.
        with patch.object(
            sockets, "request", Mock(args={"channel": "special", "scope": "page-7"})
        ):
            sockets.chat(scripted_socket())

        events = [
            json.loads(call.args[1])
            for call in sockets.redis_conn.publish.mock_calls
            if call.args[0] == sockets.CONTROL_CHANNEL
        ]
        assert events
        assert all(event["client"]["scope"] == "page-7" for event in events)


def channel_events(sockets):
    """The subscribe/unsubscribe bookkeeping a channel announces."""
    return [
        json.loads(call.args[1])["event"]
        for call in sockets.redis_conn.publish.mock_calls
        if call.args[0] == sockets.CONTROL_CHANNEL
        and json.loads(call.args[1])["type"] == "channel"
    ]


@pytest.mark.slow
class TestChannellessConnection:
    """A connection that names no channel sends without receiving."""

    def connect(self, sockets, ws, **args):
        with patch.object(sockets, "request", Mock(args=args)):
            sockets.chat(ws)

    @pytest.mark.parametrize("args", [{}, {"channel": ""}], ids=["absent", "empty"])
    def test_no_channel_builds_no_channel(self, sockets, scripted_socket, args):
        self.connect(sockets, scripted_socket("game:payload"), **args)

        assert channel_events(sockets) == []

    def test_a_named_channel_still_builds_one(self, sockets, scripted_socket):
        self.connect(sockets, scripted_socket("game:payload"), channel="special")

        assert channel_events(sockets) == ["subscribed", "unsubscribed"]

    def test_frames_are_still_relayed(self, sockets, scripted_socket):
        self.connect(sockets, scripted_socket("game:payload"))

        relayed = [
            call.args
            for call in sockets.redis_conn.publish.mock_calls
            if call.args[0] != sockets.CONTROL_CHANNEL
        ]
        assert relayed == [("game", "payload")]


@pytest.mark.slow
class TestExperimentSocketConnection:
    def connect(self, sockets, ws, **args):
        with patch.object(sockets, "request", Mock(args=args)):
            sockets.experiment_socket(ws)

    def connect_chat(self, sockets, ws, **args):
        with patch.object(sockets, "request", Mock(args=args)):
            sockets.chat(ws)

    def test_unknown_participant_is_refused(self, sockets, mocksocket):
        with patch.object(sockets, "resolve_participant_id", return_value=None):
            with patch.object(sockets, "Experiment") as experiment_factory:
                self.connect(
                    sockets,
                    mocksocket,
                    channel="special",
                    participant_id="999",
                )

        mocksocket.close.assert_called_once_with(
            sockets.REFUSED_CLOSE_CODE, "unknown participant"
        )
        experiment_factory.assert_not_called()
        assert "special" not in sockets.chat_backend.channels

    def test_the_chat_route_still_relays(self, sockets, scripted_socket):
        ws = scripted_socket("special:payload")
        self.connect_chat(sockets, ws, channel="special")

        ws.close.assert_not_called()
        relayed = [
            call.args
            for call in sockets.redis_conn.publish.mock_calls
            if call.args[0] != sockets.CONTROL_CHANNEL
        ]
        assert relayed == [("special", "payload")]

    def test_lookup_failure_asks_the_client_to_retry(self, sockets, mocksocket):
        from sqlalchemy.exc import OperationalError

        failure = OperationalError("SELECT 1", {}, Exception("no server"))
        with patch.object(sockets, "resolve_participant_id", side_effect=failure):
            with patch.object(sockets, "Experiment") as experiment_factory:
                self.connect(
                    sockets,
                    mocksocket,
                    channel="special",
                    participant_id="42",
                )

        mocksocket.close.assert_called_once_with(
            sockets.UNAVAILABLE_CLOSE_CODE, "participant lookup failed"
        )
        experiment_factory.assert_not_called()

    def test_known_participant_gets_an_experiment(self, sockets, scripted_socket):
        ws = scripted_socket("special:payload")
        with patch.object(sockets, "resolve_participant_id", return_value="42"):
            with patch.object(sockets, "Experiment") as experiment_factory:
                self.connect(
                    sockets,
                    ws,
                    channel="special",
                    participant_id="42",
                    scope="page-7",
                )

        ws.close.assert_not_called()
        experiment_factory.assert_called_once_with()
        exp = experiment_factory.return_value
        call = exp.handle_websocket_message.mock_calls[0]
        assert call.kwargs["scope"] == "page-7"
        # The parsed id rendered back, not the query string it came from.
        assert call.kwargs["participant_id"] == "42"

    def test_building_the_experiment_releases_the_session(
        self, sockets, scripted_socket
    ):
        ws = scripted_socket()
        with patch.object(sockets, "resolve_participant_id", return_value="42"):
            with patch.object(sockets, "Experiment"):
                with patch.object(sockets, "session") as session:
                    self.connect(
                        sockets,
                        ws,
                        channel="special",
                        participant_id="42",
                    )

        # configure() may have queried, and this connection can now idle in
        # receive() indefinitely.
        session.remove.assert_called_once_with()

    def test_connections_share_one_experiment(self, sockets, scripted_socket):
        with patch.object(sockets, "resolve_participant_id", return_value="42"):
            with patch.object(sockets, "Experiment") as experiment_factory:
                for _ in range(3):
                    self.connect(
                        sockets,
                        scripted_socket("special:payload"),
                        channel="special",
                        participant_id="42",
                    )

        experiment_factory.assert_called_once_with()
        exp = experiment_factory.return_value
        assert exp.handle_websocket_message.call_count == 3

    def test_two_greenlets_build_one_experiment(self, sockets):
        built = []

        def build():
            # Experiment.__init__ runs configure(), which is experiment code
            # and may query, so the constructor can yield here.
            gevent.sleep(0)
            built.append(Mock())
            return built[-1]

        with patch.object(sockets, "Experiment", side_effect=build):
            greenlets = [gevent.spawn(sockets.process_experiment) for _ in range(2)]
            gevent.joinall(greenlets)

        assert len(built) == 1
        assert [g.value for g in greenlets] == [built[0], built[0]]

    def test_a_experiment_socket_still_subscribes_to_its_channel(
        self, sockets, scripted_socket
    ):
        # A experiment socket changes the inbound direction only, so broadcasts to
        # ``channel`` still have to reach the browser.
        with patch.object(sockets, "resolve_participant_id", return_value="42"):
            with patch.object(sockets, "Experiment"):
                self.connect(
                    sockets,
                    scripted_socket("special:payload"),
                    channel="special",
                    participant_id="42",
                )

        assert channel_events(sockets) == ["subscribed", "unsubscribed"]

    def test_a_failed_experiment_releases_the_session(self, sockets, mocksocket):
        with patch.object(sockets, "resolve_participant_id", return_value="42"):
            with patch.object(sockets, "Experiment", side_effect=ValueError("boom")):
                with patch.object(sockets, "session") as session:
                    self.connect(
                        sockets,
                        mocksocket,
                        channel="special",
                        participant_id="42",
                    )

        # configure() may have queried before raising.
        session.remove.assert_called_once_with()

    def test_a_failed_experiment_is_not_cached(self, sockets, mocksocket):
        with patch.object(sockets, "resolve_participant_id", return_value="42"):
            with patch.object(sockets, "Experiment", side_effect=ValueError("boom")):
                self.connect(
                    sockets,
                    mocksocket,
                    channel="special",
                    participant_id="42",
                )

        mocksocket.close.assert_called_once_with(
            sockets.UNAVAILABLE_CLOSE_CODE, "experiment unavailable"
        )
        assert sockets._process_experiment is None
        assert "special" not in sockets.chat_backend.channels

    def test_the_chat_route_does_not_look_up_the_participant(self, sockets, mocksocket):
        with patch.object(sockets, "resolve_participant_id") as lookup:
            self.connect_chat(
                sockets, mocksocket, channel="special", participant_id="nonsense"
            )

        lookup.assert_not_called()


class TestNormalizedParticipantId:
    @pytest.mark.parametrize(
        "given, expected",
        [
            ("42", "42"),
            (42, "42"),
            (b"42", "42"),
            ("  42  ", "42"),
            ("042", "42"),
            ("+42", "42"),
            ("-42", "-42"),
            ("\u0664\u0662", "42"),
        ],
    )
    def test_a_whole_number_is_its_parsed_form(self, sockets, given, expected):
        assert sockets.normalized_participant_id(given) == expected

    @pytest.mark.parametrize("given", [12.7, 12.0, float("inf"), Decimal("12")])
    def test_a_number_that_is_not_an_integer_is_refused(self, sockets, given):
        # int() reads 12.7 as 12, and raises OverflowError rather than
        # ValueError on an infinity.
        assert sockets.normalized_participant_id(given) is None

    def test_a_boolean_is_refused(self, sockets):
        # bool is an int subclass, so int(True) is 1.
        assert sockets.normalized_participant_id(True) is None

    @pytest.mark.parametrize(
        "given", ["", "not-a-number", "12.7", None, [42], object()]
    )
    def test_an_unparseable_value_is_refused(self, sockets, given):
        assert sockets.normalized_participant_id(given) is None

    def test_an_integer_that_is_not_an_int_is_parsed(self, sockets):
        """A numpy integer out of a dataframe column takes this path."""

        class Counted:
            def __int__(self):
                return 42

        numbers.Integral.register(Counted)

        assert sockets.normalized_participant_id(Counted()) == "42"


@pytest.mark.slow
class TestResolveParticipantId:
    def test_a_number_that_is_not_an_integer_is_not_a_lookup(self, sockets):
        with patch.object(sockets, "session") as session:
            assert sockets.resolve_participant_id(12.7) is None

        session.query.assert_not_called()

    def test_non_numeric_id_is_not_a_lookup(self, sockets):
        with patch.object(sockets, "session") as session:
            assert sockets.resolve_participant_id("not-a-number") is None

        session.query.assert_not_called()

    def test_missing_id_is_not_a_lookup(self, sockets):
        with patch.object(sockets, "session") as session:
            assert sockets.resolve_participant_id(None) is None

        session.query.assert_not_called()

    def test_a_failed_query_still_releases_the_session(self, sockets):
        from sqlalchemy.exc import OperationalError

        with patch.object(sockets, "session") as session:
            session.query.side_effect = OperationalError(
                "SELECT 1", {}, Exception("no server")
            )

            with pytest.raises(OperationalError):
                sockets.resolve_participant_id("42")

        session.remove.assert_called_once_with()


@pytest.mark.slow
class TestResolveParticipantIdAgainstTheDatabase:
    """The lookup against a real participant table, not a mocked session."""

    def test_finds_a_real_participant(self, sockets, a):
        # resolve_participant_id calls session.remove(), which detaches
        # anything built here, so read the id before the lookup.
        participant_id = a.participant().id

        assert sockets.resolve_participant_id(str(participant_id)) == str(
            participant_id
        )

    def test_absent_id_is_unknown(self, sockets, a):
        participant_id = a.participant().id

        assert sockets.resolve_participant_id(str(participant_id + 1000)) is None

    def test_non_ascii_digits_yield_the_parsed_id(self, sockets, a):
        participant_id = a.participant().id
        arabic_indic = str(participant_id).translate(
            str.maketrans(
                "0123456789",
                "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669",
            )
        )

        # int() accepts these. The raw string reaching the column instead
        # would raise DataError on every query made with it.
        assert sockets.resolve_participant_id(arabic_indic) == str(participant_id)


def published_envelopes(sockets):
    """Every directed-send envelope published to redis, as JSON strings."""
    return [
        call.args[1]
        for call in sockets.redis_conn.publish.mock_calls
        if call.args[0] == sockets.DIRECT_CHANNEL
    ]


def sockets_envelope_fields():
    from dallinger.experiment_server import sockets

    return sockets.ENVELOPE_FIELDS


#: A well formed envelope from another process, for tests that vary one field.
DIRECT_ENVELOPE = {
    "participant_ids": ["42"],
    "scope": None,
    "origin": "another process",
    "payload": '{"type": "wake"}',
}


def envelope_message(sockets, envelope):
    """The pubsub frame another process reads for a published envelope."""
    return {
        "type": "message",
        "channel": sockets.DIRECT_CHANNEL.encode("utf-8"),
        "data": envelope.encode("utf-8"),
    }


class TestParticipantRegistry:
    def test_a_chat_connection_is_addressable(self, sockets, mocksocket):
        addressed = []
        mocksocket.receive = Mock(
            side_effect=lambda: addressed.append(
                dict(sockets.chat_backend.clients_by_participant)
            )
        )

        with patch.object(sockets, "request", Mock(args={"participant_id": "42"})):
            sockets.chat(mocksocket)

        assert list(addressed[0]) == ["42"]

    def test_a_connection_without_a_participant_is_not_addressable(
        self, sockets, mocksocket
    ):
        addressed = []
        mocksocket.receive = Mock(
            side_effect=lambda: addressed.append(
                dict(sockets.chat_backend.clients_by_participant)
            )
        )

        with patch.object(sockets, "request", Mock(args={"channel": "special"})):
            sockets.chat(mocksocket)

        assert addressed == [{}]
        assert sockets.chat_backend.direct_channel is None

    def test_an_experiment_socket_is_addressable(self, sockets, mocksocket):
        addressed = []
        mocksocket.receive = Mock(
            side_effect=lambda: addressed.append(
                dict(sockets.chat_backend.clients_by_participant)
            )
        )

        with (
            patch.object(sockets, "resolve_participant_id", return_value="42"),
            patch.object(sockets, "process_experiment", return_value=Mock()),
            patch.object(sockets, "request", Mock(args={"participant_id": "42"})),
        ):
            sockets.experiment_socket(mocksocket)

        assert list(addressed[0]) == ["42"]

    def test_a_closed_connection_is_no_longer_addressable(self, sockets, mocksocket):
        with patch.object(sockets, "request", Mock(args={"participant_id": "42"})):
            sockets.chat(mocksocket)

        assert sockets.chat_backend.clients_by_participant == {}

    def test_a_failed_send_stops_addressing_the_connection(self, sockets, registered):
        client = registered("42")
        client.ws.send.side_effect = socket.error("broken pipe")

        with pytest.raises(ConnectionClosed):
            client.send("dallinger_direct:{}")

        assert sockets.chat_backend.clients_by_participant == {}

    @pytest.mark.parametrize(
        "named", ["012", " 42 ", "42"], ids=["padded", "spaced", "plain"]
    )
    def test_an_id_is_addressed_by_its_parsed_value(self, sockets, registered, named):
        registered(named)

        assert list(sockets.chat_backend.clients_by_participant) == [str(int(named))]

    def test_an_unparseable_id_is_not_addressable(self, sockets, registered):
        registered("not-a-number")

        assert sockets.chat_backend.clients_by_participant == {}

    def test_every_connection_of_one_participant_is_kept(self, sockets, registered):
        first = registered("42")
        second = registered("42")

        assert sockets.chat_backend.clients_by_participant["42"] == {first, second}

    def test_deregistering_one_connection_keeps_the_others(self, sockets, registered):
        first = registered("42")
        second = registered("42")

        sockets.chat_backend.deregister(first)

        assert sockets.chat_backend.clients_by_participant["42"] == {second}

    def test_a_subscriber_that_is_not_a_connection_is_not_addressable(self, sockets):
        # ``on_launch`` subscribes the experiment to its own channels through
        # the same backend, and an ``Experiment`` has no ``addressable_id``.
        experiment = Mock(spec=["client_info", "send"])

        sockets.chat_backend.register(experiment)
        sockets.chat_backend.unsubscribe(experiment)

        assert sockets.chat_backend.clients_by_participant == {}

    def test_the_listener_starts_with_the_first_addressable_client(
        self, sockets, registered, pubsub
    ):
        pubsub.listen.side_effect = parking_listen
        registered("42")

        assert isinstance(sockets.chat_backend.direct_channel, sockets.DirectChannel)

    def test_a_second_client_joins_the_running_listener(
        self, sockets, registered, pubsub
    ):
        pubsub.listen.side_effect = parking_listen
        registered("42")
        listener = sockets.chat_backend.direct_channel

        registered("43")

        # A listener per registration would relay every envelope once per
        # listener.
        assert sockets.chat_backend.direct_channel is listener

    def test_the_listener_outlives_the_last_one(self, sockets, registered, pubsub):
        pubsub.listen.side_effect = parking_listen
        client = registered("42")
        listener = sockets.chat_backend.direct_channel

        sockets.chat_backend.deregister(client)

        # Stopping here would leave a registration during ``Greenlet.kill``
        # either attached to a dying listener or served by a second one.
        assert sockets.chat_backend.direct_channel is listener

    def test_a_client_arriving_after_a_dead_listener_gets_a_live_one(
        self, sockets, registered
    ):
        registered("42")
        first = sockets.chat_backend.direct_channel
        gevent.wait(timeout=1)

        assert sockets.chat_backend.direct_channel is None

        registered("43")

        assert sockets.chat_backend.direct_channel is not first


class TestDirectedSend:
    def test_the_named_participant_receives_the_payload(self, sockets, registered):
        client = registered("42")

        sockets.publish_to_participants({"type": "wake"}, [42])
        gevent.wait(timeout=1)

        client.ws.send.assert_called_once_with('dallinger_direct:{"type": "wake"}')

    def test_other_participants_receive_nothing(self, sockets, registered):
        other = registered("43")

        sockets.publish_to_participants({"type": "wake"}, [42])
        gevent.wait(timeout=1)

        other.ws.send.assert_not_called()

    def test_every_connection_of_the_participant_receives_it(self, sockets, registered):
        first = registered("42")
        second = registered("42")

        sockets.publish_to_participants({"type": "wake"}, [42])
        gevent.wait(timeout=1)

        assert first.ws.send.call_count == 1
        assert second.ws.send.call_count == 1

    def test_an_id_is_matched_by_its_parsed_value(self, sockets, registered):
        client = registered("012")

        sockets.publish_to_participants({"type": "wake"}, ["12"])
        gevent.wait(timeout=1)

        assert client.ws.send.call_count == 1

    def test_a_single_id_needs_no_list(self, sockets, registered):
        client = registered("42")

        sockets.publish_to_participants({"type": "wake"}, 42)
        gevent.wait(timeout=1)

        assert client.ws.send.call_count == 1

    def test_a_repeated_id_delivers_once(self, sockets, registered):
        client = registered("42")

        sockets.publish_to_participants({"type": "wake"}, [42, "42", "042"])
        gevent.wait(timeout=1)

        assert client.ws.send.call_count == 1

    def test_a_scope_reaches_only_connections_opened_with_it(self, sockets, registered):
        current = registered("42", scope="page-7")
        stale = registered("42", scope="page-6")

        sockets.publish_to_participants({"type": "wake"}, [42], scope="page-7")
        gevent.wait(timeout=1)

        assert current.ws.send.call_count == 1
        stale.ws.send.assert_not_called()

    def test_a_scope_does_not_reach_a_connection_opened_without_one(
        self, sockets, registered
    ):
        unscoped = registered("42")

        sockets.publish_to_participants({"type": "wake"}, [42], scope="page-7")
        gevent.wait(timeout=1)

        # No scope is a scope of its own, not a wildcard.
        unscoped.ws.send.assert_not_called()

    def test_a_scope_that_is_not_text_is_compared_as_text(self, sockets, registered):
        # A connection names its scope in a query string, so it holds "7".
        client = registered("42", scope="7")

        sockets.publish_to_participants({"type": "wake"}, [42], scope=7)
        gevent.wait(timeout=1)

        client.ws.send.assert_called_once_with('dallinger_direct:{"type": "wake"}')

    def test_the_envelope_carries_a_scope_as_text(self, sockets, registered):
        registered("42", scope="7")

        sockets.publish_to_participants({"type": "wake"}, [42], scope=7)

        assert json.loads(published_envelopes(sockets)[0])["scope"] == "7"

    def test_no_scope_reaches_every_connection(self, sockets, registered):
        scoped = registered("42", scope="page-7")
        unscoped = registered("42")

        sockets.publish_to_participants({"type": "wake"}, [42])
        gevent.wait(timeout=1)

        assert scoped.ws.send.call_count == 1
        assert unscoped.ws.send.call_count == 1

    def test_the_envelope_reaches_the_other_processes(self, sockets, registered):
        registered("42")

        sockets.publish_to_participants({"type": "wake"}, [42, 43], scope="page-7")

        envelope = json.loads(published_envelopes(sockets)[0])
        assert envelope["participant_ids"] == ["42", "43"]
        assert envelope["scope"] == "page-7"
        assert envelope["origin"] == sockets.process_token()
        assert json.loads(envelope["payload"]) == {"type": "wake"}

    def test_a_failed_publish_reaches_nobody(self, sockets, registered):
        client = registered("42")
        sockets.redis_conn.publish.side_effect = sockets.RedisError("no redis")

        with pytest.raises(sockets.RedisError):
            sockets.publish_to_participants({"type": "wake"}, [42])
        gevent.wait(timeout=1)

        # Delivering locally first would serve this process and no other, and
        # a retry would then send to these connections twice.
        client.ws.send.assert_not_called()

    def test_the_payload_is_serialized_once(self, sockets, registered):
        client = registered("42")

        sockets.publish_to_participants({"type": "wake", "token": "abc"}, [42])
        gevent.wait(timeout=1)

        envelope = json.loads(published_envelopes(sockets)[0])
        frame = client.ws.send.mock_calls[0].args[0]
        assert frame == "{}:{}".format(sockets.DIRECT_CHANNEL, envelope["payload"])

    def test_a_datetime_in_the_payload_is_serialized(self, sockets, registered):
        client = registered("42")

        sockets.publish_to_participants({"at": datetime(2026, 9, 17, 12, 30)}, [42])
        gevent.wait(timeout=1)

        frame = client.ws.send.mock_calls[0].args[0]
        assert json.loads(frame.split(":", 1)[1]) == {"at": "2026-09-17T12:30:00"}

    def test_an_unaddressable_id_is_skipped(self, sockets, registered):
        client = registered("42")

        sockets.publish_to_participants({"type": "wake"}, ["not-a-number", 42])
        gevent.wait(timeout=1)

        assert client.ws.send.call_count == 1
        assert json.loads(published_envelopes(sockets)[0])["participant_ids"] == ["42"]

    def test_a_send_no_one_can_receive_publishes_nothing(self, sockets, registered):
        registered("42")

        sockets.publish_to_participants({"type": "wake"}, [None])

        assert published_envelopes(sockets) == []

    def test_naming_a_participant_who_is_elsewhere_still_publishes(
        self, sockets, registered
    ):
        registered("42")

        sockets.publish_to_participants({"type": "wake"}, [43])
        gevent.wait(timeout=1)

        assert json.loads(published_envelopes(sockets)[0])["participant_ids"] == ["43"]


class TestDirectChannelListener:
    def listener(self, sockets, backend=None):
        return sockets.DirectChannel(backend or sockets.chat_backend)

    def test_an_envelope_from_another_process_is_delivered(self, sockets, registered):
        client = registered("42")
        envelope = json.dumps(
            {
                "participant_ids": ["42"],
                "scope": None,
                "origin": "another process",
                "payload": '{"type": "wake"}',
            }
        )

        self.listener(sockets).relay(envelope_message(sockets, envelope))
        gevent.wait(timeout=1)

        client.ws.send.assert_called_once_with('dallinger_direct:{"type": "wake"}')

    def test_this_process_does_not_deliver_its_own_envelope_twice(
        self, sockets, registered
    ):
        client = registered("42")
        sockets.publish_to_participants({"type": "wake"}, [42])

        for envelope in published_envelopes(sockets):
            self.listener(sockets).relay(envelope_message(sockets, envelope))
        gevent.wait(timeout=1)

        assert client.ws.send.call_count == 1

    def test_a_scope_is_honoured_across_processes(self, sockets, registered):
        stale = registered("42", scope="page-6")
        envelope = json.dumps(
            {
                "participant_ids": ["42"],
                "scope": "page-7",
                "origin": "another process",
                "payload": '{"type": "wake"}',
            }
        )

        self.listener(sockets).relay(envelope_message(sockets, envelope))
        gevent.wait(timeout=1)

        stale.ws.send.assert_not_called()

    def test_an_unreadable_envelope_is_discarded(self, sockets, registered):
        client = registered("42")

        self.listener(sockets).relay(envelope_message(sockets, "not json"))
        gevent.wait(timeout=1)

        client.ws.send.assert_not_called()

    def test_an_envelope_naming_its_ids_as_text_is_discarded(self, sockets, registered):
        # Iterating "42" yields "4", which is a participant the send did not
        # name and this process holds a connection for.
        client = registered("4")
        envelope = dict(DIRECT_ENVELOPE, participant_ids="42")

        self.listener(sockets).relay(envelope_message(sockets, json.dumps(envelope)))
        gevent.wait(timeout=1)

        client.ws.send.assert_not_called()

    @pytest.mark.parametrize(
        "field, value",
        [
            # An unhashable id raises on the registry lookup rather than missing.
            pytest.param("participant_ids", [["42"]], id="an-id-unhashable"),
            pytest.param("payload", {"type": "wake"}, id="payload-not-text"),
            pytest.param("origin", 7, id="origin-not-text"),
        ],
    )
    def test_an_envelope_that_is_not_one_reaches_nobody(
        self, sockets, registered, field, value
    ):
        client = registered("42")
        envelope = dict(DIRECT_ENVELOPE, **{field: value})

        self.listener(sockets).relay(envelope_message(sockets, json.dumps(envelope)))
        gevent.wait(timeout=1)

        client.ws.send.assert_not_called()

    def test_a_frame_carrying_no_envelope_leaves_the_listener_reading(
        self, sockets, pubsub, registered
    ):
        pubsub.listen.return_value = [
            envelope_message(sockets, "[]"),
            envelope_message(sockets, json.dumps(DIRECT_ENVELOPE)),
        ]

        client = registered("42")
        gevent.wait(timeout=1)

        # The envelope behind the bad frame still arrived, so the greenlet
        # that reads them did not unwind on the first one.
        client.ws.send.assert_called_once_with('dallinger_direct:{"type": "wake"}')

    def test_a_subscribe_confirmation_is_not_an_envelope(self, sockets, registered):
        client = registered("42")

        with patch.object(sockets, "log") as log:
            self.listener(sockets).relay(
                {"type": "subscribe", "channel": b"dallinger_direct", "data": 1}
            )
        gevent.wait(timeout=1)

        # Read as an envelope a confirmation is unreadable, so dropping the
        # type check costs a warning for every subscription rather than a
        # delivery.
        log.assert_not_called()
        client.ws.send.assert_not_called()

    def test_each_process_delivers_to_its_own_clients(self, sockets, registered):
        here = registered("42")
        there_backend = sockets.ChatBackend()
        there = sockets.Client(Mock(), participant_id="42")
        there_backend.register(there)
        here_listener = self.listener(sockets)
        there_listener = self.listener(sockets, there_backend)

        sockets.publish_to_participants({"type": "wake"}, [42])
        for envelope in published_envelopes(sockets):
            here_listener.relay(envelope_message(sockets, envelope))
            # The second backend stands in for a second process, which reads
            # the same envelope holding a token of its own.
            with patch.object(sockets, "process_token", return_value="another process"):
                there_listener.relay(envelope_message(sockets, envelope))
        gevent.wait(timeout=1)

        # One copy each: the sending process delivered to ``here`` directly and
        # skipped its own envelope, and the other process delivered from it.
        here.ws.send.assert_called_once_with('dallinger_direct:{"type": "wake"}')
        there.ws.send.assert_called_once_with('dallinger_direct:{"type": "wake"}')


class TestProcessToken:
    def test_the_token_is_stable_within_a_process(self, sockets):
        assert sockets.process_token() == sockets.process_token()

    def test_a_forked_worker_gets_a_token_of_its_own(self, sockets):
        # With preload_app this module is imported before the fork, so a token
        # fixed at import would be shared and every worker would discard the
        # others' envelopes as its own.
        before = sockets.process_token()

        with patch.object(sockets.os, "getpid", return_value=-1):
            assert sockets.process_token() != before


class TestParsedEnvelope:
    def test_a_well_formed_envelope_comes_back(self, sockets):
        assert sockets.parsed_envelope(json.dumps(DIRECT_ENVELOPE)) == DIRECT_ENVELOPE

    def test_a_scope_of_text_comes_back(self, sockets):
        envelope = dict(DIRECT_ENVELOPE, scope="page-7")

        assert sockets.parsed_envelope(json.dumps(envelope)) == envelope

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param("not json", id="not-json"),
            pytest.param("[]", id="a-json-array"),
            pytest.param('"text"', id="a-json-string"),
            pytest.param("12", id="a-json-number"),
            pytest.param("null", id="json-null"),
            pytest.param(None, id="no-data"),
        ],
    )
    def test_a_frame_carrying_no_envelope_is_refused(self, sockets, data):
        assert sockets.parsed_envelope(data) is None

    @pytest.mark.parametrize("field", sorted(sockets_envelope_fields()))
    def test_an_envelope_missing_a_field_is_refused(self, sockets, field):
        envelope = dict(DIRECT_ENVELOPE)
        del envelope[field]

        assert sockets.parsed_envelope(json.dumps(envelope)) is None

    @pytest.mark.parametrize(
        "field, value",
        [
            pytest.param("participant_ids", "42", id="ids-not-a-list"),
            pytest.param("participant_ids", [42], id="an-id-not-text"),
            pytest.param("participant_ids", [["42"]], id="an-id-unhashable"),
            pytest.param("payload", {"type": "wake"}, id="payload-not-text"),
            pytest.param("payload", None, id="payload-null"),
            pytest.param("origin", 7, id="origin-not-text"),
            pytest.param("scope", 7, id="scope-not-text"),
        ],
    )
    def test_an_envelope_with_a_field_of_the_wrong_type_is_refused(
        self, sockets, field, value
    ):
        envelope = dict(DIRECT_ENVELOPE, **{field: value})

        assert sockets.parsed_envelope(json.dumps(envelope)) is None


class TestReservedChannels:
    def test_a_client_may_not_subscribe_to_the_direct_channel(
        self, sockets, mocksocket
    ):
        with patch.object(sockets.chat_backend, "subscribe") as subscribe:
            with patch.object(
                sockets, "request", Mock(args={"channel": sockets.DIRECT_CHANNEL})
            ):
                sockets.chat(mocksocket)

        # The connection drops its channels as it closes, so the channel map
        # is empty afterwards whether or not the name was refused.
        subscribe.assert_not_called()

    def test_a_client_may_not_subscribe_to_the_control_channel(
        self, sockets, mocksocket
    ):
        with patch.object(sockets.chat_backend, "subscribe") as subscribe:
            with patch.object(
                sockets, "request", Mock(args={"channel": sockets.CONTROL_CHANNEL})
            ):
                sockets.chat(mocksocket)

        # The connection drops its channels as it closes, so the channel map
        # is empty afterwards whether or not the name was refused.
        subscribe.assert_not_called()

    def test_a_client_may_not_publish_to_the_direct_channel(self, sockets, mocksocket):
        mocksocket.receive.return_value = (
            'dallinger_direct:{"participant_ids": ["42"], "payload": "{}"}'
        )

        sockets.Client(mocksocket).publish()

        assert published_envelopes(sockets) == []
