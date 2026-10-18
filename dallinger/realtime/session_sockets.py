"""How a page's websocket takes part in a real-time session.

A page joins a session by opening a websocket with the session's id in the
``session`` query parameter. The web process adds a join to the session when
the socket is ready, a message for each frame the page sends on the game
type's channel, and a leave when the socket closes. Frames on a game channel
are never broadcast or passed to
:meth:`~dallinger.experiment.Experiment.handle_websocket_message`.

A page whose session has already ended gets no join. Its socket gets the
session's ending instead, as :mod:`dallinger.realtime.delivery` describes.

A page measures its clock against the server's with frames on
:data:`~dallinger.db.TIME_CHANNEL`, each a JSON object:

- ``{"type": "request", "id": ...}`` asks for the server's clock. The ``id``
  is a number the page chooses. The web process answers at once, on the same
  socket, with ``{"type": "time", "id": ..., "clock": ...}``: the request's
  ``id`` and the server's clock, in seconds since 1970. A request whose ``id``
  isn't a finite number that fits in a float is dropped. The server's clock
  is redis's, which also sets the times entries are received and the
  session's time.
- ``{"type": "clock", "browser_time": ..., "server_time": ...,
  "round_trip": ...}`` reports a measurement, which is saved with the
  session's records. ``browser_time`` is the browser's clock, the clock of
  message envelopes' ``browser_time``. ``server_time`` is the server's clock
  at the same moment, as the page estimated it, in seconds since 1970, and
  ``round_trip`` is the round trip of the request the estimate came from, in
  seconds. A report counts against the rate limit as a message does. One
  missing a value, with a value that isn't a finite number that fits in a
  float, or with a negative ``round_trip``, is dropped.

A socket with no session gets no answers, and its reports are dropped.

The web process only checks that the participant the socket names is one of
the session's players. Dallinger's sockets don't authenticate anyone, so a
page that names another player's participant id can play as that player. An
experiment can check ``/experiment-socket`` connections itself with
:func:`~dallinger.experiment.Experiment.accept_websocket_connection`, but a
``/chat`` connection can join a session without that check.
"""

import json
import logging
import math
import time
import uuid

from redis import RedisError

from dallinger.db import DIRECT_CHANNEL, TIME_CHANNEL, channel_frame
from dallinger.realtime import store
from dallinger.realtime.delivery import ending_payload

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


class SessionExpired(Exception):
    """The session's keys expired after the connection was found to be one of
    its players.
    """


class NoSession:
    """The session side of a connection with no session, which drops every
    frame on a game channel or the time channel.

    :param describe: what the warnings call the connection
    """

    def __init__(self, describe):
        self.describe = describe
        self.last_warning = None

    def join(self):
        return None

    def leave(self):
        pass

    def handle_frame(self, channel, data):
        """Drop a frame on a game channel or the time channel, and return
        ``None``.
        """
        self.warn_dropped("on {} with no session".format(channel))

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
    messages, clock reports and leave to the session's entries.

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
        #: Seconds to add to this process's clock for redis's.
        self.clock_offset = 0.0
        self.joined = False

    def join(self):
        """Add the connection's join to its session and return ``None``, or,
        if the session has ended, return the frame that tells the page how it
        ended.

        :raises SessionExpired: if the session's keys have expired
        """
        self.clock_offset = store.server_time() - time.time()
        if self.add_socket_entry("join") is not None:
            self.joined = True
            return None
        ending = store.load_ending(self.session_id)
        if ending is None:
            raise SessionExpired(self.session_id)
        return channel_frame(
            DIRECT_CHANNEL, ending_payload(self.session_id, ending, self.participant)
        )

    def leave(self):
        """Add the connection's leave to its session, if it joined."""
        if self.joined:
            self.add_socket_entry("leave")

    def add_socket_entry(self, kind):
        return store.add_entry(
            self.session_id,
            {
                "type": kind,
                "participant": self.participant,
                "scope": self.scope,
                "socket": self.socket,
            },
        )

    def handle_frame(self, channel, data):
        """Add a game frame to the session as a message, or handle a frame on
        the time channel. Return the frame that answers a time request, or
        ``None``.

        A game frame on another game type's channel is dropped.
        """
        if channel == TIME_CHANNEL:
            return self.handle_time_frame(data)
        if channel != self.game.channel:
            self.warn_dropped(
                "on the game channel {}, which isn't its session's".format(channel)
            )
            return None
        self.add_limited_entry({"type": "message", "data": data})
        return None

    def handle_time_frame(self, data):
        """Return the frame that answers a time request, or add a clock report
        to the session and return ``None``.
        """
        frame = _json_object(data)
        kind = None if frame is None else frame.get("type")
        if kind == "request" and _finite_number(frame.get("id")) is not None:
            clock = time.time() + self.clock_offset
            answer = {"type": "time", "id": frame["id"], "clock": clock}
            return channel_frame(TIME_CHANNEL, json.dumps(answer))
        report = _clock_report(frame) if kind == "clock" else None
        if report is None:
            self.warn_dropped(
                "on {} that aren't time requests or clock reports".format(TIME_CHANNEL)
            )
            return None
        self.add_limited_entry({"type": "clock", **report})
        return None

    def add_limited_entry(self, entry):
        """Add an entry from the page to the session, or drop it if it's over
        the rate limit, the session has ended or redis refuses it.
        """
        if not self.bucket.take():
            self.warn_dropped("over {}'s rate limit".format(type(self.game).__name__))
            return
        try:
            added = store.add_entry(
                self.session_id,
                {"participant": self.participant, "scope": self.scope, **entry},
            )
        except RedisError:
            self.warn_dropped("that redis refused", exc_info=True)
            return
        if added is None:
            self.warn_dropped("for a session that has ended")


def _json_object(data):
    try:
        value = json.loads(data)
    # json.loads raises RecursionError for deeply nested arrays or objects.
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _finite_number(value):
    """``value`` as a float if it's a finite number that fits in one, otherwise
    ``None``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    # json.loads reads NaN and Infinity, and a float too large as infinity.
    return value if math.isfinite(value) else None


def _clock_report(frame):
    names = ("browser_time", "server_time", "round_trip")
    report = {name: _finite_number(frame.get(name)) for name in names}
    if None in report.values() or report["round_trip"] < 0:
        return None
    return report


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
