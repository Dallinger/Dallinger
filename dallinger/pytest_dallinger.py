import mock
import os
import pexpect
import pytest
import shutil
import sys
import tempfile
import time
from jinja2 import FileSystemLoader
from selenium import webdriver
from dallinger import information
from dallinger import models
from dallinger import networks
from dallinger import nodes
from dallinger.bots import BotBase
from dallinger.recruiters import NEW_RECRUIT_LOG_PREFIX
from dallinger.recruiters import CLOSE_RECRUITMENT_LOG_PREFIX
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()

    # set a report attribute for each phase of a call, which can
    # be "setup", "call", "teardown"

    setattr(item, "rep_" + rep.when, rep)


@pytest.fixture(scope="session")
def root(request):
    try:
        path = request.fspath.strpath
        return os.path.abspath(os.path.join(path, ".."))
    except AttributeError:
        return request.node.fspath.strpath


# This fixture is used automatically and ensures that
# the current working directory is reset if other test classes changed it.
@pytest.fixture(scope="class")
def cwd(root):
    os.chdir(root)


def is_dallinger_module(key):
    return key.startswith("dallinger_experiment") or key.startswith(
        "TEST_EXPERIMENT_UID"
    )


@pytest.fixture(autouse=True)
def reset_sys_modules():
    to_clear = [k for k in sys.modules if is_dallinger_module(k)]
    for key in to_clear:
        del sys.modules[key]


@pytest.fixture
def clear_workers():
    import subprocess

    def _zap():
        kills = [["pkill", "-f", "heroku"]]
        for kill in kills:
            try:
                subprocess.check_call(kill)
            except Exception as e:
                if e.returncode != 1:
                    raise

    _zap()
    yield
    _zap()


@pytest.fixture(scope="session")
def env():
    # Heroku requires a home directory to start up
    # We create a fake one using tempfile and set it into the
    # environment to handle sandboxes on CI servers
    with mock.patch("os.environ", os.environ.copy()) as environ_patched:
        running_on_ci = environ_patched.get("CI", False)
        have_home_dir = environ_patched.get("HOME", False)
        environ_patched.update({"FLASK_SECRET_KEY": "A TERRIBLE SECRET"})
        if not running_on_ci and have_home_dir:
            yield environ_patched
        else:
            fake_home = tempfile.mkdtemp()
            environ_patched.update({"HOME": fake_home})
            yield environ_patched
            shutil.rmtree(fake_home, ignore_errors=True)


@pytest.fixture
def tempdir():
    tmp = tempfile.mkdtemp()
    yield tmp

    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def in_tempdir(tempdir):
    cwd = os.getcwd()
    os.chdir(tempdir)
    yield tempdir

    os.chdir(cwd)


@pytest.fixture
def stub_config():
    """Builds a standardized Configuration object and returns it, but does
    not load it as the active configuration returned by
    dallinger.config.get_config()
    """
    defaults = {
        u"ad_group": u"Test ad group",
        u"approve_requirement": 95,
        u"assign_qualifications": True,
        u"auto_recruit": True,
        u"aws_access_key_id": u"fake aws key",
        u"aws_secret_access_key": u"fake aws secret",
        u"aws_region": u"us-east-1",
        u"base_payment": 0.01,
        u"base_port": 5000,
        u"browser_exclude_rule": u"MSIE, mobile, tablet",
        u"clock_on": False,
        u"contact_email_on_error": u"error_contact@test.com",
        u"dallinger_email_address": u"test@example.com",
        u"database_size": u"standard-0",
        u"redis_size": u"premium-0",
        u"database_url": u"postgresql://postgres@localhost/dallinger",
        u"description": u"fake HIT description",
        u"duration": 1.0,
        u"dyno_type": u"free",
        u"heroku_auth_token": u"heroku secret",
        u"heroku_python_version": u"3.6.10",
        u"heroku_team": u"",
        u"host": u"0.0.0.0",
        u"id": u"TEST_EXPERIMENT_UID",  # This is a significant value; change with caution.
        u"keywords": u"kw1, kw2, kw3",
        u"lifetime": 1,
        u"logfile": u"-",
        u"loglevel": 0,
        u"mode": u"debug",
        u"num_dynos_web": 1,
        u"num_dynos_worker": 1,
        u"organization_name": u"Monsters University",
        u"sentry": True,
        u"smtp_host": u"smtp.fakehost.com:587",
        u"smtp_username": u"fake email username",
        u"smtp_password": u"fake email password",
        u"threads": u"1",
        u"title": u"fake experiment title",
        u"us_only": True,
        u"webdriver_type": u"phantomjs",
        u"whimsical": True,
        u"replay": False,
        u"worker_multiplier": 1.5,
    }
    from dallinger.config import default_keys
    from dallinger.config import Configuration

    config = Configuration()
    for key in default_keys:
        config.register(*key)
    config.extend(defaults.copy())
    # Patch load() so we don't update any key/value pairs from actual files:
    config.load = mock.Mock(side_effect=lambda: setattr(config, "ready", True))
    config.ready = True

    return config


