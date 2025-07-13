"""The game Concentration."""

from dallinger.config import get_config
from dallinger.experiment import Experiment
from dallinger.networks import Empty


def extra_parameters():
    config = get_config()
    config.register("num_participants", int)


class ConcentrationGame(Experiment):
    """Define the structure of the experiment."""

    experiment_repeats = 1

    def configure(self):
        config = get_config(self, load=True)
        self.initial_recruitment_size = config.get("num_participants")

    def create_network(self):
        """Return a new network."""
        return Empty(max_size=self.initial_recruitment_size)
