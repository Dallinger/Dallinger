# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os
import pkg_resources
import re
import redis
import requests
import shutil
import six
import sys
import tempfile
import threading
import time
import webbrowser
from six.moves import shlex_quote as quote
from unicodedata import normalize

from dallinger import data
from dallinger import db
from dallinger import heroku
from dallinger import recruiters
from dallinger import registration
from dallinger.compat import is_command
from dallinger.config import get_config
from dallinger.heroku.tools import HerokuApp
from dallinger.heroku.tools import HerokuLocalWrapper
from dallinger.utils import dallinger_package_path
from dallinger.utils import ensure_directory
from dallinger.utils import get_base_url
from dallinger.utils import GitClient

config = get_config()


def _make_chrome(path):
    new_chrome = webbrowser.Chrome()
    new_chrome.name = path
    profile_directory = tempfile.mkdtemp()
    with open(os.path.join(profile_directory, "First Run"), "wb") as firstrun:
        # This file existing prevents prompts to make the new profile directory
        # the default
        firstrun.flush()
    new_chrome.remote_args = webbrowser.Chrome.remote_args + [
        '--user-data-dir="{}"'.format(profile_directory),
        "--no-first-run",
    ]
    return new_chrome


def new_webbrowser_profile():
    if is_command("google-chrome"):
        return _make_chrome("google-chrome")
    elif is_command("firefox"):
        new_firefox = webbrowser.Mozilla()
        new_firefox.name = "firefox"
        profile_directory = tempfile.mkdtemp()
        new_firefox.remote_args = [
            "-profile",
            profile_directory,
            "-new-instance",
            "-no-remote",
            "-url",
            "%s",
        ]
        return new_firefox
    elif sys.platform == "darwin":
        chrome_path = config.get("chrome-path")
        if os.path.exists(chrome_path):
            return _make_chrome(chrome_path)
        else:
            return webbrowser
    else:
        return webbrowser


def exclusion_policy():
    """Returns a callable which, when passed a directory path and a list
    of files in that directory, will return a subset of the files which should
    be excluded from a copy or some other action.

    See https://docs.python.org/3/library/shutil.html#shutil.ignore_patterns
    """
    patterns = set(
        [
            ".git",
            "config.txt",
            "*.db",
            "*.dmg",
            "node_modules",
            "snapshots",
            "data",
            "server.log",
            "__pycache__",
        ]
    )

    return shutil.ignore_patterns(*patterns)


class ExperimentFileSource(object):
    """Treat an experiment directory as a potential source of files for
    copying to a temp directory as part of a deployment (debug or otherwise).
    """

    def __init__(self, root_dir="."):
        self.root = root_dir
        self.git = GitClient()

    @property
    def files(self):
        """A Set of all files copyable in the source directory, accounting for
        exclusions.
        """
        return {path for path in self._walk()}

    @property
    def size(self):
        """Combined size of all files, accounting for exclusions.
        """
        return sum([os.path.getsize(path) for path in self._walk()])

    def selective_copy_to(self, destination):
        """Write files from the source directory to another directory, skipping
        files excluded by the general exclusion_policy, plus any files
        ignored by git configuration.
        """
        for path in self.files:
            subpath = os.path.relpath(path, start=self.root)
            target_folder = os.path.join(destination, os.path.dirname(subpath))
            ensure_directory(target_folder)
            shutil.copy2(path, target_folder)

    def _walk(self):
        # The GitClient and os.walk may return different representations of the
        # same unicode characters, so we use unicodedata.normalize() for
        # comparisons:
        # list(name_from_git)
        # ['å', ' ', 'f', 'i', 'l', 'e', '.', 't', 'x', 't']
        # list(from_os_walk)
        # ['a', '̊', ' ', 'f', 'i', 'l', 'e', '.', 't', 'x', 't']
        exclusions = exclusion_policy()
        git_files = {
            os.path.join(self.root, normalize("NFC", f)) for f in self.git.files()
        }
        for dirpath, dirnames, filenames in os.walk(self.root, topdown=True):
            current_exclusions = exclusions(dirpath, os.listdir(dirpath))
            # Modifying dirnames in-place will prune the subsequent files and
            # directories visited by os.walk. This is only possible when
            # topdown = True
            dirnames[:] = [d for d in dirnames if d not in current_exclusions]
            legit_files = {
                os.path.join(dirpath, f)
                for f in filenames
                if f not in current_exclusions
            }
            if git_files:
                normalized = {
                    normalize("NFC", six.text_type(f)): f for f in legit_files
                }
                legit_files = {v for k, v in normalized.items() if k in git_files}
            for legit in legit_files:
                yield legit


