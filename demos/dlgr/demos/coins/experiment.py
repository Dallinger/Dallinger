"""Two to four players move around an arena, collecting coins.

A demo of Dallinger's real-time engine. ``Coins`` is the game type:

- ``apply`` checks each move against the session clock, so a page can't move
  its player faster than the game allows.
- ``tick`` adds coins as time passes, 20 times a second.
- ``view`` leaves out what pages don't need, such as movement time.
- ``save_message`` keeps only the moves that collected a coin or touched a
  player.
- ``queue_effect`` and ``handle_effect`` record each steal and bounce as an
  ``Info``, since game methods can't use the database.
- ``bot`` plays for the players the bots recruiter signs up.

``CoinCollection`` starts a session when a group fills and pays a bonus from
each session's outcome. The page, ``static/scripts/experiment.js``, joins the
session and draws it.
"""

import math
import random

import requests

from dallinger import db, networks
from dallinger.bots import HighPerformanceBotBase
from dallinger.config import get_config
from dallinger.experiment import Experiment
from dallinger.models import Info, Participant
from dallinger.nodes import Agent
from dallinger.realtime import (
    RealtimeGame,
    Reject,
    create_realtime_session,
    realtime_sessions_for,
)

#: The arena's size. Positions run from 0 to these, with y increasing
#: downwards, as on the page's canvas.
WIDTH = 20
HEIGHT = 12

#: How far a player moves in a second.
SPEED = 5

#: A player collects every coin their move passes within this distance of.
REACH = 0.7

#: The most movement time a player can save up, in seconds. Moves reach the
#: game unevenly, so a player held up for a moment can catch up, but no more.
SAVED_MOVEMENT = 0.5

#: Where players start, in order of participant id.
STARTS = [[2, 2], [WIDTH - 2, HEIGHT - 2], [WIDTH - 2, 2], [2, HEIGHT - 2]]

#: The arena starts with this many coins, and another appears every
#: ``COIN_SECONDS`` while there are fewer than ``MAX_COINS``.
COINS_AT_START = 3
COIN_SECONDS = 2
MAX_COINS = 6

#: Players this close together touch, which with stealing or bouncing on is
#: when one takes the other's coin or bounces off them.
CONTACT = 1

#: With stealing on, a player robbed of a coin can't be robbed again for this
#: many seconds.
SAFE_SECONDS = 2

#: A bot goes for a coin it's at most this many times as far from as the
#: nearest other player.
BOT_MARGIN = 1.5

#: A player whose latest move was this recent is still moving, in the
#: direction of that move, when another player touches them.
MOVING_SECONDS = 0.2


def clamp(value, low, high):
    return min(high, max(low, value))


def read_move(message):
    """Return a move's ``dx``, ``dy`` and ``seconds``, or raise ``Reject``."""
    if not isinstance(message, dict):
        raise Reject("a move is {dx, dy, seconds}")
    dx, dy, seconds = message.get("dx"), message.get("dy"), message.get("seconds")
    if type(dx) is not int or type(dy) is not int or not {dx, dy} <= {-1, 0, 1}:
        raise Reject("dx and dy are each -1, 0 or 1")
    if dx == dy == 0:
        raise Reject("a move needs a direction")
    if type(seconds) not in (int, float):
        raise Reject("seconds is a positive number")
    try:
        seconds = float(seconds)
    except OverflowError:
        # An integer too big for a float
        raise Reject("seconds is a positive number") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise Reject("seconds is a positive number")
    return dx, dy, seconds


def move(x, y, dx, dy, seconds):
    """Where a player at ``x``, ``y`` ends up after moving for ``seconds``.

    A diagonal move covers the same distance as a straight one.
    """
    distance = SPEED * seconds / math.hypot(dx, dy)
    return (
        clamp(x + dx * distance, 0, WIDTH),
        clamp(y + dy * distance, 0, HEIGHT),
    )


