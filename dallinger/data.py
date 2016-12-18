"""Tools for loading data."""

import tablib
import pandas


table_names = [
    "information",
    "networks",
    "nodes",
    "vectors",
    "notification",
    "participants",
    "questions",
    "transformations",
    "transmissions",
]


def load(URL):
    """Create a Data object from the given URL."""
    if URL.endswith(".zip"):
        return NotImplementedError

    elif URL.startswith("postgresql"):
        return NotImplementedError

    else:
        return NotImplementedError


class Data(object):
    """A data object."""

    def __init__(self):
        super(Data, self).__init__()

# data = dallinger.data()
