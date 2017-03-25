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
        chat.subscribe(client, 'custom')
        chat.pubsub.subscribe.assert_called_once_with(['custom'])

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

    def test_heartbeat(self, chat):
        client = Mock()

        for i in range(300):
            chat.heartbeat(client)

        assert chat.age[client] == 0

    def test_outbox_subscribes_to_default_channel(self, sockets):
        ws = Mock()
        sockets.request = Mock()
        sockets.request.args.get.return_value = None
        sockets.outbox(ws)

        ws.closed = True
        gevent.wait()

        assert ws in sockets.chat_backend.clients['quorum']

    def test_outbox_subscribes_to_requested_channel(self, sockets):
        ws = Mock()
        sockets.request = Mock()
        sockets.request.args.get.return_value = 'special'
        sockets.outbox(ws)
        assert ws in sockets.chat_backend.clients['special']
