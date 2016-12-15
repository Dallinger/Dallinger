"""This is Dallinger, a platform for simulating evolution with people."""

from . import (
    models,
    information,
    nodes,
    networks,
    processes,
    transformations,
    experiments,
    heroku
)

import logging
from logging import NullHandler
from pkg_resources import iter_entry_points
from types import ModuleType
import sys
from localconfig import config
config.read("config.txt")
logger = logging.getLogger(__name__)
logger.addHandler(NullHandler())

experiment = ModuleType(
    'experiment',
    'A module where Dallinger experiments are registered'
)
for entry_point in iter_entry_points(group='dallinger.experiment'):
    try:
        setattr(experiment, entry_point.name, entry_point.load())
    except ImportError:
        logger.warn('Could not import registered entry point {}'.format(
            entry_point.name
        ))

sys.modules['dallinger.experiment'] = experiment


__all__ = (
    "config",
    "models",
    "information",
    "nodes",
    "networks",
    "processes",
    "transformations",
    "experiments",
    "heroku",
    "experiment",
)
