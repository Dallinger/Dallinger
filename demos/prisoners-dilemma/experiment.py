"""Coordination chatroom game."""

import dallinger as dlgr


class PrisonersDilemma(dlgr.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        super(PrisonersDilemma, self).__init__(session)
        self.experiment_repeats = 1
        self.num_participants = 2
        self.initial_recruitment_size = self.num_participants
        self.quorum = self.num_participants
        self.setup()

    def create_network(self):
        """Create a new network by reading the configuration file."""
        return dlgr.networks.FullyConnected()

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""
        for agent in node.neighbors():
            node.transmit(what=info, to_whom=agent)

    def create_node(self, participant, network):
        """Create a node for a participant."""
        return dlgr.nodes.Agent(network=network, participant=participant)

    @property
    def payoffs(self):
        return [
            [[-1, -1], [-3, 0]],
            [[0, -3], [-2, -2]],
        ]
