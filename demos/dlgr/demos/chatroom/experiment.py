"""Chatroom game."""

import logging
import dallinger as dlgr
from dallinger.compat import unicode
from dallinger.config import get_config

config = get_config()
logger = logging.getLogger(__file__)

try:
    from .bots import Bot
    # Make bot importable without triggering style warnings
    Bot = Bot
except ImportError:
    logger.error(
        "Bots not available because required packages were not installed."
    )


def extra_parameters():
    config.register('network', unicode)
    config.register('repeats', int)
    config.register('n', int)


class CoordinationChatroom(dlgr.experiment.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Initialize the experiment."""
        super(CoordinationChatroom, self).__init__(session)
        if session:
            self.setup()

    def configure(self):
        self.experiment_repeats = repeats = config.get('repeats')
        self.quorum = config.get('n')
        # Recruit for all networks at once
        self.initial_recruitment_size = repeats * self.quorum

    def create_network(self):
        """Create a new network by reading the configuration file."""
        class_ = getattr(
            dlgr.networks,
            self.config.get('network')
        )
        return class_(max_size=self.quorum)

    def choose_network(self, networks, participant):
        # Choose first available network rather than random
        return networks[0]

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""
        for agent in node.neighbors():
            node.transmit(what=info, to_whom=agent)

    def create_node(self, participant, network):
        """Create a node for a participant."""
        return dlgr.nodes.Agent(network=network, participant=participant)
