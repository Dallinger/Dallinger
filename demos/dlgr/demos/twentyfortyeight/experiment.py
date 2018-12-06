"""The game 2048."""
import dallinger
from dallinger.experiment import Experiment
from dallinger.networks import Empty

config = dallinger.config.get_config()


def extra_parameters():
    config.register('n', int)


class TwentyFortyEight(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Initialize the experiment."""
        super(TwentyFortyEight, self).__init__(session)
        self.experiment_repeats = 1
        self.initial_recruitment_size = config.get("n")
        if session:
            self.setup()

    def create_network(self):
        """Return a new network."""
        return Empty(max_size=self.initial_recruitment_size)

    def recruit(self):
        """Recruitment."""
        if not self.networks(full=False):
            self.recruiter.close_recruitment()
