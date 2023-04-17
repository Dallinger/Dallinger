import socket

import gevent
import pytest
from mock import Mock


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
    del sockets.chat_backend.channels["test"]


@pytest.fixture
def client(sockets):
    ws = Mock()
    return sockets.Client(ws)


@pytest.fixture
def mocksocket():
    class MockSocket(Mock):
        """We need a property that returns False the first time
        and True after that. Doesn't seem possible with Mock.
        """

        calls = []

        @property
        def closed(self):
            if self.calls:
                return True
            self.calls.append("called")
            return False

    return MockSocket()


class TestChannel:
    def test_subscribes_to_redis(self, sockets, pubsub):
        sockets.Channel("custom").start()
        gevent.wait()
        pubsub.subscribe.assert_called_once_with([b"custom"])

    def test_listen(self, sockets):
        sockets.redis_conn.pubsub.return_value = pubsub = Mock()
        pubsub.listen.return_value = [
            {"type": "message", "channel": b"quorum", "data": b"Calloo! Callay!"}
        ]

        channel = sockets.Channel("custom")
        client = Mock()
        channel.subscribe(client)
        channel.start()
        gevent.wait()  # wait for event loop

        client.send.assert_called_once_with("quorum:Calloo! Callay!")

    def test_stop(self, channel):
        channel.start()
        channel.stop()
        assert channel.greenlet is None


class TestChatBackend:
    def test_subscribe_to_new_channel_registers_client_for_channel(self, chat):
        client = Mock()
        chat.subscribe(client, "custom")
        assert client in chat.channels["custom"].clients

    def test_subscribe_wont_duplicate_channel(self, sockets, chat, channel, pubsub):
        client = Mock()
        chat.subscribe(client, channel.name)
        pubsub.subscribe.assert_not_called()

    def test_unsubscribe(self, chat):
        client = Mock()
        chat.subscribe(client, "quorum")
        chat.unsubscribe(client)
        assert client not in chat.channels["quorum"].clients


@pytest.mark.slow
class TestClient:
    def test_send(self, client):
        client.send("message")
        client.ws.send.assert_called_once_with("message")

    def test_send_exception_unsubscribes_client(self, client, channel):
        client.ws.send.side_effect = socket.error()
        channel.subscribe(client)
        client.send("message")
        assert client not in channel.clients

    def test_heartbeat(self, sockets, client):
        client.ws.closed = False
        sockets.HEARTBEAT_DELAY = 1

        gevent.spawn(client.heartbeat)
        gevent.sleep(2)
        client.ws.closed = True
        gevent.wait()

        client.ws.send.assert_called_with("ping")


class TestChatEndpoint:
    def test_chat_subscribes_to_requested_channel(self, sockets):
        ws = Mock()
        ws.closed = True
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
        sockets.redis_conn.publish.assert_called_once_with(
            "special", "incoming message!"
        )

    def test_sleeps_for_requested_time(self, sockets, mocksocket):
        ws = mocksocket
        ws.receive.return_value = "somechannel:incoming message!"
        sockets.request = Mock()
        sockets.request.args.get.return_value = ".5"
        sockets.gevent = Mock()
        sockets.chat(ws)
        sockets.gevent.sleep.assert_called_once_with(0.5)
