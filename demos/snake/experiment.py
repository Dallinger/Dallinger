"""The game Snake."""
import dallinger as dlgr

config = dlgr.config.get_config()


def extra_parameters():
    config.register('n', int)


class SnakeGame(dlgr.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Initialize the experiment."""
        super(SnakeGame, self).__init__(session)
        self.experiment_repeats = 1
        self.initial_recruitment_size = config.get("n")
        if session:
            self.setup()
