"""Coordination chatroom game."""

import dallinger as dlgr
from dallinger.config import get_config
try:
    unicode = unicode
except NameError:  # Python 3
    unicode = str

config = get_config()


def extra_settings():
    config.register('network', unicode)
    config.register('n', int)


class CoordinationChatroom(dlgr.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        super(CoordinationChatroom, self).__init__(session)
        self.experiment_repeats = 1
        self.num_participants = config.get('n')
        self.initial_recruitment_size = self.num_participants
        self.quorum = self.num_participants
        self.config = config
        if not self.config.ready:
            self.config.load_config()
        self.setup()

    def create_network(self):
        """Create a new network by reading the configuration file."""
        class_ = getattr(
            dlgr.networks,
            self.config.get('network')
        )
        return class_(max_size=self.num_participants)

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""
        for agent in node.neighbors():
            node.transmit(what=info, to_whom=agent)

    def create_node(self, participant, network):
        """Create a node for a participant."""
        return dlgr.nodes.Agent(network=network, participant=participant)
