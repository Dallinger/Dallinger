"""How a page's websocket takes part in a real-time session.

A page joins a session by opening a websocket with the session's id in the
``session`` query parameter. The web process adds a join to the session when
the socket is ready, a message for each frame the page sends on the game
type's channel, and a leave when the socket closes. Frames on a game channel
are never broadcast or passed to
:meth:`~dallinger.experiment.Experiment.handle_websocket_message`.

The web process only checks that the participant the socket names is one of
the session's players. Dallinger's sockets don't authenticate anyone, so a
page that names another player's participant id can play as that player.
"""

import logging
import time
import uuid

from redis import RedisError

from dallinger.realtime import store

logger = logging.getLogger(__name__)

#: The least time, in seconds, between a connection's warnings about the
#: messages it drops.
DROP_WARNING_INTERVAL_SECS = 1.0


class TokenBucket:
    """Allows ``rate`` events a second on average, and up to ``capacity`` at
    once.
    """

    def __init__(self, rate, capacity):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.updated = time.monotonic()

    def take(self):
        """Return whether an event is allowed now, and count it if so."""
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class NoSession:
    """The game-channel side of a connection with no session, which drops
    every frame on a game channel.

    :param describe: what the warnings call the connection
    """

    def __init__(self, describe):
        self.describe = describe
        self.last_warning = None

    def send(self, channel, data):
        self.warn_dropped("on the game channel {} with no session".format(channel))

    def warn_dropped(self, why, exc_info=False):
        """Log a warning about a dropped frame, at most once every
        :data:`DROP_WARNING_INTERVAL_SECS`.
        """
        now = time.monotonic()
        if (
            self.last_warning is not None
            and now - self.last_warning < DROP_WARNING_INTERVAL_SECS
        ):
            return
        self.last_warning = now
        logger.warning(
            "Dropping messages from %s %s.", self.describe, why, exc_info=exc_info
        )


class SessionSocket(NoSession):
    """A connection's place in a session: it adds the connection's join,
    messages and leave to the session's entries.

    Each connection has its own rate limit, from the game type's
    :attr:`~dallinger.realtime.game.RealtimeGame.max_messages_per_second`
    and :attr:`~dallinger.realtime.game.RealtimeGame.message_burst`.
    """

    def __init__(self, session_id, game, participant, scope, describe):
        super().__init__(describe)
        self.session_id = session_id
        self.game = game
        self.participant = participant
        self.scope = scope
        #: Names this connection in its session's join and leave entries.
        self.socket = uuid.uuid4().hex
        self.bucket = TokenBucket(game.max_messages_per_second, game.message_burst)

    def join(self):
        """Add the connection's join to its session."""
        self.add_socket_entry("join")

    def leave(self):
        """Add the connection's leave to its session."""
        self.add_socket_entry("leave")

    def add_socket_entry(self, kind):
        store.add_entry(
            self.session_id,
            {
                "type": kind,
                "participant": self.participant,
                "scope": self.scope,
                "socket": self.socket,
            },
        )

    def send(self, channel, data):
        """Add a frame to the session as a message, or drop it if it's on
        another game type's channel, over the rate limit or refused by redis.
        """
        if channel != self.game.channel:
            self.warn_dropped(
                "on the game channel {}, which isn't its session's".format(channel)
            )
            return
        if not self.bucket.take():
            self.warn_dropped("over {}'s rate limit".format(type(self.game).__name__))
            return
        try:
            store.add_entry(
                self.session_id,
                {
                    "type": "message",
                    "participant": self.participant,
                    "scope": self.scope,
                    "data": data,
                },
            )
        except RedisError:
            self.warn_dropped("that redis refused", exc_info=True)


def open_session_socket(requested, participant, scope, games, describe):
    """Return the :class:`SessionSocket` for a connection that asked for the
    session ``requested``, or ``None`` if its participant isn't one of the
    session's players. A bot isn't, because the runner plays for it.

    :param requested: the ``session`` query parameter
    :param participant: the connection's participant id, a string, or
        ``None``
    :param scope: the connection's scope
    :param games: the experiment's game types, as
        :func:`~dallinger.realtime.store.experiment_games` returns them
    :param describe: what warnings call the connection

    A redis error looking the session up is raised.
    """
    try:
        session_id = int(requested)
    except ValueError:
        return None
    if participant is None:
        return None
    game = games.get(store.player_game_channel(session_id, participant))
    if game is None:
        return None
    return SessionSocket(session_id, game, participant, scope, describe)
