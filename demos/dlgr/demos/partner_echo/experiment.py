"""Echo each message to the sender's partner, from the process that received it."""

import json
import logging

from dallinger import networks
from dallinger.config import get_config
from dallinger.db import session
from dallinger.experiment import Experiment
from dallinger.models import Info, Participant
from dallinger.nodes import Agent

logger = logging.getLogger("experiment")


def extra_parameters():
    config = get_config()
    config.register("quorum", int)


class PartnerEcho(Experiment):
    """Two participants, each one's message delivered straight to the other.

    Every browser opens an ``/experiment-socket`` connection and subscribes to
    no channel. A message reaches ``handle_websocket_message`` on the web
    process holding the socket, and the reply is addressed to the partner by
    participant id rather than broadcast to a channel both of them watch.
    """

    def configure(self):
        config = get_config(load=True)
        self.experiment_repeats = 1
        self.quorum = config.get("quorum")
        self.initial_recruitment_size = self.quorum

    def create_network(self):
        return networks.FullyConnected(max_size=self.quorum)

    def create_node(self, participant, network):
        return Agent(network=network, participant=participant)

    def handle_websocket_message(
        self, message, *, channel_name, participant_id, scope, receive_time
    ):
        """Store one message and hand it to the partner.

        Runs on the web process that owns the sender's socket, before the next
        message is read.
        """
        data = json.loads(message)
        if data.get("type") != "message":
            return

        participant = Participant.query.get(int(participant_id))
        nodes = participant.nodes()
        if not nodes:
            logger.info("Participant %s has no node yet.", participant_id)
            return
        node = nodes[-1]
        info = Info(origin=node, contents=data.get("content", ""))
        info.creation_time = receive_time
        session.commit()

        partner_ids = [agent.participant_id for agent in node.neighbors()]
        self.publish_to_participants(
            {
                "type": "message",
                "content": info.contents,
                "sender": participant.id,
            },
            participant_ids=partner_ids,
        )
        # Back to the sender, on the page that sent it: a tab left open on an
        # earlier page named a different scope and is left alone.
        self.publish_to_participants(
            {"type": "forwarded", "to": partner_ids},
            participant_ids=[participant.id],
            scope=scope,
        )
