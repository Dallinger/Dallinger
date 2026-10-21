"""A buyer and a seller bargain over a price, each knowing only their own value.

A demo of Dallinger's real-time engine. ``Bargain`` is the game type, the
rules of one round:

- ``initial_state`` draws the roles and private values.
- ``apply`` handles each offer and accept, and refuses what the rules don't
  allow.
- ``on_join`` starts the clock once both players are here.
- ``next_deadline`` and ``tick`` end the round when time runs out.
- ``view`` is what each player sees, which hides the other's value.
- ``outcome`` is what's saved when a round ends, and the bonus is paid from.
- ``queue_effect`` and ``handle_effect`` start the next round.
- ``bot`` makes a bot's moves.

``Bargaining`` is the experiment: it starts each pair's first round, saves
and relays chat, and pays the bonus. The page,
``static/scripts/experiment.js``, shows each round to the player.
"""

import json
import logging
import random
import re

import requests

from dallinger import db, networks
from dallinger.bots import HighPerformanceBotBase
from dallinger.config import get_config
from dallinger.experiment import Experiment
from dallinger.models import Info, Participant, RealtimeSession
from dallinger.nodes import Agent
from dallinger.realtime import (
    RealtimeGame,
    Reject,
    create_realtime_session,
    realtime_sessions_for,
)

logger = logging.getLogger(__name__)

#: Prices are whole cents in this range.
LOWEST_PRICE = 0
HIGHEST_PRICE = 100

#: The ranges the seller's cost and the buyer's value are drawn from. They
#: overlap, so some pairs have no price that leaves both of them better off.
COSTS = (10, 60)
VALUES = (40, 90)

#: A round's clock starts once both players are here. If one still isn't
#: this many seconds into the round, the clock starts anyway, so a player who
#: never opens the page can't hold the round open.
JOIN_SECONDS = 30

#: A bot concedes this much each time the other player makes an offer, and
#: accepts an offer that earns it at least this much.
BOT_STEP = 5
BOT_MARGIN = 5

#: Pages send chat messages to this channel, the experiment's own, so that
#: the experiment can save them before passing them on.
CHAT_CHANNEL = "bargain_chat"

#: Longer chat messages are cut to this many characters.
CHAT_LENGTH = 500


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
        # The settings in config.txt
        config = get_config()
        self.bargaining_seconds = config.get("bargaining_seconds")
        self.rounds = config.get("rounds")

    def initial_state(self, players):
        # Each round draws new roles and values
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
            # The players who have arrived
            "present": [],
            # When the clock started and runs out, in seconds into the round
            "started": None,
            "deadline": None,
            "closed": False,
        }

    def apply(self, state, player_id, message, now, sent):
        # The player sees a Reject's reason. A refused message mustn't change
        # anything, so every check comes before the first change.
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
            # The page says which price it accepts, in case the other player
            # changed their offer a moment ago
            if message["accept"] != price:
                raise Reject("that offer has changed")
            if gain(role, value, price) < 0:
                raise Reject("that price would lose you money")
            state["deal"] = price
            self.request_next_round()
        else:
            raise Reject("a message is an offer or an accept")

    def on_join(self, state, player_id, now):
        # Called when a player's page opens, and for a bot, which has no page,
        # as the round starts. Starts the clock once both players are here.
        if player_id not in state["present"]:
            state["present"].append(player_id)
        if state["started"] is None and len(state["present"]) == len(state["roles"]):
            self.start_clock(state, now)

    def start_clock(self, state, now):
        state["started"] = now
        state["deadline"] = now + self.bargaining_seconds

    def next_deadline(self, state):
        # Dallinger calls tick at this time: when the round's time runs out,
        # or before the clock has started, when it stops waiting for players
        return JOIN_SECONDS if state["deadline"] is None else state["deadline"]

    def tick(self, state, now):
        if state["deadline"] is None:
            if now >= JOIN_SECONDS:
                self.start_clock(state, now)
        elif now >= state["deadline"]:
            state["closed"] = True
            self.request_next_round()

    def is_over(self, state):
        return state["deal"] is not None or state["closed"]

    def view(self, state, player_id):
        # Pages only ever see the view, so what's left out here stays hidden
        # from the player
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
            "started": state["started"],
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

    def request_next_round(self):
        """Ask ``handle_effect`` to start the pair's next round.

        Game methods can't use the database, which starting a session needs,
        so they queue an effect, and Dallinger passes it to ``handle_effect``
        on a worker that can.
        """
        if self.rounds > 1:
            self.queue_effect("bargain_over", {})

    def handle_effect(self, name, payload, session_row):
        # The next round is saved no later than this round's ending, so pages
        # and bots that see the ending can already find it
        played = realtime_sessions_for(session_row.members[0], Bargain)
        if len(played) >= self.rounds:
            return
        # An error here would also undo saving the round just played, and its
        # pay, so it's logged instead. Pages stop waiting for the next round.
        try:
            create_realtime_session(Bargain, session_row.members, bots=session_row.bots)
        except Exception:
            logger.exception(
                "Could not start the next round after session %s.", session_row.id
            )

    def bot(self, view, player_id, now):
        """Accept an offer that earns at least ``BOT_MARGIN``, and otherwise
        concede ``BOT_STEP`` cents for each offer the other player has made.

        Bots answer each other at once, so two bots play a whole round the
        moment it starts.
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
        # A bot is asked again after every change, so it must send nothing
        # once it has nothing new to say, or the round stalls
        if price == view["my_offer"]:
            return None
        return {"offer": price}


#: Bots chat like Weizenbaum's ELIZA, turning the player's own words around
#: without understanding them, so they give nothing away about the bargain.
#: The first pattern that matches gives the answer.
ELIZA_PATTERNS = [
    (r"\b(?:hi|hello|hey)\b", "Hello. How do you feel about this bargain?"),
    (r"\bi need (.+)", "Why do you need {}?"),
    (r"\bi think (.+)", "Do you really think {}?"),
    (r"\bi want (.+)", "What would it mean to you to get {}?"),
    (r"\bi(?: am|'m) (.+)", "How long have you been {}?"),
    (r"\byou(?: are|'re) (.+)", "What makes you think I'm {}?"),
    (r"\bbecause\b", "Is that the real reason?"),
    (r"\b(\d+)\b", "Why {}?"),
    (r"\?$", "Why do you ask?"),
]
ELIZA_FALLBACKS = ["Tell me more.", "I see.", "How does that make you feel?", "Go on."]

#: Swaps "my offer" for "your offer", and so on.
REFLECTIONS = {
    "i": "you",
    "me": "you",
    "my": "your",
    "am": "are",
    "i'm": "you're",
    "you": "I",
    "your": "my",
    "you're": "I'm",
}


def eliza_reply(text):
    """A bot's answer to a chat message."""
    text = text.lower().strip()
    for pattern, answer in ELIZA_PATTERNS:
        match = re.search(pattern, text)
        if match:
            words = match.group(1).rstrip(".!?").split() if match.groups() else []
            return answer.format(" ".join(REFLECTIONS.get(w, w) for w in words))
    return random.choice(ELIZA_FALLBACKS)


