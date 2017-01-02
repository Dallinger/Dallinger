"""This is Dallinger, a platform for simulating evolution with people."""

from . import (
    models,
    information,
    nodes,
    networks,
    processes,
    transformations,
    experiment,
    experiments,
    heroku
)

import logging
from logging import NullHandler
from localconfig import config
config.read("config.txt")
logger = logging.getLogger(__name__)
logger.addHandler(NullHandler())


__all__ = (
    "config",
    "models",
    "information",
    "nodes",
    "networks",
    "processes",
    "transformations",
    "heroku",
    "experiment",
    "experiments",
)
