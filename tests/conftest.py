import os
import pytest


@pytest.fixture(scope='session', autouse=True)
def subprocess_coverage():
    # Set env var to trigger starting coverage for subprocesses
    coverage_path = os.path.dirname(os.path.dirname(__file__))
    os.environ['COVERAGE_PROCESS_START'] = os.path.join(coverage_path, '.coveragerc')
    os.environ['COVERAGE_FILE'] = os.path.join(coverage_path, '.coverage')


# This fixture is used automatically and ensures that
# the current working directory is reset if other test classes changed it.
@pytest.fixture(scope="class")
def cwd():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    os.chdir(root)


@pytest.fixture(scope='class', autouse=True)
def reset_config():
    yield

    # Make sure dallinger_experiment module isn't kept between tests
    import sys
    if 'dallinger_experiment' in sys.modules:
        del sys.modules['dallinger_experiment']

    # Make sure extra settings aren't kept between tests
    from dallinger.config import configurations
    if hasattr(configurations, 'config'):
        del configurations.config


# For tests that actually log into Amazon Mechanical Turk, get the credentials
# from environment variables.
@pytest.fixture
def creds_from_environment():
    creds = {
        'aws_access_key_id': os.getenv('aws_access_key_id'),
        'aws_secret_access_key': os.getenv('aws_secret_access_key')
    }
    return creds


# decorator for test methods or classes which should be skipped if there
# are no aws credentials set in the environment
skip_if_not_mturk_requestor = pytest.mark.skipif(
    not os.getenv('is_aws_mturk_requestor') and
    creds_from_environment().values(),
    reason="Not configured to run Amazon MTurk system tests."
)

skip_if_not_mturk_requestor_and_worker = pytest.mark.skipif(
    not (
        os.getenv('is_aws_mturk_requestor') and
        os.getenv('mturk_worker_id') and
        creds_from_environment().values()
    ),
    reason="Not configured to run Amazon MTurk requestor/worker tests."
)
