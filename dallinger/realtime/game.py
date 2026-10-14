"""Game types for the real-time engine.

A real-time game is written as a game type: a subclass of
:class:`RealtimeGame` that holds the game's rules. Each game being played is a
session, with its own state and its own players. A runner, a separate process,
plays sessions. It calls the game type's methods with a session's state as
messages arrive and as time passes, and sends each player's page a view of the
state.

A runner uses one instance of each game type for all of its sessions, so keep
nothing on the instance. Everything a session needs goes in its state.

The state, messages, views and outcomes are plain JSON values. The runner
saves the state as JSON and loads it again, sometimes in another runner, so
dict keys come back as strings and tuples as lists. Build them that way from
the start.

Players are identified by their participant ids, as strings, so the ids work
as keys in the state's dicts. Times are seconds on the session's own clock,
which starts at 0 and stops while no runner is playing the session.
"""

import json
import math
import numbers
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass

from dallinger.db import RESERVED_CHANNELS

#: The reason passed to :meth:`RealtimeGame.outcome` when
#: :meth:`~RealtimeGame.is_over` returned true.
FINISHED = "finished"

#: The reason passed to :meth:`RealtimeGame.outcome` when the session clock
#: reached :attr:`~RealtimeGame.max_duration`.
MAX_DURATION = "max_duration"

# The list effects are queued in while the session core calls game code.
queued_effects = ContextVar("queued_effects")


