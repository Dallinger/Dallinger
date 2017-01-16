import os

import pytest


# This fixture is used automatically and ensures that
# the current working directory is reset if other test classes changed it.
@pytest.fixture(scope="class")
def cwd():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    os.chdir(root)


# For tests that actually log into Amazon Mechanical Turk, get the credentials
# from environment variables.
def creds_from_environment():
    creds = {
        'aws_access_key_id': os.getenv('aws_access_key_id'),
        'aws_secret_access_key': os.getenv('aws_secret_access_key')
    }
    return creds

# decorator for test methods or classes which should be skipped if there
# are no aws credentials set in the environment
skip_if_no_mturk_requestor = pytest.mark.skipif(
    not os.getenv('is_aws_mturk_requestor') and
    creds_from_environment().values(),
    reason="Not configured to run Amazon MTurk system tests."
)
