"""The game 2048."""

from dallinger.config import get_config
from dallinger.experiment import Experiment
from dallinger.networks import Empty


def extra_parameters():
    config = get_config()
    config.register("n", int)


class TwentyFortyEight(Experiment):
    """Define the structure of the experiment."""

    experiment_repeats = 1

    def configure(self):
        config = get_config(load=True)
        self.initial_recruitment_size = config.get("n")

    def create_network(self):
        """Return a new network."""
        return Empty(max_size=self.initial_recruitment_size)

    def recruit(self):
        """Recruitment."""
        if not self.networks(full=False):
            self.recruiter.close_recruitment()
