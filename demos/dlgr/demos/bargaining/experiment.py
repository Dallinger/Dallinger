"""A buyer and a seller bargain over a price, each knowing only their own value."""

import random

import requests

from dallinger import networks
from dallinger.bots import HighPerformanceBotBase
from dallinger.config import get_config
from dallinger.experiment import Experiment
from dallinger.nodes import Agent
from dallinger.realtime import (
    RealtimeGame,
    Reject,
    create_realtime_session,
    realtime_sessions_for,
)

#: Prices are whole cents in this range.
LOWEST_PRICE = 0
HIGHEST_PRICE = 100

#: The ranges the seller's cost and the buyer's value are drawn from. They
#: overlap, so some pairs have no price that leaves both of them better off.
COSTS = (10, 60)
VALUES = (40, 90)

#: A bot concedes this much each time the other player makes an offer, and
#: accepts an offer that earns it at least this much.
BOT_STEP = 5
BOT_MARGIN = 5


def other_role(role):
    return "buyer" if role == "seller" else "seller"


def gain(role, value, price):
    """What a player in ``role`` with ``value`` earns from a deal at ``price``."""
    return price - value if role == "seller" else value - price


class Bargain(RealtimeGame):
    """One seller and one buyer, bargaining until they agree or time runs out.

    A deal pays the seller the price minus their cost, and the buyer their
    value minus the price. No deal pays nothing.
    """

    channel = "bargain"

    def __init__(self):
        self.bargaining_seconds = get_config().get("bargaining_seconds")

    def initial_state(self, players):
        seller, buyer = random.sample(players, 2)
        return {
            "roles": {seller: "seller", buyer: "buyer"},
            "values": {
                seller: random.randint(*COSTS),
                buyer: random.randint(*VALUES),
            },
            # Each role's current offer, which the other player can accept
            "standing": {"seller": None, "buyer": None},
            "offers": [],
            "deal": None,
            "deadline": self.bargaining_seconds,
            "closed": False,
        }

    def apply(self, state, player_id, message, now, sent):
        role = state["roles"][player_id]
        value = state["values"][player_id]
        if not isinstance(message, dict):
            raise Reject("a message is an offer or an accept")
        if "offer" in message:
            price = message["offer"]
            if type(price) is not int or not LOWEST_PRICE <= price <= HIGHEST_PRICE:
                raise Reject(
                    "a price is a whole number of cents from {} to {}".format(
                        LOWEST_PRICE, HIGHEST_PRICE
                    )
                )
            if gain(role, value, price) < 0:
                raise Reject("that price would lose you money")
            state["standing"][role] = price
            state["offers"].append({"by": role, "price": price, "time": now})
        elif "accept" in message:
            price = state["standing"][other_role(role)]
            if price is None:
                raise Reject("there's no offer to accept")
            # The page says which price it accepted, in case the other player
            # changed their offer just before this message arrived
            if message["accept"] != price:
                raise Reject("that offer has changed")
            if gain(role, value, price) < 0:
                raise Reject("that price would lose you money")
            state["deal"] = price
        else:
            raise Reject("a message is an offer or an accept")

    def next_deadline(self, state):
        return state["deadline"]

    def tick(self, state, now):
        if now >= state["deadline"]:
            state["closed"] = True

    def is_over(self, state):
        return state["deal"] is not None or state["closed"]

    def view(self, state, player_id):
        # The other player's value stays hidden until the game is over
        role = state["roles"][player_id]
        other = other_role(role)
        over = self.is_over(state)
        (other_id,) = [p for p in state["roles"] if p != player_id]
        return {
            "role": role,
            "value": state["values"][player_id],
            "my_offer": state["standing"][role],
            "their_offer": state["standing"][other],
            "offers": state["offers"],
            "deadline": state["deadline"],
            "deal": state["deal"],
            "their_value": state["values"][other_id] if over else None,
            "earnings": self.earnings(state)[player_id] if over else None,
        }

    def earnings(self, state):
        """Each player's earnings in cents, by player id."""
        price = state["deal"]
        return {
            player_id: 0
            if price is None
            else gain(role, state["values"][player_id], price)
            for player_id, role in state["roles"].items()
        }

    def outcome(self, state, reason):
        return {
            "roles": state["roles"],
            "values": state["values"],
            "deal": state["deal"],
            "earnings": self.earnings(state),
        }

    def bot(self, view, player_id, now):
        """Accept an offer that earns at least ``BOT_MARGIN``, and otherwise
        concede ``BOT_STEP`` cents for each offer the other player has made.

        Bots answer each other at once, so a pair of bots plays out the whole
        bargain the moment it starts.
        """
        role, value = view["role"], view["value"]
        theirs = view["their_offer"]
        if theirs is not None and gain(role, value, theirs) >= BOT_MARGIN:
            return {"accept": theirs}
        replies = sum(1 for offer in view["offers"] if offer["by"] != role)
        if role == "seller":
            price = max(value + BOT_MARGIN, HIGHEST_PRICE - BOT_STEP * replies)
        else:
            price = min(value - BOT_MARGIN, LOWEST_PRICE + BOT_STEP * replies)
        if price == view["my_offer"]:
            return None
        return {"offer": price}


class Bargaining(Experiment):
    """Pairs of participants, each pair playing one bargain."""

    realtime_games = [Bargain]

    @classmethod
    def extra_parameters(cls):
        config = get_config()
        config.register("pairs", int)
        config.register("bargaining_seconds", int)

    @classmethod
    def config_defaults(cls):
        return {"pairs": 1, "bargaining_seconds": 60}

    def configure(self):
        super().configure()
        self.experiment_repeats = get_config().get("pairs")
        self.initial_recruitment_size = 2 * self.experiment_repeats

    def create_network(self):
        return networks.Empty(max_size=2)

    def create_node(self, participant, network):
        return Agent(network=network, participant=participant)

    def add_node_to_network(self, node, network):
        network.add_node(node)
        if network.full:
            players = [n.participant for n in network.nodes()]
            # Bots recruited by HighPerformanceBotBase never open the page, so
            # the game type's bot method plays for them
            bots = [p.id for p in players if p.recruiter_id.startswith("bots:")]
            create_realtime_session(Bargain, [p.id for p in players], bots=bots)

    def bonus(self, participant):
        cents = 0
        for session in realtime_sessions_for(participant, Bargain):
            if session.status == "ended":
                cents += session.outcome["earnings"][str(participant.id)]
        return cents / 100


class Bot(HighPerformanceBotBase):
    """Joins a pair without opening the game's page. The game type's ``bot``
    method makes its offers.
    """

    def participate(self):
        url = "{}/node/{}".format(self.host, self.participant_id)
        result = requests.post(url)
        if not result.ok:
            self.log("Couldn't join a pair: {}".format(result.text))
            return
        self.wait_for_realtime_sessions(Bargain)