def assemble_experiment_temp_dir(config):
    """Create a temp directory from which to run an experiment.
    The new directory will include:
    - Copies of custom experiment files which don't match the exclusion policy
    - Templates and static resources from Dallinger
    - An export of the loaded configuration
    - Heroku-specific files (Procile, runtime.txt) from Dallinger

    Assumes the experiment root directory is the current working directory.

    Returns the absolute path of the new directory.
    """
    app_id = config.get("id")
    dst = os.path.join(tempfile.mkdtemp(), app_id)

    # Copy local experiment files, minus some
    ExperimentFileSource(os.getcwd()).selective_copy_to(dst)

    # Export the loaded configuration
    config.write(filter_sensitive=True, directory=dst)

    # Save the experiment id
    with open(os.path.join(dst, "experiment_id.txt"), "w") as file:
        file.write(app_id)

    # Copy Dallinger files
    dallinger_root = dallinger_package_path()
    ensure_directory(os.path.join(dst, "static", "scripts"))
    ensure_directory(os.path.join(dst, "static", "css"))
    frontend_files = [
        os.path.join("static", "css", "dallinger.css"),
        os.path.join("static", "scripts", "dallinger2.js"),
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("static", "scripts", "require.js"),
        os.path.join("static", "scripts", "reconnecting-websocket.js"),
        os.path.join("static", "scripts", "spin.min.js"),
        os.path.join("static", "scripts", "tracker.js"),
        os.path.join("static", "scripts", "store+json2.min.js"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "error-complete.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("templates", "complete.html"),
        os.path.join("templates", "questionnaire.html"),
        os.path.join("templates", "thanks.html"),
        os.path.join("templates", "waiting.html"),
        os.path.join("static", "robots.txt"),
    ]
    frontend_dirs = [os.path.join("templates", "base")]
    for filename in frontend_files:
        src = os.path.join(dallinger_root, "frontend", filename)
        dst_filepath = os.path.join(dst, filename)
        if not os.path.exists(dst_filepath):
            shutil.copy(src, dst_filepath)
    for filename in frontend_dirs:
        src = os.path.join(dallinger_root, "frontend", filename)
        dst_filepath = os.path.join(dst, filename)
        if not os.path.exists(dst_filepath):
            shutil.copytree(src, dst_filepath)

    # Copy Heroku files
    heroku_files = ["Procfile"]
    for filename in heroku_files:
        src = os.path.join(dallinger_root, "heroku", filename)
        shutil.copy(src, os.path.join(dst, filename))

    # Write out a runtime.txt file based on configuration
    pyversion = config.get("heroku_python_version")
    with open(os.path.join(dst, "runtime.txt"), "w") as file:
        file.write("python-{}".format(pyversion))

    if not config.get("clock_on"):
        # If the clock process has been disabled, overwrite the Procfile:
        src = os.path.join(dallinger_root, "heroku", "Procfile_no_clock")
        shutil.copy(src, os.path.join(dst, "Procfile"))

    return dst


def setup_experiment(log, debug=True, verbose=False, app=None, exp_config=None):
    """Checks the experiment's python dependencies, then prepares a temp directory
    with files merged from the custom experiment and Dallinger.

    The resulting directory includes all the files necessary to deploy to
    Heroku.
    """

    # Verify that the Postgres server is running.
    try:
        db.check_connection()
    except Exception:
        log("There was a problem connecting to the Postgres database!")
        raise

    # Check that the demo-specific requirements are satisfied.
    try:
        with open("requirements.txt", "r") as f:
            dependencies = [r for r in f.readlines() if r[:3] != "-e "]
    except (OSError, IOError):
        dependencies = []
    pkg_resources.require(dependencies)

    # Generate a unique id for this experiment.
    from dallinger.experiment import Experiment

    generated_uid = public_id = Experiment.make_uuid(app)

    # If the user provided an app name, use it everywhere that's user-facing.
    if app:
        public_id = str(app)

    log("Experiment id is " + public_id + "")

    # Load and update the config
    config = get_config()
    if not config.ready:
        config.load()  #
    if exp_config:
        config.extend(exp_config)
    config.extend({"id": six.text_type(generated_uid)})

    temp_dir = assemble_experiment_temp_dir(config)
    log("Deployment temp directory: {}".format(temp_dir), chevrons=False)

    # Zip up the temporary directory and place it in the cwd.
    if not debug:
        log("Freezing the experiment package...")
        shutil.make_archive(
            os.path.join(os.getcwd(), "snapshots", public_id + "-code"), "zip", temp_dir
        )

    return (public_id, temp_dir)


INITIAL_DELAY = 5
BACKOFF_FACTOR = 2
MAX_ATTEMPTS = 4


def _handle_launch_data(url, error, delay=INITIAL_DELAY, attempts=MAX_ATTEMPTS):
    for remaining_attempt in sorted(range(attempts), reverse=True):  # [3, 2, 1, 0]
        time.sleep(delay)
        launch_request = requests.post(url)
        try:
            launch_data = launch_request.json()
        except ValueError:
            error(
                "Error parsing response from /launch, "
                "check web dyno logs for details: " + launch_request.text
            )
            raise

        # Early return if successful
        if launch_request.ok:
            return launch_data

        error(
            "Error accessing /launch ({}):\n{}".format(
                launch_request.status_code, launch_request.text
            )
        )

        if remaining_attempt:
            delay = delay * BACKOFF_FACTOR
            next_attempt_count = attempts - (remaining_attempt - 1)
            error(
                "Experiment launch failed. Trying again "
                "(attempt {} of {}) in {} seconds ...".format(
                    next_attempt_count, attempts, delay
                )
            )

    error("Experiment launch failed, check web dyno logs for details.")
    if launch_data.get("message"):
        error(launch_data["message"])
    launch_request.raise_for_status()


def deploy_sandbox_shared_setup(log, verbose=True, app=None, exp_config=None):
    """Set up Git, push to Heroku, and launch the app."""
    if verbose:
        out = None
    else:
        out = open(os.devnull, "w")

    config = get_config()
    if not config.ready:
        config.load()
    heroku.sanity_check(config)

    (id, tmp) = setup_experiment(log, debug=False, app=app, exp_config=exp_config)

    # Register the experiment using all configured registration services.
    if config.get("mode") == "live":
        log("Registering the experiment on configured services...")
        registration.register(id, snapshot=None)

    # Log in to Heroku if we aren't already.
    log("Making sure that you are logged in to Heroku.")
    heroku.log_in()
    config.set("heroku_auth_token", heroku.auth_token())
    log("", chevrons=False)

    # Change to temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    # Commit Heroku-specific files to tmp folder's git repo.
    git = GitClient(output=out)
    git.init()
    git.add("--all")
    git.commit('"Experiment {}"'.format(id))

    # Initialize the app on Heroku.
    log("Initializing app on Heroku...")
    team = config.get("heroku_team", None)
    heroku_app = HerokuApp(dallinger_uid=id, output=out, team=team)
    heroku_app.bootstrap()
    heroku_app.buildpack("https://github.com/stomita/heroku-buildpack-phantomjs")

    # Set up add-ons and AWS environment variables.
    database_size = config.get("database_size")
    redis_size = config.get("redis_size")
    addons = [
        "heroku-postgresql:{}".format(quote(database_size)),
        "heroku-redis:{}".format(quote(redis_size)),
        "papertrail",
    ]
    if config.get("sentry"):
        addons.append("sentry")

    for name in addons:
        heroku_app.addon(name)

    heroku_config = {
        "aws_access_key_id": config["aws_access_key_id"],
        "aws_secret_access_key": config["aws_secret_access_key"],
        "aws_region": config["aws_region"],
        "auto_recruit": config["auto_recruit"],
        "smtp_username": config["smtp_username"],
        "smtp_password": config["smtp_password"],
        "whimsical": config["whimsical"],
    }

    heroku_app.set_multiple(**heroku_config)

    # Wait for Redis database to be ready.
    log("Waiting for Redis...")
    ready = False
    while not ready:
        try:
            r = redis.from_url(heroku_app.redis_url)
            r.set("foo", "bar")
            ready = True
        except (ValueError, redis.exceptions.ConnectionError):
            time.sleep(2)

    log("Saving the URL of the postgres database...")
    config.extend({"database_url": heroku_app.db_url})
    config.write()
    git.add("config.txt")
    time.sleep(0.25)
    git.commit("Save URL for database")
    time.sleep(0.25)

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    git.push(remote="heroku", branch="HEAD:master")

    log("Scaling up the dynos...")
    default_size = config.get("dyno_type")
    for process in ["web", "worker"]:
        size = config.get("dyno_type_" + process, default_size)
        qty = config.get("num_dynos_" + process)
        heroku_app.scale_up_dyno(process, qty, size)
    if config.get("clock_on"):
        heroku_app.scale_up_dyno("clock", 1, size)

    time.sleep(8)

    # Launch the experiment.
    log("Launching the experiment on the remote server and starting recruitment...")
    launch_data = _handle_launch_data("{}/launch".format(heroku_app.url), error=log)
    result = {
        "app_name": heroku_app.name,
        "app_home": heroku_app.url,
        "recruitment_msg": launch_data.get("recruitment_msg", None),
    }
    log("Experiment details:")
    log("App home: {}".format(result["app_home"]), chevrons=False)
    log("Recruiter info:")
    log(result["recruitment_msg"], chevrons=False)

    # Return to the branch whence we came.
    os.chdir(cwd)

    log("Completed deployment of experiment " + id + ".")
    return result


def _deploy_in_mode(mode, app, verbose, log):
    # Load configuration.
    config = get_config()
    config.load()

    # Set the mode.
    config.extend({"mode": mode, "logfile": "-"})

    # Do shared setup.
    deploy_sandbox_shared_setup(log, verbose=verbose, app=app)


class HerokuLocalDeployment(object):

    exp_id = None
    tmp_dir = None
    dispatch = {}  # Subclass may provide handlers for Heroku process output

    def configure(self):
        self.exp_config.update({"mode": "debug", "loglevel": 0})

    def setup(self):
        self.exp_id, self.tmp_dir = setup_experiment(
            self.out.log, exp_config=self.exp_config
        )

    def update_dir(self):
        os.chdir(self.tmp_dir)
        # Update the logfile to the new directory
        config = get_config()
        logfile = config.get("logfile")
        if logfile and logfile != "-":
            logfile = os.path.join(self.original_dir, logfile)
            config.extend({"logfile": logfile})
            config.write()

    def run(self):
        """Set up the environment, get a HerokuLocalWrapper instance, and pass
        it to the concrete class's execute() method.
        """
        self.configure()
        self.setup()
        self.update_dir()
        db.init_db(drop_all=True)
        self.out.log("Starting up the server...")
        config = get_config()
        with HerokuLocalWrapper(config, self.out, verbose=self.verbose) as wrapper:
            try:
                self.execute(wrapper)
            except KeyboardInterrupt:
                pass
            finally:
                os.chdir(self.original_dir)
                self.cleanup()

    def notify(self, message):
        """Callback function which checks lines of output, tries to match
        against regex defined in subclass's "dispatch" dict, and passes through
        to a handler on match.
        """
        for regex, handler in self.dispatch.items():
            match = re.search(regex, message)
            if match:
                handler = getattr(self, handler)
                return handler(match)

    def execute(self, heroku):
        raise NotImplementedError()


class DebugDeployment(HerokuLocalDeployment):

    dispatch = {
        r"[^\"]{} (.*)$".format(recruiters.NEW_RECRUIT_LOG_PREFIX): "new_recruit",
        r"{}".format(recruiters.CLOSE_RECRUITMENT_LOG_PREFIX): "recruitment_closed",
    }

    def __init__(self, output, verbose, bot, proxy_port, exp_config):
        self.out = output
        self.verbose = verbose
        self.bot = bot
        self.exp_config = exp_config or {}
        self.proxy_port = proxy_port
        self.original_dir = os.getcwd()
        self.complete = False
        self.status_thread = None

    def configure(self):
        super(DebugDeployment, self).configure()
        if self.bot:
            self.exp_config["recruiter"] = "bots"

    def execute(self, heroku):
        base_url = get_base_url()
        self.out.log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))
        self.out.log("Launching the experiment...")
        time.sleep(4)
        try:
            result = _handle_launch_data(
                "{}/launch".format(base_url), error=self.out.error, attempts=1
            )
        except Exception:
            # Show output from server
            self.dispatch[r"POST /launch"] = "launch_request_complete"
            heroku.monitor(listener=self.notify)
        else:
            if result["status"] == "success":
                self.out.log(result["recruitment_msg"])
                self.heroku = heroku
                heroku.monitor(listener=self.notify)

    def launch_request_complete(self, match):
        return HerokuLocalWrapper.MONITOR_STOP

    def cleanup(self):
        self.out.log("Completed debugging of experiment with id " + self.exp_id)
        self.complete = True

    def new_recruit(self, match):
        """Dispatched to by notify(). If a recruitment request has been issued,
        open a browser window for the a new participant (in this case the
        person doing local debugging).
        """
        self.out.log("new recruitment request!")
        url = match.group(1)
        if self.proxy_port is not None:
            self.out.log("Using proxy port {}".format(self.proxy_port))
            url = url.replace(str(get_config().get("base_port")), self.proxy_port)
        new_webbrowser_profile().open(url, new=1, autoraise=True)

    def recruitment_closed(self, match):
        """Recruitment is closed.

        Start a thread to check the experiment summary.
        """
        if self.status_thread is None:
            self.status_thread = threading.Thread(target=self.check_status)
            self.status_thread.start()

    def check_status(self):
        """Check the output of the summary route until
        the experiment is complete, then we can stop monitoring Heroku
        subprocess output.
        """
        self.out.log("Recruitment is complete. Waiting for experiment completion...")
        base_url = get_base_url()
        status_url = base_url + "/summary"
        while not self.complete:
            time.sleep(10)
            try:
                resp = requests.get(status_url)
                exp_data = resp.json()
            except (ValueError, requests.exceptions.RequestException):
                self.out.error("Error fetching experiment status.")
            else:
                self.out.log("Experiment summary: {}".format(exp_data))
                if exp_data.get("completed", False):
                    self.out.log("Experiment completed, all nodes filled.")
                    self.complete = True
                    self.heroku.stop()

    def notify(self, message):
        """Monitor output from heroku process.

        This overrides the base class's `notify`
        to make sure that we stop if the status-monitoring thread
        has determined that the experiment is complete.
        """
        if self.complete:
            return HerokuLocalWrapper.MONITOR_STOP
        return super(DebugDeployment, self).notify(message)


