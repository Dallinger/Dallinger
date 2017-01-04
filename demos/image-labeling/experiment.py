"""Image-labeling task."""

import base64
import os

import dallinger as dlgr


class ImageLabeling(dlgr.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        super(ImageLabeling, self).__init__(session)
        self.experiment_repeats = 1
        self.initial_recruitment_size = dlgr.config.num_participants
        self.setup()

    def setup(self):
        """Setup the networks."""
        if not self.networks():
            super(ImageLabeling, self).setup()
            for net in self.networks():
                ObjectPhotographSource(network=net)

    def add_node_to_network(self, node, network):
        """Add node to the network and receive transmissions."""
        network.add_node(node)
        source = dlgr.nodes.Source.query.one()
        source.connect(direction="to", whom=node)
        source.transmit()
        node.receive()

    def recruit(self):
        """Don't recruit new participants."""
        pass


class ObjectPhotographSource(dlgr.nodes.Source):
    """Transmits a photograph of an object."""

    __mapper_args__ = {
        "polymorphic_identity": "object_photograph_source"
    }

    def _contents(self):
        """Return an image."""
        stimuli_dir = os.path.join("static", "stimuli")
        for i in os.listdir(stimuli_dir):
            if i.endswith(".jpg"):
                with open(os.path.join(stimuli_dir, i), "rb") as f:
                    return base64.b64encode(f.read())