def passes_near(x1, y1, x2, y2, coin, reach=REACH):
    """Whether a move from ``x1``, ``y1`` to ``x2``, ``y2`` comes within
    ``reach`` of ``coin``, or of anything else with an ``x`` and ``y``.
    """
    sx, sy = x2 - x1, y2 - y1
    length = sx * sx + sy * sy
    # How far along the move the closest point to the coin is, from 0 to 1
    along = (
        0 if length == 0 else ((coin["x"] - x1) * sx + (coin["y"] - y1) * sy) / length
    )
    along = clamp(along, 0, 1)
    return math.hypot(x1 + along * sx - coin["x"], y1 + along * sy - coin["y"]) <= reach


def first_contact(players, player_id, x, y):
    """The nearest other player that ``player_id``'s move from ``x``, ``y``
    runs into, or ``None``. Players already touching when the move starts
    don't touch again until they've parted.
    """
    player = players[player_id]

    def distance(other_id):
        other = players[other_id]
        return math.hypot(x - other["x"], y - other["y"])

    touched = [
        other_id
        for other_id, other in players.items()
        if other_id != player_id
        and distance(other_id) > CONTACT
        and passes_near(x, y, player["x"], player["y"], other, CONTACT)
    ]
    return min(touched, key=distance, default=None)


def touching_point(other, x, y):
    """The point at touching distance from ``other``, toward ``x``, ``y``."""
    dx, dy = x - other["x"], y - other["y"]
    scale = CONTACT / math.hypot(dx, dy)
    return other["x"] + dx * scale, other["y"] + dy * scale


def heads_toward(player, other):
    """Whether ``player``'s direction of movement points at ``other``."""
    dx, dy = player["heading"]
    return dx * (other["x"] - player["x"]) + dy * (other["y"] - player["y"]) > 0


def knock_away(player, other, distance):
    """Move ``player`` to ``distance`` beyond touching distance of ``other``,
    straight away from them.
    """
    dx, dy = player["x"] - other["x"], player["y"] - other["y"]
    away = (CONTACT + distance) / math.hypot(dx, dy)
    player["x"] = clamp(other["x"] + dx * away, 0, WIDTH)
    player["y"] = clamp(other["y"] + dy * away, 0, HEIGHT)


def knock_apart(player, other, distance):
    """Move two players apart, to ``distance`` beyond touching distance of
    each other, each the same way from where they met.
    """
    mid_x, mid_y = (player["x"] + other["x"]) / 2, (player["y"] + other["y"]) / 2
    dx, dy = player["x"] - other["x"], player["y"] - other["y"]
    half = (CONTACT + distance) / 2 / math.hypot(dx, dy)
    for one, sign in ((player, 1), (other, -1)):
        one["x"] = clamp(mid_x + sign * dx * half, 0, WIDTH)
        one["y"] = clamp(mid_y + sign * dy * half, 0, HEIGHT)


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def coin_worth_chasing(me, others, coins):
    """The nearest coin ``me`` is at most ``BOT_MARGIN`` times as far from as
    any of ``others``, or ``None``."""
    chances = [
        coin
        for coin in coins
        if distance(me, coin) <= BOT_MARGIN * min(distance(o, coin) for o in others)
    ]
    return min(chances, key=lambda coin: distance(me, coin), default=None)


#: The squares, this many units across, that a bot's part of the arena is
#: measured in. Coarser is cheaper, and a bot only needs to know roughly where
#: its part is.
TERRITORY_CELL = 2
TERRITORY_CELLS = [
    (x + TERRITORY_CELL / 2, y + TERRITORY_CELL / 2)
    for x in range(0, WIDTH, TERRITORY_CELL)
    for y in range(0, HEIGHT, TERRITORY_CELL)
]


