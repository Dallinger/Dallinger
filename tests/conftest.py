import os

import pytest


# This fixture is used automatically and ensures that
# the current working directory is reset if other test classes changed it.
@pytest.fixture(scope="class")
def cwd():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    os.chdir(root)
