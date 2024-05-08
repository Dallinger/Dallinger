import os
import re
import shutil
import sys
import tempfile
import time
from unittest import mock

import pexpect
import pytest
from jinja2 import FileSystemLoader
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from dallinger import information, models, networks, nodes
from dallinger.bots import BotBase
from dallinger.recruiters import CLOSE_RECRUITMENT_LOG_PREFIX, NEW_RECRUIT_LOG_PREFIX


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
    original_home = os.path.expanduser("~")
    with mock.patch("os.environ", os.environ.copy()) as environ_patched:
        running_on_ci = environ_patched.get("CI", False)
        have_home_dir = environ_patched.get("HOME", False)
        environ_patched.update({"FLASK_SECRET_KEY": "A TERRIBLE SECRET"})
        if not running_on_ci and have_home_dir:
            yield environ_patched
        else:
            fake_home = tempfile.mkdtemp()
            environ_patched.update({"HOME": fake_home})
            try:
                shutil.copyfile(
                    os.path.join(original_home, ".dallingerconfig"),
                    os.path.join(fake_home, ".dallingerconfig"),
                )
            except FileNotFoundError:
                pass
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
        "activate_recruiter_on_start": True,
        "ad_group": "Test ad group",
        "approve_requirement": 95,
        "assign_qualifications": True,
        "auto_recruit": True,
        "aws_access_key_id": "fake aws key",
        "aws_secret_access_key": "fake aws secret",
        "aws_region": "us-east-1",
        "base_payment": 0.01,
        "base_port": 5000,
        "browser_exclude_rule": "MSIE, mobile, tablet",
        "clock_on": False,
        "contact_email_on_error": "error_contact@test.com",
        "dallinger_email_address": "test@example.com",
        "database_size": "standard-0",
        "disable_when_duration_exceeded": True,
        "enable_global_experiment_registry": False,
        "redis_size": "premium-0",
        "dashboard_user": "admin",
        "database_url": "postgresql://postgres@localhost/dallinger",
        "description": "fake HIT description",
        "duration": 1.0,
        "dyno_type": "free",
        "heroku_app_id_root": "fake-customid",
        "heroku_auth_token": "heroku secret",
        "heroku_python_version": "3.9.2",
        "heroku_team": "",
        "host": "0.0.0.0",
        "id": "TEST_EXPERIMENT_UID",  # This is a significant value; change with caution.
        "keywords": "kw1, kw2, kw3",
        "lifetime": 1,
        "lock_table_when_creating_participant": True,
        "logfile": "-",
        "loglevel": 0,
        "mode": "debug",
        "num_dynos_web": 1,
        "num_dynos_worker": 1,
        "organization_name": "Monsters University",
        "sentry": True,
        "smtp_host": "smtp.fakehost.com:587",
        "smtp_username": "fake email username",
        "smtp_password": "fake email password",
        "threads": "1",
        "title": "fake experiment title",
        "us_only": True,
        "webdriver_type": "chrome_headless",
        "whimsical": True,
        "replay": False,
        "worker_multiplier": 1.5,
    }
    from dallinger.config import Configuration, default_keys

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
def dashboard_config(active_config):
    active_config.extend(
        {"dashboard_user": "admin", "dashboard_password": "DUMBPASSWORD"}
    )
    return active_config


@pytest.fixture
def csrf_token(dashboard_config, webapp):
    # Initialize app to get user info in config
    webapp.get("/")
    # Make a writeable session and copy the csrf token into it
    from flask_wtf.csrf import generate_csrf

    with webapp.application.test_request_context() as request:
        with webapp.session_transaction() as sess:
            token = generate_csrf()
            sess.update(request.session)
    yield token