def territory_center(me, others):
    """The middle of the part of the arena nearer to ``me`` than to any of
    ``others``. A bot that waits there is as near as it can be to wherever the
    next coin appears in its part."""

    def squared_distance(player, x, y):
        # Comparing squared distances gives the same answer without a sqrt
        return (player["x"] - x) ** 2 + (player["y"] - y) ** 2

    mine = [
        (x, y)
        for x, y in TERRITORY_CELLS
        if squared_distance(me, x, y)
        <= min(squared_distance(other, x, y) for other in others)
    ]
    if not mine:
        return me
    return {
        "x": sum(x for x, _ in mine) / len(mine),
        "y": sum(y for _, y in mine) / len(mine),
    }


def steps_toward(start, target):
    """The ``dx`` and ``dy`` that head from ``start`` toward ``target``. An
    axis within half of ``REACH`` of the target is 0."""

    def step(gap):
        if abs(gap) < REACH / 2:
            return 0
        return 1 if gap > 0 else -1

    return step(target["x"] - start["x"]), step(target["y"] - start["y"])


class Coins(RealtimeGame):
    """Players move around the arena, and each coin goes to the first player
    whose move reaches it. The game ends after ``max_duration`` seconds.

    A page sends moves as the player holds down the arrow keys, each saying
    which way the player moved and for how long, so the page can show the
    move at once by doing what ``apply`` does.

    The experiment's ``stealing`` and ``bouncing`` settings make players
    touch. A player who runs into another takes one of their coins, with
    stealing on, and knocks them ``bounce_distance`` beyond touching distance,
    with bouncing on. When the other was heading into them too, neither steals
    and both bounce apart.
    """

    channel = "coins"
    tick_rate = 20
    max_duration = 60

    # Pages send many moves a second and show their own at once, so the sender
    # gets its view with the next tick like everyone else
    send_views_on_messages = False

    def __init__(self):
        config = get_config()
        self.stealing = config.get("stealing")
        self.bouncing = config.get("bouncing")
        self.bounce_distance = config.get("bounce_distance")
        self.bot_speed = config.get("bot_speed")
        self.bonus_per_coin = config.get("bonus_per_coin")

    def initial_state(self, players):
        if not 2 <= len(players) <= len(STARTS):
            raise ValueError("Coins is for 2 to {} players.".format(len(STARTS)))
        ordered = sorted(players, key=int)
        state = {
            "players": {
                player_id: {
                    "number": number,
                    "x": x,
                    "y": y,
                    "coins": 0,
                    # The session time up to which the player's movement time
                    # is spent
                    "moved_until": 0,
                    # The direction of the player's latest move, and when
                    "heading": [0, 0],
                    "moved_at": None,
                    # Whether the player's latest move collected a coin or
                    # touched another player
                    "eventful": False,
                    # Coins the player stole and lost to stealing, and how many
                    # times they were bounced and bounced others
                    "stole": 0,
                    "coins_lost": 0,
                    "bounced": 0,
                    "bounced_others": 0,
                    # Until when the player can't be robbed
                    "safe_until": 0,
                }
                for number, (player_id, (x, y)) in enumerate(
                    zip(ordered, STARTS), start=1
                )
            },
            "coins": [],
            "next_coin_id": 0,
            "next_coin": COIN_SECONDS,
        }
        for _ in range(COINS_AT_START):
            self.add_coin(state)
        return state

    def add_coin(self, state):
        state["coins"].append(
            {
                "id": state["next_coin_id"],
                "x": round(random.uniform(1, WIDTH - 1), 2),
                "y": round(random.uniform(1, HEIGHT - 1), 2),
            }
        )
        state["next_coin_id"] += 1

    def apply(self, state, player_id, message, now, sent):
        dx, dy, seconds = read_move(message)
        player = state["players"][player_id]
        # Movement time is spent against the session clock, so however many
        # moves a page sends, its player moves no faster than SPEED
        start = max(player["moved_until"], now - SAVED_MOVEMENT)
        seconds = min(seconds, now - start)
        if seconds <= 0:
            raise Reject("moving faster than the game allows")
        player["moved_until"] = start + seconds

        x, y = player["x"], player["y"]
        stop = player["x"], player["y"] = move(x, y, dx, dy, seconds)
        player["heading"], player["moved_at"] = [dx, dy], now
        player["eventful"] = False
        other_id = None
        if self.stealing or self.bouncing:
            other_id = first_contact(state["players"], player_id, x, y)
        if other_id is not None:
            point = touching_point(state["players"][other_id], x, y)
            stop = self.touch(state, player_id, other_id, now, point)
        # Messages are applied in the order they arrived, so the coin goes to
        # whoever reached it first
        for coin in list(state["coins"]):
            if passes_near(x, y, *stop, coin):
                state["coins"].remove(coin)
                player["coins"] += 1
                player["eventful"] = True

    def touch(self, state, player_id, other_id, now, point):
        """Settle ``player_id``'s move running into ``other_id`` at ``point``,
        by the rules on, and return where the move ended before any knock.
        Each steal and bounce is queued as an effect, so it's in the session's
        record.
        """
        player, other = state["players"][player_id], state["players"][other_id]
        player["eventful"] = True
        stop = player["x"], player["y"]
        if self.bouncing:
            # A player who runs into another stops where they touched
            stop = player["x"], player["y"] = point
        at = [round(point[0], 2), round(point[1], 2)]
        moving = other["moved_at"] is not None and now - other["moved_at"] <= (
            MOVING_SECONDS
        )
        # Judged where they touched, since without bouncing the move can end
        # beyond the other player
        if moving and heads_toward(other, {"x": point[0], "y": point[1]}):
            # Head on: neither steals, and each bounces the other
            if self.bouncing:
                knock_apart(player, other, self.bounce_distance)
                for by, bounced in ((player_id, other_id), (other_id, player_id)):
                    state["players"][by]["bounced_others"] += 1
                    state["players"][bounced]["bounced"] += 1
                    self.queue_effect(
                        "bounce", {"by": by, "bounced": bounced, "at": at}
                    )
            return stop
        if self.stealing and other["coins"] > 0 and now >= other["safe_until"]:
            other["coins"] -= 1
            other["safe_until"] = now + SAFE_SECONDS
            player["coins"] += 1
            player["stole"] += 1
            other["coins_lost"] += 1
            self.queue_effect("steal", {"by": player_id, "from": other_id, "at": at})
        if self.bouncing:
            knock_away(other, player, self.bounce_distance)
            other["bounced"] += 1
            player["bounced_others"] += 1
            self.queue_effect(
                "bounce", {"by": player_id, "bounced": other_id, "at": at}
            )
        return stop

    def handle_effect(self, name, payload, session_row):
        # Each steal and bounce also becomes an Info on the node of the player
        # who did it, so it's in the experiment tables
        # A player who has since been failed has no node to add it to, and
        # the effect is still in the session's record
        nodes = Participant.query.get(int(payload["by"])).nodes()
        if nodes:
            db.session.add(Info(origin=nodes[0], contents=name, details=payload))

    def save_message(self, state, player_id, message, rejection):
        # Only the moves that collected a coin or touched another player go in
        # the record, which then can't replay where players went between
        # checkpoints
        return rejection is None and state["players"][player_id]["eventful"]

    def tick(self, state, now):
        while now >= state["next_coin"]:
            if len(state["coins"]) < MAX_COINS:
                self.add_coin(state)
            state["next_coin"] += COIN_SECONDS

    def view(self, state, player_id):
        return {
            "me": player_id,
            "players": {
                other_id: {
                    "number": player["number"],
                    "x": player["x"],
                    "y": player["y"],
                    "coins": player["coins"],
                    "safe_until": player["safe_until"],
                    "stole": player["stole"],
                    "coins_lost": player["coins_lost"],
                    "bounced": player["bounced"],
                    "bounced_others": player["bounced_others"],
                }
                for other_id, player in state["players"].items()
            },
            "coins": state["coins"],
            "end": self.max_duration,
            "stealing": self.stealing,
            "bouncing": self.bouncing,
            "bonus_per_coin": self.bonus_per_coin,
        }

    def outcome(self, state, reason):
        players = state["players"].items()
        return {
            name: {player_id: player[name] for player_id, player in players}
            for name in ("coins", "stole", "coins_lost", "bounced", "bounced_others")
        }

    def bot(self, view, player_id, now):
        """Make one move a tick, each ``bot_speed`` ticks' worth of time, so a
        ``bot_speed`` below 1 makes bots slower than players.

        A bot goes for the nearest coin it has a chance of reaching first.
        With none, it waits in the middle of the part of the arena nearer to it
        than to anyone else, so bots spread out and each is ready for the next
        coin that appears in its part.
        """
        me = view["players"][player_id]
        others = [p for other_id, p in view["players"].items() if other_id != player_id]
        coin = coin_worth_chasing(me, others, view["coins"])
        if coin is not None:
            dx, dy = steps_toward(me, coin)
            if dx == dy == 0:
                # A coin can appear within reach of a bot standing still, and
                # only a move collects it
                dx = 1 if coin["x"] >= me["x"] else -1
        else:
            dx, dy = steps_toward(me, territory_center(me, others))
            if dx == dy == 0:
                return None
        return {"dx": dx, "dy": dy, "seconds": self.bot_speed / self.tick_rate}


