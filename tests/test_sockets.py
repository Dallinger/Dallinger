import json
import socket
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

    def test_failed_subscribe_skips_listening(self, sockets, pubsub):
        pubsub.subscribe.side_effect = sockets.ConnectionError("no redis")
        sockets.Channel("custom").start()
        gevent.wait()
        pubsub.listen.assert_not_called()
        pubsub.close.assert_called_once_with()

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

    def test_failed_subscribe_is_not_retried(self, sockets, pubsub):
        pubsub.subscribe.side_effect = sockets.ConnectionError("no redis")

        sockets.Channel("custom").listen()

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