@pytest.fixture
def webapp_admin(csrf_token, webapp):
    admin_user = webapp.application.config["ADMIN_USER"]
    webapp.post(
        "/dashboard/login",
        data={
            "username": admin_user.id,
            "password": admin_user.password,
            "next": "/dashboard/something",
            "submit": "Sign In",
            "csrf_token": csrf_token,
        },
    )

    yield webapp


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
    """Provides a standard way of building model objects in tests.

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

        def question(self, **kw):
            defaults = {
                "participant": self.participant,
                "question": "A question...",
                "response": "A question response...",
                "number": 1,
            }
            defaults.update(kw)
            return self._build(models.Question, defaults)

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
    from dallinger.experiment_server.experiment_server import app

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
    timeout = request.config.getvalue("recruiter_timeout", 120)

    # Make sure debug server runs to completion with bots
    p = pexpect.spawn(
        "dallinger", ["debug", "--no-browsers", "--verbose"], env=env, encoding="utf-8"
    )
    p.logfile = sys.stdout

    try:
        p.expect_exact("Server is running", timeout=timeout)
        yield p
        if request.node.rep_setup.passed and request.node.rep_call.passed:
            p.expect_exact("Experiment completed", timeout=timeout)
            p.expect_exact("Local Heroku process terminated", timeout=timeout)
    finally:
        try:
            flush_output(p, timeout=0.1)
            p.sendcontrol("c")
            flush_output(p, timeout=3)
            # Why do we need to call flush_output twice? Good question.
            # Something about calling p.sendcontrol("c") seems to disrupt the log.
            # Better to call it both before and after.
        except IOError:
            pass


def flush_output(p, timeout):
    old_timeout = p.timeout
    p.timeout = timeout
    try:
        # Calling read() causes the process's output to be written to stdout,
        # which is then propagated to pytest.
        # This still happens even when a TIMEOUT occurs.
        p.read(
            1000000
        )  # The big number sets the maximum amount of output characters to read.
    except pexpect.TIMEOUT:
        pass
    p.timeout = old_timeout


@pytest.fixture
def recruitment_loop(request, debug_experiment):
    def recruitment_looper():
        timeout = request.config.getvalue("recruiter_timeout", 30)
        urls = set()
        while True:
            index = debug_experiment.expect(
                [
                    "{}: (.*&mode=debug)".format(NEW_RECRUIT_LOG_PREFIX),
                    "{}".format(CLOSE_RECRUITMENT_LOG_PREFIX),
                ],
                timeout=timeout,
            )
            if index == 1:
                return
            elif index == 0:
                url = debug_experiment.match.group(1)
                assert is_valid_recruitment_url(url)
                # Don't repeat the same recruitment url if it appears
                # multiple times
                if url in urls:
                    continue
                urls.add(url)
                yield url
                time.sleep(5)

    yield recruitment_looper()


def is_valid_recruitment_url(url):
    pattern = "^http://localhost:[0-9]+/ad\\?recruiter=[a-zA-Z0-9]+&assignmentId=[a-zA-Z0-9]+&hitId=[a-zA-Z0-9]+&workerId=[a-zA-Z0-9]+&mode=debug$"
    return bool(re.match(pattern, url))


def test_valid_recruitment_urls():
    assert is_valid_recruitment_url(
        "http://localhost:5000/ad?recruiter=hotair&assignmentId=TL6UWU&hitId=Y1A9I0&workerId=8VPUMO&mode=debug"
    )
    assert not is_valid_recruitment_url(
        "http://localhost:5000/ad?recruiter=hotair&assignmentId=TL6UWU&hitId=Y1A9I0&workerId=8VPUMO&mode=debug extra text"
    )


DRIVER_MAP = {
    "firefox": webdriver.Firefox,
    "chrome": webdriver.Chrome,
    "chrome_headless": webdriver.Chrome,
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
            driver_class = DRIVER_MAP.get(request.param, webdriver.Chrome)
            if request.param == "chrome_headless":
                from selenium.webdriver.chrome.options import Options

                chrome_options = Options()
                chrome_options.add_argument("--headless")
                kwargs = {"options": chrome_options}
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
    driver_type = request.param or "chrome_headless"
    active_config.set("webdriver_type", driver_type)

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


@pytest.fixture
def tasks_with_cleanup():
    from dallinger import experiment

    tasks = experiment.EXPERIMENT_TASK_REGISTRATIONS
    orig_tasks = tasks.copy()
    tasks.clear()
    yield tasks
    tasks[:] = orig_tasks


def pytest_addoption(parser):
    parser.addoption("--chrome", action="store_true", help="Run chrome tests")
    parser.addoption(
        "--chrome-headless",
        action="store_true",
        help="Run chrome tests with headless driver",
    )
    parser.addoption("--firefox", action="store_true", help="Run firefox tests")
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


@pytest.fixture
def redis_conn():
    from dallinger.db import redis_conn as _redis

    yield _redis

    for key in _redis.keys():
        _redis.delete(key)
