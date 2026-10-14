"""Game types for the real-time engine.

A game type is a subclass of :class:`RealtimeGame`. A runner holds one
instance of each game type and calls its methods for every session of that
type, passing in the session's state, so an instance keeps nothing between
calls. States, messages, views and outcomes are plain JSON values, and each
one passes through JSON between calls, so dict keys come back as strings and
tuples as lists. Build them that way from the start.

Times passed to game code are seconds on the session's own clock, which starts
at 0 and stops while no runner holds the session.
"""

import math
import numbers
from abc import ABC, abstractmethod
from dataclasses import dataclass

from dallinger.db import RESERVED_CHANNELS


class Reject(Exception):
    """Raised by :meth:`RealtimeGame.apply` to refuse a message.

    A rejected message counts as processed. It is saved with ``reason``, and
    its number and ``reason`` go to the sender's page with their next view.
    The runner can't undo changes ``apply`` made before raising, so check
    everything before changing the state.
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Sent:
    """What the sending page's envelope said about a message.

    ``number`` counts the messages the page has sent, ``browser_time`` is the
    browser's clock when it sent this one, and ``view_time``
    is the session time of the view the page was showing. All three are
    ``None`` for a frame sent without an envelope.
    """

    number: int | None = None
    browser_time: float | None = None
    view_time: float | None = None


class RealtimeGame(ABC):
    """Base class for a real-time game type.

    Subclasses set :attr:`channel` and implement :meth:`initial_state` and
    :meth:`apply`. The other methods have defaults. ``apply``, ``tick`` and
    ``on_leave`` change the state in place, and none of these methods may
    use the database.
    """

    #: The websocket channel the game's pages send messages on. It may not
    #: be a reserved channel, the experiment's ``channel``, or another game
    #: type's channel.
    channel = None

    #: How many times a second :meth:`tick` runs. At 0 it runs only at the
    #: times :meth:`next_deadline` returns.
    tick_rate = 0

    #: Seconds on the session's clock after which the session ends, whatever
    #: :meth:`is_over` says. ``None`` means no limit.
    max_duration = None

    #: Whether a player who sends a message gets a view as soon as it's
    #: processed, rather than waiting for the next tick. Games with a
    #: ``tick_rate`` of 0 send views after every change regardless.
    send_views_on_messages = True

    #: The sustained number of messages one connection may send per second.
    #: Messages over the limit are dropped and counted.
    max_messages_per_second = 120

    #: How many messages a connection may send at once, above the sustained
    #: rate, before the limit applies.
    message_burst = 20

    #: Saved with each session's state. A runner refuses state saved by a
    #: different version.
    version = 1

    @abstractmethod
    def initial_state(self, players):
        """Return the state a new session starts from.

        :param players: the participant ids of the session's members
        """

    @abstractmethod
    def apply(self, state, player_id, message, now, sent):
        """Check a player's message and apply it to ``state``.

        Raise :class:`Reject` to refuse it.

        :param state: the session's state, changed in place
        :param player_id: the sending participant's id
        :param message: the message's payload
        :param now: the session time the message was received
        :param sent: the :class:`Sent` details from the page's envelope
        """

    def tick(self, state, now):
        """Advance ``state`` to ``now``: movement, timers and deadlines."""

    def next_deadline(self, state):
        """Return the session time :meth:`tick` must next run at, or ``None``.

        Only needed when a deadline can fall between ticks.
        """
        return None

    def view(self, state, player_id):
        """Return what ``player_id`` may see of ``state``.

        Defaults to the whole state. Override it to hide anything.
        """
        return state

    def is_over(self, state):
        """Return whether the game has finished. Checked after every change."""
        return False

    def outcome(self, state, reason):
        """Return the result committed to Postgres when the session ends.

        :param reason: why the session ended
        """
        return None

    def on_leave(self, state, player_id, now):
        """Respond to ``player_id``'s last socket closing.

        By default the game continues without them.
        """

    def bot(self, view, player_id, now):
        """Return a bot member's next message, or ``None`` to send nothing.

        :param view: what the bot may see, from :meth:`view`
        :param player_id: the bot member's participant id
        :param now: the current session time
        """
        return None


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
