"""Define a transmission-chain experiment that transmits functional forms."""

from dallinger.experiments import Experiment
from dallinger.networks import Chain


class FunctionLearning(Experiment):
    """A function-learning experiment."""

    def __init__(self, session):
        """Call the same function in the super (see experiments.py in dallinger).

        A few properties are then overwritten. Finally, setup() is called.
        """
        super(FunctionLearning, self).__init__(session)
        self.experiment_repeats = 1
        self.setup()

    def setup(self):
        """Setup does stuff only if there are no networks.

        This is so it only runs once at the start of the experiment. It first
        calls the same function in the super (see experiments.py in dallinger).
        Then it adds a source to each network.
        """
        if not self.networks():
            from sources import SinusoidalFunctionSource
            super(FunctionLearning, self).setup()
            for net in self.networks():
                SinusoidalFunctionSource(network=net)

    def create_network(self):
        """Create a new network."""
        return Chain(max_size=3)

    def add_node_to_network(self, node, network):
        """When an agent is created, add it to the network and take a step."""
        network.add_node(node)
        parent = node.neighbors(direction="from")[0]
        parent.transmit()
        node.receive()
