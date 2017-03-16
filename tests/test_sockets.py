from mock import Mock
import gevent
import pytest


@pytest.fixture
def sockets():
    from dallinger.experiment_server import sockets
    return sockets


@pytest.fixture
def chat(sockets):
    return sockets.ChatBackend()


@pytest.mark.usefixtures("experiment_dir")
class TestChatBackend:

    def test_subscribe_one_channel(self, chat):
        client = Mock()
        chat.subscribe(client, 'quorum')
        assert chat.clients == {'quorum': [client]}

    def test_subscribe_all_channels(self, chat):
        client = Mock()
        chat.subscribe(client)
        assert chat.clients == {'quorum': [client]}

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
        client.send.side_effect = Exception()
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

    def test_outbox(self, sockets):
        ws = Mock()
        ws.closed = False
        sockets.outbox(ws)
        ws.closed = True

        gevent.wait()
        assert ws in sockets.chat_backend.clients['quorum']