class CoinCollection(Experiment):
    """Groups of players, each group playing one game of coins."""

    realtime_games = [Coins]

    @classmethod
    def extra_parameters(cls):
        config = get_config()
        config.register("groups", int)
        config.register("players_per_group", int)
        config.register("stealing", bool)
        config.register("bouncing", bool)
        config.register("bounce_distance", float)
        config.register("bot_speed", float)
        config.register("bonus_per_coin", float)

    @classmethod
    def config_defaults(cls):
        return {
            "groups": 1,
            "players_per_group": 2,
            "stealing": False,
            "bouncing": False,
            "bounce_distance": 1.0,
            "bot_speed": 0.8,
            "bonus_per_coin": 0.02,
        }

    def configure(self):
        super().configure()
        config = get_config()
        # Also read by the instructions page, which describes the settings
        self.stealing = config.get("stealing")
        self.bouncing = config.get("bouncing")
        self.bonus_per_coin = config.get("bonus_per_coin")
        self.players_per_group = config.get("players_per_group")
        if not 2 <= self.players_per_group <= len(STARTS):
            raise ValueError(
                "players_per_group must be from 2 to {}.".format(len(STARTS))
            )
        self.experiment_repeats = config.get("groups")
        self.initial_recruitment_size = self.players_per_group * self.experiment_repeats

    def create_network(self):
        return networks.Empty(max_size=self.players_per_group)

    def create_node(self, participant, network):
        return Agent(network=network, participant=participant)

    def add_node_to_network(self, node, network):
        network.add_node(node)
        if network.full:
            players = [n.participant for n in network.nodes()]
            # Bots recruited by HighPerformanceBotBase never open the page, so
            # the game type's bot method plays for them
            bots = [p.id for p in players if p.recruiter_id.startswith("bots:")]
            create_realtime_session(Coins, [p.id for p in players], bots=bots)

    def bonus(self, participant):
        # Only games that ended normally pay
        coins = 0
        for session in realtime_sessions_for(participant, Coins):
            if session.status == "ended":
                coins += session.outcome["coins"][str(participant.id)]
        return round(coins * self.bonus_per_coin, 2)


class Bot(HighPerformanceBotBase):
    """Joins a group without opening the game's page. The game type's ``bot``
    method makes its moves.

    The bot signs off once it has joined. The experiment isn't complete while
    the game is running, so it's still played to the end.
    """

    def participate(self):
        url = "{}/node/{}".format(self.host, self.participant_id)
        result = requests.post(url)
        if not result.ok:
            self.log("Couldn't join a group: {}".format(result.text))
