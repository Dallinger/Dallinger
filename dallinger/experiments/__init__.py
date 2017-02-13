"""A home for all Dallinger Experiments. Experiments should be registered
with a ``setuptools`` ``entry_point`` for the ``dallinger.experiments`` group.
"""
import logging
from pkg_resources import iter_entry_points
from ..experiment import Experiment

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Avoid PEP-8 warning, we want this to be importable from this location
Experiment = Experiment

for entry_point in iter_entry_points(group='dallinger.experiments'):
    try:
        globals()[entry_point.name] = entry_point.load()
    except ImportError:
        logger.exception('Could not import registered entry point {}'.format(
            entry_point.name
        ))