class Bargaining(Experiment):
    """Pairs of participants, each pair playing one or more bargains."""

    realtime_games = [Bargain]

    @classmethod
    def extra_parameters(cls):
        config = get_config()
        config.register("pairs", int)
        config.register("bargaining_seconds", int)
        config.register("rounds", int)
        config.register("chat", bool)

    @classmethod
    def config_defaults(cls):
        return {"pairs": 1, "bargaining_seconds": 60, "rounds": 1, "chat": False}

    def configure(self):
        super().configure()
        config = get_config()
        # The instructions and game pages read these too
        self.bargaining_seconds = config.get("bargaining_seconds")
        self.rounds = config.get("rounds")
        self.chat = config.get("chat")
        if self.rounds < 1:
            raise ValueError("rounds must be at least 1.")
        # Messages sent to the experiment's channel reach receive_message
        self.channel = CHAT_CHANNEL if self.chat else None
        self.experiment_repeats = config.get("pairs")
        self.initial_recruitment_size = 2 * self.experiment_repeats

    def create_network(self):
        return networks.Empty(max_size=2)

    def create_node(self, participant, network):
        return Agent(network=network, participant=participant)

    def add_node_to_network(self, node, network):
        network.add_node(node)
        if network.full:
            players = [n.participant for n in network.nodes()]
            # Bots like the demo's Bot never open the page, so the game's bot
            # method plays for them
            bots = [p.id for p in players if p.recruiter_id.startswith("bots:")]
            create_realtime_session(Bargain, [p.id for p in players], bots=bots)

    def receive_message(
        self, message, channel_name=None, participant=None, node=None, receive_time=None
    ):
        """Save a chat message, send it to both players, and answer it for any
        bot in the session.

        Runs on a worker. Chat goes to the experiment rather than the game, so
        it never reaches ``apply``.
        """
        # The channel also carries Dallinger's notices of pages connecting
        if channel_name != CHAT_CHANNEL or participant is None:
            return
        chat = json.loads(message)
        if not isinstance(chat, dict):
            return
        text, session_id = chat.get("text"), chat.get("session")
        if not isinstance(text, str) or not text.strip() or type(session_id) is not int:
            return
        # The page names the sender, and nothing verifies it, so this keeps
        # chat within the pair but can't stop a player posing as their partner
        session = db.session.get(RealtimeSession, session_id)
        if session is None or participant.id not in session.members:
            return
        text = text.strip()[:CHAT_LENGTH]
        self.post_chat(participant, session, text, receive_time)
        # Bots have no page, so the experiment chats for them
        for bot_id in session.bots:
            if bot_id != participant.id:
                bot = Participant.query.get(bot_id)
                self.post_chat(bot, session, eliza_reply(text))

    def post_chat(self, participant, session, text, received_at=None):
        """Save a chat message as an ``Info`` on the sender's node, and send it
        to both players once it's saved."""
        info = Info(
            origin=participant.nodes()[0],
            contents=text,
            details={"session": session.id},
        )
        if received_at:
            info.creation_time = received_at
        db.session.add(info)
        relayed = {"session": session.id, "from": participant.id, "text": text}
        players = list(session.members)
        db.run_after_commit(lambda: self.publish_to_participants(relayed, players))

    def bonus(self, participant):
        # Every round pays, unless it failed
        cents = 0
        for session in realtime_sessions_for(participant, Bargain):
            if session.status == "ended":
                cents += session.outcome["earnings"][str(participant.id)]
        return cents / 100


class Bot(HighPerformanceBotBase):
    """Joins a pair without opening the game's page. The game type's ``bot``
    method makes its offers.

    The bot signs off once it has joined. The experiment isn't complete while
    any round is running, so its rounds are still played to the end.
    """

    def participate(self):
        url = "{}/node/{}".format(self.host, self.participant_id)
        result = requests.post(url)
        if not result.ok:
            self.log("Couldn't join a pair: {}".format(result.text))
