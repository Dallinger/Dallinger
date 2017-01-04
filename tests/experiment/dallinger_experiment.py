from dallinger.config import get_config
from dallinger.experiments import Experiment

config = get_config()


class TestExperiment(Experiment):
    pass


def extra_settings():
    config.register('custom_parameter', int, [])
