"""Define a transmission-chain experiment that transmits functional forms."""

from dallinger.experiment import Experiment
from dallinger.networks import Chain


class FunctionLearning(Experiment):
    """A function-learning experiment."""

    def __init__(self, session=None):
        """Call the same function in the super (see experiments.py in dallinger).

        The models module is imported here because it must be imported at
        runtime.

        A few properties are then overwritten.

        Finally, setup() is called.
        """
        super(FunctionLearning, self).__init__(session)
        import models
        self.models = models
        self.experiment_repeats = 1
        if session:
            self.setup()

    def setup(self):
        """Setup does stuff only if there are no networks.

        This is so it only runs once at the start of the experiment. It first
        calls the same function in the super (see experiments.py in dallinger).
        Then it adds a source to each network.
        """
        if not self.networks():
            super(FunctionLearning, self).setup()
            for net in self.networks():
                self.models.SinusoidalFunctionSource(network=net)

    def create_network(self):
        """Create a new network."""
        return Chain(max_size=3)

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
