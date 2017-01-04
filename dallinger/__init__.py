"""This is Dallinger, a platform for simulating evolution with people."""

from . import (
    command_line,
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
from localconfig import LocalConfig
# Read directory local config last
config = LocalConfig("config.txt", interpolation=True)
# Read global config first
config.read('~/.dallingerconfig')
logger = logging.getLogger(__name__)
logger.addHandler(NullHandler())


__all__ = (
    "command_line",
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
