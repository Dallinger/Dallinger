"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from dallinger.networks import Empty
from dallinger.experiment import Experiment


class VoxPopuli(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Call the same function in the super (see experiments.py in dallinger).

        A few properties are then overwritten.
        Finally, setup() is called.
        """
        super(VoxPopuli, self).__init__(session)
        self.experiment_repeats = 1
        self.initial_recruitment = 20
        if session:
            self.setup()

    def create_network(self):
        """Return a new network."""
        return Empty(max_size=20)
