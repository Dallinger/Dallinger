"""Coordination chatroom game."""

import dallinger as dlgr


class CoordinationChatroom(dlgr.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        super(CoordinationChatroom, self).__init__(session)
        self.experiment_repeats = 1
        self.num_participants = dlgr.config.experiment_configuration.n
        self.initial_recruitment_size = self.num_participants
        self.quorum = self.num_participants
        self.setup()

    def create_network(self):
        """Create a new network by reading the configuration file."""
        class_ = getattr(
            dlgr.networks,
            dlgr.config.experiment_configuration.network
        )
        return class_(max_size=self.num_participants)

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""
        for agent in node.neighbors():
            node.transmit(what=info, to_whom=agent)

    def create_node(self, participant, network):
        """Create a node for a participant."""
        return dlgr.nodes.Agent(network=network, participant=participant)
