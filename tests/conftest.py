import os
import pytest
import shutil
import tempfile
from dallinger import models
from dallinger import networks


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


@pytest.fixture(scope='session')
def env():
    # Heroku requires a home directory to start up
    # We create a fake one using tempfile and set it into the
    # environment to handle sandboxes on CI servers
    environ_orig = os.environ.copy()
    if not environ_orig.get("CI", False):
        yield environ_orig
    else:
        fake_home = tempfile.mkdtemp()
        environ_patched = environ_orig.copy()
        environ_patched.update({'HOME': fake_home})
        os.environ = environ_patched
        yield environ_patched
        os.environ = environ_orig
        shutil.rmtree(fake_home, ignore_errors=True)


@pytest.fixture()
def webapp():
    from dallinger.experiment_server import sockets
    from dallinger.config import get_config
    config = get_config()
    if not config.ready:
        config.load()
    app = sockets.app
    app.config['DEBUG'] = True
    app.config['TESTING'] = True
    client = app.test_client()
    yield client


@pytest.fixture
def a(db_session):
    """ Provides a standard way of building model objects in tests.

        def test_using_all_defaults(self, a):
            assert a.info()

        def test_with_participant_node(self, a):
            participant = a.participant(worker_id=42)
            info = a.info(origin=a.node(participant=participant))
    """
    class ModelFactory(object):

        def __init__(self, db):
            self.db = db

        def info(self, **kw):
            defaults = {
                'origin': self.star_network,
                'contents': None,
            }

            defaults.update(kw)
            return self._build(models.Info, defaults)

        def participant(self, **kw):
            defaults = {
                'worker_id': '1',
                'assignment_id': '1',
                'hit_id': '1',
                'mode': 'test'
            }
            defaults.update(kw)
            return self._build(models.Participant, defaults)

        def network(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(models.Network, defaults)

        def star_network(self, **kw):
            defaults = {
                'max_size': 2,
            }
            defaults.update(kw)
            return self._build(networks.Star, defaults)

        def node(self, **kw):
            defaults = {
                'network': self.star_network
            }
            defaults.update(kw)
            return self._build(models.Node, defaults)

        def _build(self, klass, attrs):
            # Some of our default values are factories:
            for k, v in attrs.items():
                if callable(v):
                    attrs[k] = v()

            obj = klass(**attrs)
            self._insert(obj)
            return obj

        def _insert(self, thing):
            db_session.add(thing)
            db_session.flush()  # This gets us an ID and sets relationships

    return ModelFactory(db_session)


@pytest.fixture
def stub_config():
    """Builds a standardized Configuration object and returns it, but does
    not load it as the active configuration returned by
    dallinger.config.get_config()
    """
    defaults = {
        u'ad_group': u'Test ad group',
        u'approve_requirement': 95,
        u'auto_recruit': True,
        u'aws_access_key_id': u'fake aws key',
        u'aws_secret_access_key': u'fake aws secret',
        u'aws_region': u'us-east-1',
        u'base_payment': 0.01,
        u'base_port': 5000,
        u'browser_exclude_rule': u'MSIE, mobile, tablet',
        u'clock_on': True,
        u'contact_email_on_error': u'test@mailinator.com',
        u'dallinger_email_address': u'test@example.com',
        u'dallinger_email_password': u'fake password',
        u'database_size': u'standard-0',
        u'database_url': u'postgresql://postgres@localhost/dallinger',
        u'description': u'fake HIT description',
        u'duration': 1.0,
        u'dyno_type': u'free',
        u'heroku_team': u'',
        u'host': u'0.0.0.0',
        u'id': u'some experiment uid',
        u'keywords': u'kw1, kw2, kw3',
        u'lifetime': 1,
        u'logfile': u'-',
        u'loglevel': 0,
        u'mode': u'debug',
        u'notification_url': u'https://url-of-notification-route',
        u'num_dynos_web': 1,
        u'num_dynos_worker': 1,
        u'organization_name': u'Monsters University',
        u'sentry': True,
        u'threads': u'1',
        u'title': u'fake experiment title',
        u'us_only': True,
        u'webdriver_type': u'phantomjs',
        u'whimsical': True
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
def active_config(stub_config):
    """Loads the standard config as the active configuration returned by
    dallinger.config.get_config() and returns it.
    """
    from copy import deepcopy
    from dallinger.config import get_config
    config = get_config()
    config.data = deepcopy(stub_config.data)
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
def in_tempdir(tempdir):
    cwd = os.getcwd()
    os.chdir(tempdir)
    yield tempdir

    os.chdir(cwd)


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
    parser.addoption("--mturkfull", action="store_true",
                     help="Run comprehensive MTurk integration tests during test run")
    parser.addoption("--heroku", action="store_true",
                     help="Run tests requiring heroku login")
