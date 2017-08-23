import mock
import os
import pytest
import shutil
import tempfile


@pytest.fixture(scope='session', autouse=True)
def subprocess_coverage():
    # Set env var to trigger starting coverage for subprocesses
    coverage_path = os.path.dirname(os.path.dirname(__file__))
    os.environ['COVERAGE_PROCESS_START'] = os.path.join(coverage_path, '.coveragerc')
    os.environ['COVERAGE_FILE'] = os.path.join(coverage_path, '.coverage')


@pytest.fixture()
def clear_workers():
    import subprocess

    def _zap():
        kills = [
            ['pkill', 'gunicorn'],
            ['pkill', '-f', 'python worker.py'],
        ]
        for kill in kills:
            try:
                subprocess.check_call(kill)
            except Exception as e:
                if e.returncode != 1:
                    raise

    _zap()
    yield
    _zap()


@pytest.fixture(scope='session')
def root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


# This fixture is used automatically and ensures that
# the current working directory is reset if other test classes changed it.
@pytest.fixture(scope="class")
def cwd(root):
    os.chdir(root)


@pytest.fixture(scope="class")
def experiment_dir(root):
    os.chdir('tests/experiment')
    yield
    cwd(root)


@pytest.fixture(scope="class")
def bartlett_dir(root):
    os.chdir('demos/dlgr/demos/bartlett1932')
    yield
    cwd(root)


@pytest.fixture(scope='class', autouse=True)
def reset_config():
    yield

    # Make sure dallinger_experiment module isn't kept between tests
    import sys
    if 'dallinger_experiment' in sys.modules:
        del sys.modules['dallinger_experiment']

    # Make sure extra parameters aren't kept between tests
    from dallinger.config import configurations
    if hasattr(configurations, 'config'):
        del configurations.config


@pytest.fixture
def env():
    # Heroku requires a home directory to start up
    # We create a fake one using tempfile and set it into the
    # environment to handle sandboxes on CI servers

    fake_home = tempfile.mkdtemp()
    environ = os.environ.copy()
    environ.update({'HOME': fake_home})
    yield environ

    shutil.rmtree(fake_home, ignore_errors=True)


@pytest.fixture
def stub_config():
    defaults = {
        'auto_recruit': True,
        'aws_access_key_id': u'fake key',
        'aws_secret_access_key': u'fake secret',
        'base_payment': 0.01,
        'duration': 1.0,
        'mode': u'sandbox',
        'id': u'some experiment uid',
        'keywords': u'kw1, kw2, kw3',
        'server': '0.0.0.0',
        'organization_name': u'fake org name',
        'notification_url': u'https://url-of-notification-route',
        'approve_requirement': 95,
        'us_only': True,
        'lifetime': 1,
        'title': u'fake experiment title',
        'description': u'fake HIT description',
    }
    from dallinger.config import default_keys
    from dallinger.config import Configuration
    config = Configuration()
    for key in default_keys:
        config.register(*key)
    config.extend(defaults.copy())
    config.ready = True

    return config


@pytest.fixture
def tempdir():
    cwd = os.getcwd()
    tmp = tempfile.mkdtemp()
    os.chdir(tmp)
    yield tmp

    os.chdir(cwd)
    shutil.rmtree(tmp, ignore_errors=True)



@pytest.fixture
def subproc():
    with mock.patch('dallinger.heroku.tools.subprocess') as sp:
        yield sp


@pytest.fixture(scope='class')
def aws_creds():
    from dallinger.config import get_config
    config = get_config()
    if not config.ready:
        config.load()
    creds = {
        'aws_access_key_id': config.get('aws_access_key_id'),
        'aws_secret_access_key': config.get('aws_secret_access_key')
    }
    return creds


@pytest.fixture
def db_session():
    import dallinger.db
    # The drop_all call can hang without this; see:
    # https://stackoverflow.com/questions/13882407/sqlalchemy-blocked-on-dropping-tables
    dallinger.db.session.close()
    session = dallinger.db.init_db(drop_all=True)
    yield session
    session.rollback()
    session.close()


def pytest_addoption(parser):
    parser.addoption("--firefox", action="store_true", help="Run firefox bot tests")
    parser.addoption("--chrome", action="store_true", help="Run chrome bot tests")
    parser.addoption("--phantomjs", action="store_true", help="Run phantomjs bot tests")
    parser.addoption("--webdriver", nargs="?", action="store",
                     help="URL of selenium server including /wd/hub to run remote tests against",
                     metavar='URL')
    parser.addoption("--runbot", action="store_true",
                     help="Run an experiment using a bot during tests")
    parser.addoption("--manual", action="store_true",
                     help="Run manual interactive tests during test run")
    parser.addoption("--heroku", action="store_true",
                     help="Run tests requiring heroku login")
