"""The game 2048."""

import ConfigParser
import dallinger


class TwentyFortyEight(dallinger.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        config = ConfigParser.ConfigParser()
        config.read("config.txt")

        super(TwentyFortyEight, self).__init__(session)
        self.experiment_repeats = 1
        N = config.get("Experiment", "num_participants")
        self.initial_recruitment_size = N
        self.setup()
