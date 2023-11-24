"""This is Dallinger, a platform for simulating evolution with people."""

import logging
from logging import NullHandler

from . import (
    bots,
    command_line,
    config,
    experiment,
    experiments,
    heroku,
    information,
    models,
    networks,
    nodes,
    processes,
    registration,
    transformations,
)
from .patches import patch

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
