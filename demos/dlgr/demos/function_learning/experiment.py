"""Define a transmission-chain experiment that transmits functional forms."""

from dallinger import db
from dallinger.experiment import Experiment
from dallinger.networks import Chain

from . import models


class FunctionLearning(Experiment):
    """A function-learning experiment."""

    experiment_repeats = 1

    def setup(self):
        """Setup does stuff only if there are no networks.

        This is so it only runs once at the start of the experiment. It first
        calls the same function in the super (see experiments.py in dallinger).
        Then it adds a source to each network.
        """
        if not self.networks():
            super(FunctionLearning, self).setup()
            for net in self.networks():
                models.SinusoidalFunctionSource(network=net)
            db.session.commit()

    def create_network(self):
        """Create a new network."""
        return Chain(max_size=2)

    def add_node_to_network(self, node, network):
        """When an agent is created, add it to the network and take a step."""
        network.add_node(node)
        parent = node.neighbors(direction="from")[0]
        parent.transmit()
        node.receive()

    def recruit(self):
        """Recruit one participant at a time until all networks are full."""
        if self.networks(full=False):
            self.recruiter.recruit(n=1)
        else:
            self.recruiter.close_recruitment()
