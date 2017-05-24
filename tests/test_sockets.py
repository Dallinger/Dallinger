from mock import Mock
import gevent
import pytest
import socket


@pytest.fixture
def sockets():
    from dallinger.experiment_server import sockets
    return sockets


@pytest.fixture
def chat(sockets):
    return sockets.ChatBackend()


@pytest.mark.usefixtures("experiment_dir")
class TestChatBackend:

    def test_subscribe_all_default_channels(self, chat):
        client = Mock()
        chat.subscribe(client)
        assert chat.clients == {'quorum': [client]}

    def test_subscribe_explicitly_to_a_default_channel(self, chat):
        client = Mock()
        chat.subscribe(client, 'quorum')
        assert chat.clients == {'quorum': [client]}

    def test_subscribe_to_new_channel_registers_client_for_channel(self, chat):
        client = Mock()
        chat.subscribe(client, 'custom')
        assert chat.clients == {'custom': [client]}

    def test_subscribe_to_new_channel_subscribes_on_redis(self, chat):
        client = Mock()
        chat.pubsub = Mock()
        chat.pubsub.channels = {}
        chat.subscribe(client, 'custom')
        chat.pubsub.subscribe.assert_called_once_with(['custom'])

    def test_subscribe_wont_duplicate_channel(self, chat):
        client1 = Mock()
        chat.pubsub = Mock()
        chat.pubsub.channels = {'custom'}
        chat.subscribe(client1, 'custom')
        chat.pubsub.subscribe.assert_not_called()

    def test_unsubscribe(self, chat):
        client = Mock()
        chat.subscribe(client, 'quorum')
        chat.unsubscribe(client, 'quorum')
        assert chat.clients == {'quorum': []}

    def test_send(self, chat):
        client = Mock()
        chat.send(client, 'message')
        client.send.assert_called_once_with('message')

    def test_send_exception(self, chat):
        client = Mock()
        client.send.side_effect = socket.error()
        chat.subscribe(client)
        chat.send(client, 'message')
        assert chat.clients == {'quorum': []}

    def test_run(self, chat):
        client = Mock()
        chat.subscribe(client)

        chat.pubsub = Mock()
        chat.pubsub.listen.return_value = [{
            'type': 'message',
            'channel': 'quorum',
            'data': 'Calloo! Callay!',
        }]

        chat.run()

        gevent.wait()  # wait for event loop
        client.send.assert_called_once_with('quorum:Calloo! Callay!')

    def test_stop(self, chat):
        chat.start()
        chat.stop()

    def test_heartbeat(self, chat, sockets):
        client = Mock()
        client.closed = False
        chat.send = Mock()
        sockets.HEARTBEAT_DELAY = 1

        gevent.spawn(chat.heartbeat, client)
        gevent.sleep(2)
        client.closed = True
        gevent.wait()

        chat.send.assert_called_with(client, 'ping')

    def test_chat_subscribes_to_default_channel(self, sockets):
        ws = Mock()
        sockets.request = Mock()
        sockets.request.args = {}
        sockets.chat(ws)

        ws.closed = True
        gevent.wait()

        assert ws in sockets.chat_backend.clients['quorum']

    def test_chat_subscribes_to_requested_channel(self, sockets):
        ws = Mock()
        sockets.request = Mock()
        sockets.request.args.get.return_value = 'special'
        sockets.chat(ws)
        assert ws in sockets.chat_backend.clients['special']

    def test_chat_publishes_message_to_requested_channel(self, sockets):
        class MockSocket(Mock):
            """We need a property that returns False the first time
            and True after that. Doesn't seem possible with Mock.
            """
            calls = []

            @property
            def closed(self):
                if self.calls:
                    return True
                self.calls.append('called')
                return False

        ws = MockSocket()
        ws.receive.return_value = 'special:incoming message!'
        sockets.request = Mock()
        sockets.conn = Mock()
        sockets.chat(ws)
        sockets.conn.publish.assert_called_once_with(
            'special', 'incoming message!'
        )
