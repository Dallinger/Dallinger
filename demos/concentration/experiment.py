"""The game Snake."""

import ConfigParser
import dallinger as dlgr


class ConcentrationGame(dlgr.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        config = ConfigParser.ConfigParser()
        config.read("config.txt")

        super(ConcentrationGame, self).__init__(session)
        self.experiment_repeats = 1
        N = config.get("Experiment Configuration", "num_participants")
        self.initial_recruitment_size = N
        self.setup()
