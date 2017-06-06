"""The game Snake."""

import dallinger

config = dallinger.config.get_config()


def extra_parameters():
    config.register('num_participants', int)


class ConcentrationGame(dallinger.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Initialize the experiment."""
        super(ConcentrationGame, self).__init__(session)
        self.experiment_repeats = 1
        N = config.get("Experiment", "num_participants")
        self.initial_recruitment_size = N
        if session:
            self.setup()