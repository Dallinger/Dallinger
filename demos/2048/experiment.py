"""The game 2048."""
import dallinger

config = dallinger.config.get_config()


def extra_parameters():
    config.register('n', int)


class TwentyFortyEight(dallinger.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Initialize the experiment."""
        super(TwentyFortyEight, self).__init__(session)
        self.experiment_repeats = 1
        N = config.get("n")
        self.initial_recruitment_size = N
        if session:
            self.setup()

    def recruit(self):
        """Recruitment."""
        if not self.networks(full=False):
            self.recruiter().close_recruitment()
