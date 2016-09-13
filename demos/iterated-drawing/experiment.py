"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from dallinger.networks import Chain
from dallinger.nodes import Source
from dallinger.experiments import Experiment
import random
import base64
import os
import json


class IteratedDrawing(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Call the same function in the super (see experiments.py in dallinger).

        A few properties are then overwritten.
        Finally, setup() is called.
        """
        super(IteratedDrawing, self).__init__(session)
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
            super(IteratedDrawing, self).setup()
            for net in self.networks():
                DrawingSource(network=net)

    def create_network(self):
        """Return a new network."""
        return Chain(max_size=10)

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


class DrawingSource(Source):
    """A Source that reads in a random image from a file and transmits it."""

    __mapper_args__ = {
        "polymorphic_identity": "drawing_source"
    }

    def _contents(self):
        """Define the contents of new Infos.

        transmit() -> _what() -> create_information() -> _contents().
        """
        images = [
            "owl.png",
        ]

        image = random.choice(images)

        image_path = os.path.join("static", "stimuli", image)
        uri_encoded_image = (
            "data:image/png;base64," +
            base64.b64encode(open(image_path, "rb").read())
        )

        return json.dumps({
            "image": uri_encoded_image,
            "sketch": ""
        })
