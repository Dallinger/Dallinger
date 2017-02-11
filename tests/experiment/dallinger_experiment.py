from dallinger.config import get_config
from dallinger.experiments import Experiment
from dallinger.networks import Star

config = get_config()


class TestExperiment(Experiment):

    def __init__(self, session=None):
        super(TestExperiment, self).__init__(session)
        self.experiment_repeats = 1
        self.setup()

    def create_network(self):
        """Return a new network."""
        return Star(max_size=2)


def extra_parameters():
    config.register('custom_parameter', int, [])
