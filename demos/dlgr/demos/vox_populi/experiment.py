"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from dallinger.experiment import Experiment
from dallinger.networks import Empty


class VoxPopuli(Experiment):
    """Define the structure of the experiment."""

    experiment_repeats = 1
    initial_recruitment_size = 2

    def create_network(self):
        """Return a new network."""
        return Empty(max_size=self.initial_recruitment_size)
