"""The game Concentration."""

import dallinger
from dallinger.experiment import Experiment
from dallinger.networks import Empty

config = dallinger.config.get_config()


def extra_parameters():
    config.register("num_participants", int)


class ConcentrationGame(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Initialize the experiment."""
        super(ConcentrationGame, self).__init__(session)
        self.experiment_repeats = 1
        self.initial_recruitment_size = config["num_participants"]
        if session:
            self.setup()

    def create_network(self):
        """Return a new network."""
        return Empty(max_size=self.initial_recruitment_size)
