"""This is Dallinger, a platform for simulating evolution with people."""

from . import (
    bots,
    command_line,
    config,
    models,
    information,
    nodes,
    networks,
    processes,
    transformations,
    experiment,
    experiments,
    heroku,
    registration,
)
from .patches import patch

import logging
from logging import NullHandler

logger = logging.getLogger(__name__)
logger.addHandler(NullHandler())

patch()

__all__ = (
    "bots",
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
    "registration",
    "logger",
)
