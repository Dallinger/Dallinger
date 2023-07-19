"""Chatroom game."""

import json
import logging

from dallinger import db, networks
from dallinger.compat import unicode
from dallinger.config import get_config
from dallinger.experiment import Experiment
from dallinger.models import Info
from dallinger.nodes import Agent

try:
    from .bots import Bot

    Bot = Bot  # Make name "Bot" importable without triggering style warnings
except ImportError:
    pass

logger = logging.getLogger(__file__)


def extra_parameters():
    config = get_config()
    config.register("network", unicode)
    config.register("repeats", int)
    config.register("n", int)
    config.register("quorum", int)


class WebSocketChatroom(Experiment):
    """Define the structure of the experiment."""

    channel = "chatroom"

    def __init__(self, session=None):
        """Initialize the experiment."""
        super(WebSocketChatroom, self).__init__(session)
        if session:
            self.setup()

    def configure(self):
        config = get_config()
        self.experiment_repeats = repeats = config.get("repeats")
        self.network_class = config.get("network")
        self.quorum = config.get("quorum")
        self.max_recruits = config.get("n")
        # Recruit for all networks at once
        self.initial_recruitment_size = repeats * (self.max_recruits or self.quorum)

    def create_network(self):
        """Create a new network by reading the configuration file."""
        class_ = getattr(networks, self.network_class)
        return class_(max_size=self.initial_recruitment_size)

    def choose_network(self, networks, participant):
        # Choose first available network rather than random
        return networks[0]

    def create_node(self, participant, network):
        """Create a node for a participant."""
        return Agent(network=network, participant=participant)

    def is_overrecruited(self, waiting_count):
        """A True value indicates that subsequent users should skip the
        experiment. Returns True if the experiment has been marked as
        completed, or if the number of people recruited is in excess of
        the total allowed. A value of 0 for quorum or total recruits means we
        don't limit recruitment, and always return False here.
        """
        networks = self.networks(full=False)
        if networks and networks[0].details.get("completed", False):
            return True
        if not self.quorum or not self.max_recruits:
            return False
        return waiting_count > self.max_recruits

    def receive_message(
        self, message, channel_name=None, participant=None, node=None, receive_time=None
    ):
        """We recieve all messages coming into the ``chatroom`` channel along with
        the ``dallinger_control`` channel. We store all user messages as
        transmissions, but let the broadcast happen in the websocket channel.

        We send control messages back to the ``chatroom`` channel as log message
        so that clients can display them separate from chat messages.
        """
        message = json.loads(message)
        # Get the node if we can
        if participant and not node:
            nodes = participant.nodes()
            if len(nodes):
                node = participant.nodes()[-1]

        # Create an info for the message with details stored
        connected_neighbors = []
        if node:
            content = message.get("content", "")
            info = Info(origin=node, contents=content, details=message)
            if receive_time:
                info.creation_time = receive_time

            connected_neighbors = [
                a for a in node.neighbors() if a.details.get("subscribed", True)
            ]

        # Handle control messages by marking nodes as connected/subscribed and
        # sending log info to clients via the chatroom channel
        if channel_name == "dallinger_control":
            log_output = None
            if participant and message.get("event"):
                log_output = "Participant {} {}.".format(
                    participant.id, message["event"]
                )
                db.redis_conn.publish(
                    "chatroom",
                    json.dumps(
                        {
                            "type": "log",
                            "content": log_output,
                        }
                    ),
                )

            # Mark channel as (un)subscribed based on admin messages
            if (
                node
                and message.get("type") == "channel"
                and message.get("channel") == "chatroom"
            ):
                details = dict(node.details or {})
                details["subscribed"] = (
                    message.get("event", "subscribed") == "subscribed"
                )
                # We need to set details to a new value
                node.details = details
                self.session.add(node)

                # If we get an unsubscribe from the last connected member, we
                # send a specific message suggest ending the chat.
                if message["event"] == "unsubscribed":
                    if len(connected_neighbors) <= 1:
                        # No connections remaining, notify
                        db.redis_conn.publish(
                            "chatroom",
                            json.dumps(
                                {
                                    "type": "log",
                                    "action": "finish",
                                    "content": 'All other participants have left the chat. Click "Leave chat" to finish.',
                                }
                            ),
                        )
                        # Mark as completed and don't allow more participants to join
                        net_details = dict(node.network.details)
                        net_details["completed"] = True
                        node.network.details = net_details
                        self.session.add(node.network)
                        self.recruiter.close_recruitment()

        # If the message was sent to the chatroom we create transmissions to all
        # subcribed nodes.
        if channel_name == "chatroom" and connected_neighbors:
            transmissions = node.transmit(what=info, to_whom=connected_neighbors)
            if receive_time:
                for transmission in transmissions:
                    transmission.created_time = receive_time

        self.session.commit()
