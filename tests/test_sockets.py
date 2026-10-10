import json
import socket
from unittest.mock import Mock

import gevent
import pytest
from simple_websocket import ConnectionClosed


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
    for channel in list(sockets.chat_backend.channels.values()):
        channel.stop()
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


def block_forever():
    """Stand in for ``pubsub.listen()`` waiting for messages."""
    gevent.sleep(60)
    return iter(())


def message(channel, data):
    return {"type": "message", "channel": channel, "data": data}


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
def mocksocket():
    class MockSocket(Mock):
        """We need a property that returns True the first time
        and False after that. Doesn't seem possible with Mock.
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
    def test_subscribes_to_redis(self, channel, pubsub):
        channel.start()
        gevent.sleep(0.01)
        pubsub.subscribe.assert_called_once_with("test")

    def test_listen(self, channel, pubsub, mockclient):
        pubsub.listen.return_value = [message(b"quorum", b"Calloo! Callay!")]
        channel.subscribe(mockclient)
        channel.start()
        gevent.sleep(0.01)

        mockclient.send.assert_called_once_with("quorum:Calloo! Callay!")

    def test_listen_tolerates_client_that_disconnected(
        self, channel, pubsub, mockclient, monkeypatch
    ):
        errors = []
        monkeypatch.setattr(
            gevent.get_hub(), "handle_error", lambda *args: errors.append(args)
        )
        pubsub.listen.return_value = [message(b"quorum", b"Calloo! Callay!")]
        mockclient.send.side_effect = ConnectionClosed(1000, "")
        channel.subscribe(mockclient)
        channel.start()
        gevent.sleep(0.01)

        mockclient.send.assert_called_once_with("quorum:Calloo! Callay!")
        assert errors == []

    def test_listen_skips_messages_that_are_not_utf8(self, channel, pubsub, mockclient):
        pubsub.listen.return_value = [
            message(b"quorum", b"\xff"),
            message(b"quorum", b"after"),
        ]
        channel.subscribe(mockclient)
        channel.start()
        gevent.sleep(0.01)

        mockclient.send.assert_called_once_with("quorum:after")
        pubsub.subscribe.assert_called_once()

    def test_listen_recovers_from_lost_redis_connection(
        self, channel, pubsub, mockclient
    ):
        from redis import ConnectionError

        responses = [ConnectionError("lost"), [message(b"test", b"back")]]

        def listen():
            if not responses:
                return block_forever()
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        pubsub.listen.side_effect = listen
        channel.subscribe(mockclient)
        channel.start()
        gevent.sleep(1.1)

        mockclient.send.assert_called_once_with("test:back")

    def test_stop_closes_the_redis_connection(self, channel, pubsub):
        pubsub.listen.side_effect = block_forever
        channel.start()
        gevent.sleep(0.01)
        channel.stop()
        assert channel.greenlet is None
        pubsub.close.assert_called_once()

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

    def test_last_client_leaving_releases_the_redis_connection(
        self, chat, pubsub, mockclient
    ):
        pubsub.listen.side_effect = block_forever
        chat.subscribe(mockclient, "quorum")
        gevent.sleep(0.01)
        chat.unsubscribe(mockclient)

        assert "quorum" not in chat.channels
        pubsub.close.assert_called_once()

    def test_last_client_leaving_releases_the_connection_when_redis_fails(
        self, sockets, chat, pubsub, mockclient
    ):
        from redis.exceptions import ConnectionError

        pubsub.listen.side_effect = block_forever
        chat.subscribe(mockclient, "quorum")
        gevent.sleep(0.01)
        sockets.redis_conn.publish.side_effect = ConnectionError("Redis is down")
        chat.unsubscribe(mockclient)

        assert "quorum" not in chat.channels
        pubsub.close.assert_called_once()

    def test_channel_stays_while_other_clients_remain(self, chat, pubsub, mockclient):
        pubsub.listen.side_effect = block_forever
        other = Mock(**{"client_info.return_value": {}})
        chat.subscribe(mockclient, "quorum")
        chat.subscribe(other, "quorum")
        gevent.sleep(0)
        chat.unsubscribe(mockclient)
        gevent.sleep(0)

        assert chat.channels["quorum"].clients == [other]
        pubsub.close.assert_not_called()

    def test_unsubscribe_tolerates_channel_added_meanwhile(
        self, sockets, chat, mockclient
    ):
        chat.subscribe(mockclient, "quorum")
        # Publishing yields to other greenlets, which may open new channels.
        sockets.redis_conn.publish.side_effect = lambda *args: chat.channels.setdefault(
            "late", sockets.Channel("late")
        )
        chat.unsubscribe(mockclient)
        assert "quorum" not in chat.channels


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
    def test_chat_subscribes_to_requested_channel(self, sockets):
        ws = Mock()
        ws.connected = False
        ws.receive.return_value = None
        sockets.request = Mock()
        sockets.request.args = {"channel": "special"}
        sockets.chat(ws)

        clients = [
            c for c in sockets.chat_backend.channels["special"].clients if c.ws is ws
        ]
        assert len(clients) == 1

    def test_chat_publishes_message_to_requested_channel(self, sockets, mocksocket):
        ws = mocksocket
        ws.receive.return_value = "special:incoming message!"
        sockets.request = Mock()
        sockets.request.args = {"tolerance": ".5"}
        sockets.chat(ws)

        # We should have three calls publishing messages on redis
        #
        # 1. The subscribe message on the control channel from
        #    ``TestChannel.test_subscribe_sends_control_message``
        # 2. A websocket connected message on the control channel sent before
        #    entering the receive loop in `client.publish()`
        # 3. The plain text message received from `ws.receive()` on the
        #    `special` channel.

        assert sockets.redis_conn.publish.call_count == 3

        # Let's look for that `special` message
        assert sockets.redis_conn.publish.mock_calls[2].args[0] == "special"
        assert sockets.redis_conn.publish.mock_calls[2].args[1] == "incoming message!"

    def test_sleeps_for_requested_time(self, sockets, mocksocket):
        ws = mocksocket
        ws.receive.return_value = "somechannel:incoming message!"
        sockets.request = Mock()
        sockets.request.args.get.return_value = ".5"
        sockets.gevent = Mock()
        sockets.chat(ws)
        sockets.gevent.sleep.assert_called_once_with(0.5)
