"""A home for all Dallinger Experiments. Experiments should be registered
with a ``setuptools`` ``entry_point`` for the ``dallinger.experiments`` group.
"""

import logging
from importlib.metadata import entry_points

from ..experiment import Experiment

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Avoid PEP-8 warning, we want this to be importable from this location
Experiment = Experiment

experiments_entry_points = entry_points(group="dallinger.experiments")

for entry_point in experiments_entry_points:
    try:
        globals()[entry_point.name] = entry_point.load()
    except ImportError:
        logger.exception(
            "Could not import registered entry point {}".format(entry_point.name)
        )