class LoaderDeployment(HerokuLocalDeployment):
    dispatch = {"Replay ready: (.*)$": "start_replay"}

    def __init__(self, app_id, output, verbose, exp_config):
        self.app_id = app_id
        self.out = output
        self.verbose = verbose
        self.exp_config = exp_config or {}
        self.original_dir = os.getcwd()
        self.zip_path = None

    def configure(self):
        self.exp_config.update({"mode": "debug", "loglevel": 0})

        self.zip_path = data.find_experiment_export(self.app_id)
        if self.zip_path is None:
            msg = 'Dataset export for app id "{}" could not be found.'
            raise IOError(msg.format(self.app_id))

    def setup(self):
        self.exp_id, self.tmp_dir = setup_experiment(
            self.out.log, app=self.app_id, exp_config=self.exp_config
        )

    def execute(self, heroku):
        """Start the server, load the zip file into the database, then loop
        until terminated with <control>-c.
        """
        db.init_db(drop_all=True)
        self.out.log(
            "Ingesting dataset from {}...".format(os.path.basename(self.zip_path))
        )
        data.ingest_zip(self.zip_path)
        base_url = get_base_url()
        self.out.log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))

        if self.exp_config.get("replay"):
            self.out.log("Launching the experiment...")
            time.sleep(4)
            _handle_launch_data("{}/launch".format(base_url), error=self.out.error)
            heroku.monitor(listener=self.notify)

        # Just run until interrupted:
        while self.keep_running():
            time.sleep(1)

    def start_replay(self, match):
        """Dispatched to by notify(). If a recruitment request has been issued,
        open a browser window for the a new participant (in this case the
        person doing local debugging).
        """
        self.out.log("replay ready!")
        url = match.group(1)
        new_webbrowser_profile().open(url, new=1, autoraise=True)

    def cleanup(self):
        self.out.log("Terminating dataset load for experiment {}".format(self.exp_id))

    def keep_running(self):
        # This is a separate method so that it can be replaced in tests
        return True
