"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from wallace.networks import Chain
from wallace.nodes import Source
from wallace.experiments import Experiment
import random
import json
import os
import base64


class IteratedDrawing(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Call the same function in the super (see experiments.py in wallace).

        A few properties are then overwritten.
        Finally, setup() is called.
        """
        super(IteratedDrawing, self).__init__(session)
        self.experiment_repeats = 10
        self.initial_recruitment = 10
        self.setup()

    def setup(self):
        """Setup the networks.

        Setup only does stuff if there are no networks, this is so it only
        runs once at the start of the experiment. It first calls the same
        function in the super (see experiments.py in wallace). Then it adds a
        source to each network.
        """
        if not self.networks():
            super(IteratedDrawing, self).setup()
            for net in self.networks():
                CharacterSource(network=net)

    def create_network(self):
        """Return a new network."""
        return Chain(max_size=11)

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


class CharacterSource(Source):
    """Transmit handwritten characters from a local folder."""

    __mapper_args__ = {
        "polymorphic_identity": "character_source"
    }

    def _contents(self):
        """Read in the images."""
        img_root = "static/images/characters"
        filenames = os.listdir(img_root)
        random.shuffle(filenames)
        data = []
        for fn in filenames:
            if ".png" in fn:
                # Encode the image in base64.
                encoded = base64.b64encode(
                    open(os.path.join(img_root, fn), "rb").read())

                data.append({
                    "name": fn,
                    "image": "data:image/png;base64," + encoded,
                    "drawing": "",
                })

        return json.dumps(data)
