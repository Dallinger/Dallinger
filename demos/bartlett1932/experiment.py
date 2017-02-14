"""Bartlett's transmission chain experiment from Remembering (1932)."""

from dallinger.networks import Chain
from dallinger.experiments import Experiment


class Bartlett1932(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Call the same function in the super (see experiments.py in dallinger).

        A few properties are then overwritten.
        Finally, setup() is called.
        """
        super(Bartlett1932, self).__init__(session)
        self.experiment_repeats = 1
        self.setup()

    def setup(self):
        """Setup the networks.

        Setup only does stuff if there are no networks, this is so it only
        runs once at the start of the experiment. It first calls the same
        function in the super (see experiments.py in dallinger). Then it adds a
        source to each network.
        """
        if not self.networks():
            from bartlett1932_source import WarOfTheGhostsSource
            super(Bartlett1932, self).setup()
            for net in self.networks():
                WarOfTheGhostsSource(network=net)

    def create_network(self):
        """Return a new network."""
        return Chain(max_size=3)

    def add_node_to_network(self, node, network):
        """Add node to the chain and receive transmissions."""
        network.add_node(node)
        parent = node.neighbors(direction="from")[0]
        parent.transmit()
        node.receive()

    def recruit(self):
        """Recruit one participant at a time until all networks are full."""
        if self.networks(full=False):
            self.recruiter().recruit_participants(n=1)
        else:
            self.recruiter().close_recruitment()