class Reject(Exception):
    """Raise from :meth:`RealtimeGame.apply` to refuse a message.

    A refused message still counts as processed. It's saved with ``reason``,
    and the sender's page gets the message's number and ``reason`` with its
    next view. The runner can't undo changes ``apply`` made before raising, so
    check everything before changing the state.

    :param reason: why the message was refused, as a JSON value
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Sent:
    """What a player's page said about a message it sent.

    The client helpers wrap each message in an envelope with these values.
    ``number`` counts the messages the page has sent, ``browser_time`` is the
    browser's clock when it sent this one, and ``view_time`` is the session
    time of the view the page was showing. Each is ``None`` when the page
    sent no envelope, or a missing or invalid value.
    """

    number: int | None = None
    browser_time: float | None = None
    view_time: float | None = None


class RealtimeGame(ABC):
    """Base class for real-time game types.

    A game type sets :attr:`channel` and implements :meth:`initial_state` and
    :meth:`apply`. Every other method has a default.

    Methods get the session's ``state``, and ``now``, the current session
    time. :meth:`apply`, :meth:`tick`, :meth:`on_join` and :meth:`on_leave`
    change the state in place. The other methods only read it, and the runner
    calls them as often as it needs to. No method may use the database: use
    :meth:`queue_effect` for anything that needs it.
    """

    #: The websocket channel the game's pages send messages on. It can't
    #: contain a colon, or be one of Dallinger's reserved channels, the
    #: experiment's ``channel``, or another game type's channel.
    channel = None

    #: How many times a second :meth:`tick` runs. At 0, it runs only at the
    #: times :meth:`next_deadline` returns.
    tick_rate = 0

    #: Seconds on the session clock after which the session ends, whatever
    #: :meth:`is_over` says. ``None`` means no limit.
    max_duration = None

    #: Whether a player's page gets a view as soon as the player's message is
    #: applied, rather than with the next tick. A game with a
    #: :attr:`tick_rate` of 0 always sends the sender a view, and sends every
    #: player one when the state changes.
    send_views_on_messages = True

    #: How many messages a second each page may send, on average. Messages
    #: over the limit are dropped and counted.
    max_messages_per_second = 120

    #: How many messages a page may send at once, above
    #: :attr:`max_messages_per_second`, before the limit applies.
    message_burst = 20

    #: Saved with each session's state. A runner refuses to load state saved
    #: by a different version, so change it when the state's format changes.
    version = 1

    @abstractmethod
    def initial_state(self, players):
        """Return the state a new session starts from.

        :param players: the player ids of the session's members, bots
            included
        """

    @abstractmethod
    def apply(self, state, player_id, message, now, sent):
        """Check a player's message and apply it to ``state``.

        Raise :class:`Reject` to refuse the message.

        :param player_id: the sender's player id
        :param message: the message, as a JSON value, or the text the page
            sent if it isn't JSON
        :param now: the session time the message arrived
        :param sent: what the page said about the message
        """

    def tick(self, state, now):
        """Advance ``state`` to ``now``: movement, timers and deadlines.

        Runs :attr:`tick_rate` times a second, and at the times
        :meth:`next_deadline` returns. A runner that falls behind runs each
        missed tick in turn, each with its own ``now``.
        """

    def next_deadline(self, state):
        """Return the session time :meth:`tick` should next run at, or
        ``None``.

        Needed only when a deadline can fall between ticks, as in a game with
        a :attr:`tick_rate` of 0. A deadline that has passed runs ``tick`` at
        once. A deadline at or before the last tick doesn't run, so ``tick``
        can leave a deadline it has handled in the state.
        """
        return None

    def view(self, state, player_id):
        """Return what ``player_id`` may see of ``state``.

        The default is the whole state. Override it to hide anything from a
        player.
        """
        return state

    def is_over(self, state):
        """Return whether the game has finished. Checked after every change
        to the state.
        """
        return False

    def outcome(self, state, reason):
        """Return the session's result, saved in Postgres when the session
        ends.

        :param reason: why the session ended: :data:`FINISHED`,
            :data:`MAX_DURATION`, or the reason the experiment gave when it
            ended the session
        """
        return None

    def on_join(self, state, player_id, now):
        """Respond to a player opening a page while none of theirs is open.

        A player who reloads their page leaves and then joins again.
        """

    def on_leave(self, state, player_id, now):
        """Respond to a player's last open page closing.

        By default the game carries on without them.
        """

    def bot(self, view, player_id, now):
        """Return a bot's next message, or ``None`` to send nothing.

        Bots are players the runner plays for, and their messages go through
        :meth:`apply` like any other player's. In a game with ticks, each bot
        is asked once per tick. In a game without ticks, bots are asked when
        the session starts and after every message, join, leave and tick,
        including each other's messages, until a round passes in which no
        bot's message is accepted. A bot in a game without ticks must
        therefore return ``None`` once it has nothing to do.

        :param view: a copy of the bot's view, from :meth:`view`
        :param player_id: the bot's player id
        """
        return None

    def queue_effect(self, name, payload):
        """Queue an effect: work the game needs done outside the runner, such
        as writing to the database.

        Effects are saved with the session's records, and handled later in a
        job that can use the database. Only :meth:`apply`, :meth:`tick`,
        :meth:`on_join` and :meth:`on_leave` can queue effects, because the
        runner calls the other methods as often as it needs to. The effects of
        a call that raises, such as an ``apply`` that raises :class:`Reject`,
        are dropped.

        :param name: a string naming the effect
        :param payload: a JSON value, copied when it's queued
        """
        effects = queued_effects.get(None)
        if effects is None:
            raise RuntimeError(
                "queue_effect only works in apply, tick, on_join and on_leave, "
                "called by a runner."
            )
        effects.append((name, json.loads(json.dumps(payload, allow_nan=False))))


def _is_number(value):
    return isinstance(value, numbers.Real) and math.isfinite(value)


def _check_game(name, game):
    channel = game.channel
    if not isinstance(channel, str) or not channel:
        raise ValueError("{}'s channel must be a non-empty string.".format(name))
    # Frames on the socket are "channel:data", split at the first colon.
    if ":" in channel:
        raise ValueError(
            "{}'s channel {!r} may not contain a colon.".format(name, channel)
        )
    if channel in RESERVED_CHANNELS:
        raise ValueError(
            "{}'s channel {} is reserved for Dallinger's own use.".format(name, channel)
        )
    if not _is_number(game.tick_rate) or game.tick_rate < 0:
        raise ValueError("{}'s tick_rate must be a number, 0 or more.".format(name))
    if game.max_duration is not None and (
        not _is_number(game.max_duration) or game.max_duration <= 0
    ):
        raise ValueError(
            "{}'s max_duration must be None or a positive number.".format(name)
        )
    if not _is_number(game.max_messages_per_second) or (
        game.max_messages_per_second <= 0
    ):
        raise ValueError(
            "{}'s max_messages_per_second must be a positive number.".format(name)
        )
    if not isinstance(game.message_burst, int) or game.message_burst < 1:
        raise ValueError(
            "{}'s message_burst must be a whole number, 1 or more.".format(name)
        )
    # Saved state is compared with this after a JSON round trip, which turns a
    # tuple into a list that never matches.
    if not isinstance(game.version, (int, str)):
        raise ValueError("{}'s version must be an integer or a string.".format(name))


def validate_game_types(game_types, experiment_channel=None):
    """Check an experiment's game types and return an instance of each.

    Each game type is instantiated with no arguments, so a subclass can read
    its settings from the experiment's config in ``__init__``.

    :param game_types: :class:`RealtimeGame` subclasses
    :param experiment_channel: the experiment's own ``channel``, if it has one
    :returns: a dict mapping each channel to its game type's instance
    :raises ValueError: if a game type isn't a :class:`RealtimeGame`
        subclass, doesn't define ``initial_state`` and ``apply``, or has an
        invalid setting, or if two game types, or a game type and the
        experiment, share a channel
    """
    games = {}
    for game_type in game_types:
        if not (isinstance(game_type, type) and issubclass(game_type, RealtimeGame)):
            raise ValueError("{!r} is not a RealtimeGame subclass.".format(game_type))
        name = game_type.__name__
        if game_type.__abstractmethods__:
            raise ValueError(
                "{} must define {}.".format(
                    name, " and ".join(sorted(game_type.__abstractmethods__))
                )
            )
        game = game_type()
        _check_game(name, game)
        if experiment_channel is not None and game.channel == experiment_channel:
            raise ValueError(
                "{}'s channel {} is the experiment's channel.".format(
                    name, game.channel
                )
            )
        if game.channel in games:
            raise ValueError(
                "{} and {} both use the channel {}.".format(
                    type(games[game.channel]).__name__, name, game.channel
                )
            )
        games[game.channel] = game
    return games