@pytest.fixture
def active_config(stub_config):
    """Loads the standard config as the active configuration returned by
    dallinger.config.get_config() and returns it.
    """
    from dallinger import config as c

    orig_config = c.config
    c.config = stub_config
    yield c.config
    c.config = orig_config


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

        def agent(self, **kw):
            defaults = {"network": self.network}
            defaults.update(kw)
            return self._build(nodes.Agent, defaults)

        def info(self, **kw):
            defaults = {"origin": self.star, "contents": None}

            defaults.update(kw)
            return self._build(models.Info, defaults)

        def gene(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(information.Gene, defaults)

        def meme(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(information.Meme, defaults)

        def participant(self, **kw):
            defaults = {
                "recruiter_id": "hotair",
                "worker_id": "1",
                "assignment_id": "1",
                "hit_id": "1",
                "mode": "test",
            }
            defaults.update(kw)
            return self._build(models.Participant, defaults)

        def network(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(models.Network, defaults)

        def burst(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(networks.Burst, defaults)

        def chain(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(networks.Chain, defaults)

        def delayed_chain(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(networks.DelayedChain, defaults)

        def empty(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(networks.Empty, defaults)

        def fully_connected(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(networks.FullyConnected, defaults)

        def replicator(self, **kw):
            defaults = {"network": self.network}
            defaults.update(kw)
            return self._build(nodes.ReplicatorAgent, defaults)

        def scale_free(self, **kw):
            defaults = {"m0": 1, "m": 1}
            defaults.update(kw)
            return self._build(networks.ScaleFree, defaults)

        def sequential_microsociety(self, **kw):
            defaults = {"n": 1}
            defaults.update(kw)
            return self._build(networks.SequentialMicrosociety, defaults)

        def split_sample(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(networks.SplitSampleNetwork, defaults)

        def star(self, **kw):
            defaults = {"max_size": 2}
            defaults.update(kw)
            return self._build(networks.Star, defaults)

        def node(self, **kw):
            defaults = {"network": self.star}
            defaults.update(kw)
            return self._build(models.Node, defaults)

        def source(self, **kw):
            defaults = {"network": self.star}
            defaults.update(kw)
            # nodes.Source is intended to be abstract
            return self._build(nodes.RandomBinaryStringSource, defaults)

        def transformation(self, **kw):
            defaults = {}
            defaults.update(kw)
            return self._build(models.Transformation, defaults)

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


def uncached_jinja_loader(app):
    """We want a non-cached template loader so we can load templates from
    directories which may vary between tests, so override
    the @locked_cached_property from flask.helpers
    """
    if app.template_folder is not None:
        return FileSystemLoader(os.path.join(app.root_path, app.template_folder))


@pytest.fixture
def webapp(active_config, reset_sys_modules, env):
    """Return a Flask test client.

    The imported app assumes an active Configuration, and will load both the
    test experiment package and templates from the current directory,
    so we need to make sure we wipe the slate clean between tests. This means
    not caching the Flask template search path, and clearing out sys.modules
    before loading the Flask app.
    """
    from dallinger.experiment_server import sockets

    app = sockets.app
    # look in the cwd for test's templates, and make sure the template loader
    # uses that directory to search for them.
    app.root_path = os.getcwd()
    app.jinja_loader = uncached_jinja_loader(app)

    app.config.update({"DEBUG": True, "TESTING": True})
    client = app.test_client()
    yield client
    app._got_first_request = False


@pytest.fixture
def test_request(webapp):
    return webapp.application.test_request_context


@pytest.fixture
def debug_experiment(request, env, clear_workers):
    timeout = pytest.config.getvalue("recruiter_timeout", 30)
    # Make sure debug server runs to completion with bots
    p = pexpect.spawn(
        "dallinger", ["debug", "--no-browsers"], env=env, encoding="utf-8"
    )
    p.logfile = sys.stdout

    try:
        p.expect_exact(u"Server is running", timeout=timeout)
        yield p
        if request.node.rep_setup.passed and request.node.rep_call.passed:
            p.expect_exact(u"Experiment completed", timeout=timeout)
            p.expect_exact(u"Local Heroku process terminated", timeout=timeout)
    finally:
        try:
            p.sendcontrol("c")
            p.read()
        except IOError:
            pass


@pytest.fixture
def recruitment_loop(debug_experiment):
    def recruitment_looper():
        timeout = pytest.config.getvalue("recruiter_timeout", 30)
        urls = set()
        while True:
            index = debug_experiment.expect(
                [
                    u"{}: (.*)$".format(NEW_RECRUIT_LOG_PREFIX),
                    u"{}".format(CLOSE_RECRUITMENT_LOG_PREFIX),
                ],
                timeout=timeout,
            )
            if index == 1:
                return
            elif index == 0:
                url = debug_experiment.match.group(1)
                # Don't repeat the same recruitment url if it appears
                # multiple times
                if url in urls:
                    continue
                urls.add(url)
                yield url
                time.sleep(5)

    yield recruitment_looper()


DRIVER_MAP = {
    u"phantomjs": webdriver.PhantomJS,
    u"firefox": webdriver.Firefox,
    u"chrome": webdriver.Chrome,
}


def pytest_generate_tests(metafunc):
    """Runs selenium based tests using all enabled driver types"""
    driver_types = []
    for d in DRIVER_MAP:
        if metafunc.config.getvalue(d, None):
            driver_types.append(d)
    if "selenium_recruits" in metafunc.fixturenames:
        metafunc.parametrize("selenium_recruits", driver_types, indirect=True)
    if "bot_recruits" in metafunc.fixturenames:
        metafunc.parametrize("bot_recruits", driver_types, indirect=True)


@pytest.fixture
def selenium_recruits(request, recruitment_loop):
    def recruits():
        for url in recruitment_loop:
            kwargs = {}
            driver_class = DRIVER_MAP.get(request.param, webdriver.PhantomJS)
            if driver_class is webdriver.PhantomJS:
                # PhantomJS needs a new local storage for every run
                tmpdirname = tempfile.mkdtemp()
                kwargs = {
                    "service_args": ["--local-storage-path={}".format(tmpdirname)],
                }
            driver = driver_class(**kwargs)
            driver.get(url)
            try:
                yield driver
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass

    yield recruits()


@pytest.fixture
def bot_recruits(request, active_config, recruitment_loop):
    driver_type = request.param or u"phantomjs"
    active_config.set(u"webdriver_type", driver_type)

    def recruit_bots():
        bot_class = getattr(request.module, "PYTEST_BOT_CLASS", BotBase)
        for url in recruitment_loop:
            bot = bot_class(url)
            try:
                bot.sign_up()
                yield bot
                if bot.sign_off():
                    bot.complete_experiment("worker_complete")
                else:
                    bot.complete_experiment("worker_failed")
            finally:
                try:
                    bot.driver.quit()
                except Exception:
                    pass

    yield recruit_bots()


def pytest_addoption(parser):
    parser.addoption("--chrome", action="store_true", help="Run chrome tests")
    parser.addoption("--firefox", action="store_true", help="Run firefox tests")
    parser.addoption("--phantomjs", action="store_true", help="Run phantomjs tests")
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--recruiter-timeout",
        type=int,
        dest="recruiter_timeout",
        default=30,
        help="Maximum time fot webdriver experiment sessions in seconds",
    )


def wait_for_element(driver, el_id, timeout=10):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.ID, el_id))
    )


def wait_until_clickable(driver, el_id, timeout=10):
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.ID, el_id))
    )


def wait_for_text(driver, el_id, value, removed=False, timeout=10):
    el = wait_for_element(driver, el_id, timeout)
    if value in el.text and not removed:
        return el
    if removed and value not in el.text:
        return el

    wait = WebDriverWait(driver, timeout)
    condition = EC.text_to_be_present_in_element((By.ID, el_id), value)
    if removed:
        wait.until_not(condition)
        if value not in el.text:
            return el
    else:
        wait.until(condition)
        if value in el.text:
            return el

    raise AttributeError
