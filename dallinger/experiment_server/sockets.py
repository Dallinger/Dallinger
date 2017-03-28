from collections import defaultdict
from .experiment_server import app
from .experiment_server import WAITING_ROOM_CHANNEL
from ..heroku.worker import conn
from flask import request
from flask_sockets import Sockets
from redis import ConnectionError
import gevent
import socket

sockets = Sockets(app)

DEFAULT_CHANNELS = [
    WAITING_ROOM_CHANNEL,
]


class ChatBackend(object):
    """Chat backend which relays messages from a redis pubsub to clients.

    This is run by each web process; all processes receive the messages.

    Inspired by https://devcenter.heroku.com/articles/python-websockets
    """

    def __init__(self):
        self.pubsub = conn.pubsub()
        self._join_pubsub(DEFAULT_CHANNELS)
        self.clients = defaultdict(list)

    def _join_pubsub(self, channels):
        try:
            self.pubsub.subscribe(channels)
            app.logger.debug(
                'Subscribed to channels: {}'.format(self.pubsub.channels.keys()))
        except ConnectionError:
            app.logger.exception('Could not connect to redis.')

        self.clients = {}
        for channel in DEFAULT_CHANNELS:
            self.clients[channel] = []

        self.age = defaultdict(lambda: 0)

    def subscribe(self, client, channel=None):
        """Register a new client to receive messages."""
        app.logger.debug('{} subscribing to channel {}'.format(client, channel))
        if channel is not None:
            self.clients[channel].append(client)
            self._join_pubsub([channel])
        else:
            for channel in DEFAULT_CHANNELS:
                self.clients[channel].append(client)
                app.logger.debug(
                    'Subscribed client {} to channel {}'.format(
                        client, channel))

    def unsubscribe(self, client, channel):
        if client in self.clients[channel]:
            self.clients[channel].remove(client)

    def send(self, client, data):
        """Send data to one client.

        Automatically discards invalid connections.
        """
        app.logger.debug('sending {} to client {}'.format(data, client))
        try:
            client.send(data)
        except socket.error:
            for channel in self.clients:
                self.unsubscribe(client, channel)
            if client in self.age:
                del self.age[client]

    def run(self):
        """Listens for new messages in redis, and sends them to clients."""
        for message in self.pubsub.listen():
            data = message.get('data')
            if message['type'] == 'message':
                channel = message['channel']
                count = len(self.clients[channel])
                if count:
                    app.logger.debug(
                        'Relaying message on channel {} to {} clients: {}'.format(
                            channel, len(self.clients[channel]), data))
                    for client in self.clients[channel]:
                        gevent.spawn(
                            self.send, client, '{}:{}'.format(channel, data))

    def start(self):
        """Starts listening in the background."""
        self.greenlet = gevent.spawn(self.run)

    def stop(self):
        self.greenlet.kill()

    def heartbeat(self, client):
        """Send a ping to the client periodically"""
        self.age[client] += 1
        if self.age[client] == 300:  # 30 seconds
            gevent.spawn(self.send, client, 'ping')
            self.age[client] = 0


chat_backend = ChatBackend()
app.before_first_request(chat_backend.start)


@sockets.route('/receive_chat')
def outbox(ws):
    """This route was highjacked temporarily for the Griduniverse socket.
    It both subscribes the websocket to the chat backend
    so the front-end clients get messages via redis,
    and it puts messages from the clients into redis so they can be sent on
    to the Experiment, which is also registered with the chat_backend.
    """
    chat_backend.subscribe(ws, channel=request.args.get('channel'))

    while not ws.closed:
        # Wait for chat backend
        gevent.sleep(0.1)

        # Send heartbeat ping every 30s
        # so Heroku won't close the connection
        chat_backend.heartbeat(ws)
