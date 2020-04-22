import mock
import os
import pytest

pytest_plugins = ["pytest_dallinger"]


@pytest.fixture(scope="class", autouse=True)
def reset_config():
    yield

    # Make sure dallinger_experiment module isn't kept between tests
    import sys

    to_delete = []
    for module in sys.modules:
        if module.startswith("dallinger_experiment"):
            to_delete.append(module)
    for module in to_delete:
        del sys.modules[module]

    # Make sure extra parameters aren't kept between tests
    import dallinger.config

    dallinger.config.config = None


@pytest.fixture(scope="session", autouse=True)
def subprocess_coverage():
    # Set env var to trigger starting coverage for subprocesses
    coverage_path = os.path.dirname(os.path.dirname(__file__))
    os.environ["COVERAGE_PROCESS_START"] = os.path.join(coverage_path, ".coveragerc")
    os.environ["COVERAGE_FILE"] = os.path.join(coverage_path, ".coverage")


@pytest.fixture(scope="class")
def experiment_dir(root):
    os.chdir("tests/experiment")
    yield
    os.chdir(root)


@pytest.fixture(scope="class")
def bartlett_dir(root):
    os.chdir("demos/dlgr/demos/bartlett1932")
    yield
    os.chdir(root)


@pytest.fixture(scope="class")
def aws_creds():
    from dallinger.config import get_config

    config = get_config()
    if not config.ready:
        config.load()
    creds = {
        "aws_access_key_id": config.get("aws_access_key_id"),
        "aws_secret_access_key": config.get("aws_secret_access_key"),
    }
    return creds


@pytest.fixture
def custom_app_output():
    with mock.patch("dallinger.heroku.tools.check_output") as check_output:

        def my_check_output(cmd):
            if "auth:whoami" in cmd:
                return b"test@example.com"
            elif "config:get" in cmd:
                if "CREATOR" in cmd and "dlgr-my-uid" in cmd:
                    return b"test@example.com"
                elif "DALLINGER_UID" in cmd:
                    return cmd[-1].replace("dlgr-", "")
                return b""
            elif "apps" in cmd:
                return b"""[
{"name": "dlgr-my-uid",
    "created_at": "2018-01-01T12:00Z",
    "web_url": "https://dlgr-my-uid.herokuapp.com"},
{"name": "dlgr-another-uid",
    "created_at": "2018-01-02T00:00Z",
    "web_url": "https://dlgr-another-uid.herokuapp.com"}
]"""

        check_output.side_effect = my_check_output
        yield check_output


def pytest_addoption(parser):
    parser.addoption(
        "--webdriver",
        nargs="?",
        action="store",
        help="URL of selenium server including /wd/hub to run remote tests against",
        metavar="URL",
    )
    parser.addoption(
        "--runbot",
        action="store_true",
        help="Run an experiment using a bot during tests",
    )
    parser.addoption(
        "--manual",
        action="store_true",
        help="Run manual interactive tests during test run",
    )
    parser.addoption(
        "--mturkfull",
        action="store_true",
        help="Run comprehensive MTurk integration tests during test run",
    )
    parser.addoption(
        "--heroku", action="store_true", help="Run tests requiring heroku login"
    )
    parser.addoption(
        "--griduniverse",
        action="store_true",
        help="Run griduinverse tests and fail if not all pass",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
