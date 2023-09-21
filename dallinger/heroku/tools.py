"""Miscellaneous tools for Heroku."""

from __future__ import unicode_literals

import json
import netrc
import os
import re
import signal
import subprocess
import sys
import time
import traceback

import psutil
import six
from cached_property import cached_property
from six.moves import shlex_quote as quote

from dallinger.config import SENSITIVE_KEY_NAMES
from dallinger.utils import check_call, check_output


def app_name(experiment_uuid):
    """Convert a UUID to a valid Heroku app name."""
    return "dlgr-" + experiment_uuid[:18]


def auth_token():
    """A Heroku authenication token."""
    return check_output(["heroku", "auth:token"]).rstrip().decode("utf8")


def log_in():
    """Ensure that the user is logged in to Heroku."""
    try:
        check_output(["heroku", "auth:whoami"])
    except Exception:
        raise Exception("You are not logged into Heroku.")


def container_log_in():
    """Ensure that the user is logged in to Heroku container registry."""
    check_output(["heroku", "container:login"])


def request_headers(auth_token):
    """Return request headers using the provided authorization token."""
    headers = {
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
        "Authorization": "Bearer {}".format(auth_token),
    }

    return headers


class HerokuCommandRunner(object):
    """Heroku command runner base class"""

    def __init__(self, output=None, team=None):
        self.out = output
        self.team = team
        self.out_muted = open(os.devnull, "w")

    @property
    def sys_encoding(self):
        # Encoding of strings returned from subprocess calls. The Click
        # library overwrites sys.stdout in the context of its commands,
        # so we need a fallback, which could possibly just be 'utf-8' instead
        # of getdefaultencoding().
        return getattr(sys.stdout, "encoding", sys.getdefaultencoding())

    def login_name(self):
        """Returns the current logged-in heroku user"""
        # The Heroku CLI client stores credentials in the user's netrc file
        return netrc.netrc().hosts["api.heroku.com"][0]

    def _run(self, cmd, pass_stderr=False):
        if pass_stderr:
            return check_call(cmd, stdout=self.out, stderr=self.out)
        return check_call(cmd, stdout=self.out)

    def _run_quiet(self, cmd):
        # make sure subprocess output doesn't echo secrets to the terminal
        return subprocess.check_call(cmd, stdout=self.out_muted)

    def _result(self, cmd):
        output = check_output(cmd)
        try:
            return output.decode(self.sys_encoding)
        except AttributeError:
            return output


class HerokuInfo(HerokuCommandRunner):
    """Methods for getting information about current heroku status"""

    def all_apps(self):
        """Capture a backup of the app."""
        cmd = ["heroku", "apps", "--json"]
        if self.team:
            cmd.extend(["--team", self.team])
        return json.loads(self._result(cmd))

    def my_apps(self):
        my_login = self.login_name()
        my_apps = []
        for app in self.all_apps():
            name = app.get("name")
            config = json.loads(
                self._result(["heroku", "config", "--json", "--app", name])
            )
            if config.get("CREATOR", "").strip() == my_login:
                app["dallinger_uid"] = config.get("DALLINGER_UID").strip()
                my_apps.append(app)
        return my_apps


class HerokuApp(HerokuCommandRunner):
    """Representation of a Heroku app"""

    def __init__(self, dallinger_uid, output=None, team=None):
        self.dallinger_uid = dallinger_uid
        super(HerokuApp, self).__init__(output, team)

    def bootstrap(self, buildpack="heroku/python"):
        """Creates the heroku app and local git remote. Call this once you're
        in the local repo you're going to use.
        """
        cmd = ["heroku", "apps:create", self.name]
        if buildpack:
            cmd += ["--buildpack", buildpack]

        # If a team is specified, assign the app to the team.
        if self.team:
            cmd.extend(["--team", self.team])

        self._run(cmd)
        # Set HOST value
        self.set_multiple(
            HOST=self.url, CREATOR=self.login_name(), DALLINGER_UID=self.dallinger_uid
        )

    def push_containers(self):
        """Push docker containers to Heroku.
        Reuqires Dockerfile.web and Dockerfile.worker to be present.
        """
        try:
            # We optimistically assume the user is already logged in
            self._run(["heroku", "container:push", "--recursive", "-a", self.name])
        except subprocess.CalledProcessError:
            self._run(["heroku", "container:login"])
            self._run(["heroku", "container:push", "--recursive", "-a", self.name])

    def release_containers(self):
        """Start the dynos for web and worker"""
        self._run(
            ["heroku", "container:release", "web", "worker", "clock", "-a", self.name]
        )

    @property
    def name(self):
        return app_name(self.dallinger_uid)

    @cached_property
    def url(self):
        app_info = self._result(
            [
                "heroku",
                "apps:info",
                "--app",
                self.name,
                "--json",
            ]
        )
        return json.loads(app_info)["app"]["web_url"].rstrip("/")

    def addon(self, name):
        """Set up an addon"""
        cmd = ["heroku", "addons:create", name, "--app", self.name]
        self._run(cmd)

    def addon_destroy(self, name):
        """Destroy an addon"""
        self._run(
            [
                "heroku",
                "addons:destroy",
                name,
                "--app",
                self.name,
                "--confirm",
                self.name,
            ]
        )

    def buildpack(self, url):
        """Add a buildpack by URL."""
        cmd = ["heroku", "buildpacks:add", url, "--app", self.name]
        self._run(cmd)

    @property
    def config_url(self):
        """Endpoint for sending configuration on api.heroku.com"""
        return "https://api.heroku.com/apps/{}/config-vars".format(self.name)

    @property
    def clock_is_on(self):
        cmd = ["heroku", "ps:scale", "--app", self.name]
        output = self._result(cmd)
        return "clock=1" in output

    @property
    def dashboard_url(self):
        return "https://dashboard.heroku.com/apps/{}".format(self.name)

    @property
    def dashboard_metrics_url(self):
        return "{}/metrics".format(self.dashboard_url)

    @property
    def db_uri(self):
        """The connection URL for the remote database. For example:
        postgres://some-long-uid@ec2-52-7-232-59.compute-1.amazonaws.com:5432/d5fou154it1nvt
        """
        output = self.get("DATABASE", subcommand="pg:credentials:url")
        match = re.search("(postgres://.*)$", output)
        if match is None:
            raise NameError(
                "Could not retrieve the DB URI. Check for error output from "
                "heroku above the stack trace."
            )
        return match.group(1)

    @property
    def db_url(self):
        """Return the URL for the app's database once we know
        it's fully built
        """
        self.pg_wait()
        url = self.get("DATABASE_URL")
        return url.strip()

    def backup_capture(self):
        """Capture a backup of the app."""
        self._run(
            ["heroku", "pg:backups:capture", "--app", self.name], pass_stderr=True
        )

    def backup_download(self):
        """Download a backup to the current working directory."""
        self._run(
            ["heroku", "pg:backups:download", "--app", self.name], pass_stderr=True
        )

    def destroy(self):
        """Destroy an app and all its add-ons"""
        result = self._result(
            ["heroku", "apps:destroy", "--app", self.name, "--confirm", self.name]
        )
        return result

    def get(self, key, subcommand="config:get"):
        """Get a app config value by name"""
        cmd = ["heroku", subcommand, key, "--app", self.name]
        return self._result(cmd)

    def open_logs(self):
        """Show the logs."""
        cmd = ["heroku", "addons:open", "papertrail", "--app", self.name]
        self._run(cmd)

    def pg_pull(self):
        """Pull remote data from a Heroku Postgres database to a database
        of the same name on your local machine.
        """
        self._run(["heroku", "pg:pull", "DATABASE_URL", self.name, "--app", self.name])

    def pg_wait(self):
        """Wait for the DB to be fired up."""
        retries = 10
        while retries:
            retries = retries - 1
            try:
                self._run(["heroku", "pg:wait", "--app", self.name])
            except subprocess.CalledProcessError:
                time.sleep(5)
                if not retries:
                    raise
            else:
                break

    @property
    def redis_url(self):
        return self.get("REDIS_URL")

    def restore(self, url):
        """Restore the remote database from the URL of a backup."""
        self._run(
            [
                "heroku",
                "pg:backups:restore",
                "{}".format(url),
                "DATABASE_URL",
                "--app",
                self.name,
                "--confirm",
                self.name,
            ]
        )

    def scale_up_dyno(self, process, quantity, size):
        """Scale up a dyno."""
        self._run(
            [
                "heroku",
                "ps:scale",
                "{}={}:{}".format(process, quantity, size),
                "--app",
                self.name,
            ]
        )

    def scale_down_dyno(self, process):
        """Turn off a dyno by setting its process count to 0"""
        self._run(["heroku", "ps:scale", "{}=0".format(process), "--app", self.name])

    def scale_down_dynos(self):
        """Turn off web and worker dynos, plus clock process if
        there is one and it's active.
        """
        processes = ["web", "worker"]
        if self.clock_is_on:
            processes.append("clock")
        for process in processes:
            self.scale_down_dyno(process)

    def set(self, key, value):
        """Configure an app key/value pair"""
        cmd = [
            "heroku",
            "config:set",
            "{}={}".format(key, quote(str(value))),
            "--app",
            self.name,
        ]
        if self._is_sensitive_key(key):
            self._run_quiet(cmd)
        else:
            self._run(cmd)

    def set_multiple(self, **kwargs):
        """Configure multiple app key/value pairs"""
        quiet = False
        if not kwargs:
            return
        cmd = ["heroku", "config:set"]
        for k in sorted(kwargs):
            cmd.append("{}={}".format(k, quote(str(kwargs[k]))))
            if self._is_sensitive_key(k):
                quiet = True
        cmd.extend(["--app", self.name])
        if quiet:
            self._run_quiet(cmd)
        else:
            self._run(cmd)

    def _is_sensitive_key(self, key):
        return any([s in key for s in SENSITIVE_KEY_NAMES])

    def addon_parameters(self):
        addon_listing = self._result(["heroku", "addons", "--app", self.name])
        addon_types = re.findall("as ([A-Z]+)", addon_listing)
        addon_info = {}
        for addon_type in addon_types:
            url = self._result(
                ["heroku", "addons:open", "--app", self.name, addon_type, "--show-url"]
            ).strip()
            addon_info[addon_type] = {
                "url": url,
                "title": addon_type.title(),
            }
        return addon_info


class HerokuStartupError(RuntimeError):
    """The Heroku subprocess did not start"""


class HerokuTimeoutError(HerokuStartupError):
    """The Heroku subprocess does not appear to have started within
    the maximum allowed time.
    """


class HerokuLocalWrapper(object):
    """Wrapper around a heroku local subprocess.

    Provides for verified startup and shutdown, and allows observers to register
    to recieve subprocess output via 'monitor()'.

    Implements a context manager pattern:

        with HerokuLocalWrapper(config, output) as heroku:
            heroku.monitor(my_callback)

    Arg 'output' should implement log(), error() and blather() methods taking
    strings as arguments.
    """

    shell_command = "heroku"
    success_regex = r"^.*? \d+ workers$"
    # On Windows, use 'CTRL_C_EVENT', otherwise SIGINT
    int_signal = getattr(signal, "CTRL_C_EVENT", signal.SIGINT)
    MONITOR_STOP = object()
    STREAM_SENTINEL = ""

    def __init__(
        self,
        config,
        output,
        experiment_name=None,
        tmp_dir=None,
        verbose=True,
        env=None,
        needs_chrome=False,
    ):
        self.config = config
        self.out = output
        self.verbose = verbose
        self.env = env if env is not None else os.environ.copy()
        self._record = []
        self._process = None
        # needs_chrome, tmp_dir and experiment_name are here just for simmetry with the Docker wrapper
        self.needs_chrome = needs_chrome
        self.experiment_name = experiment_name
        self.tmp_dir = tmp_dir

    def start(self, timeout_secs=60):
        """Start the heroku local subprocess group and verify that
        it has started successfully.

        The subprocess output is checked for a line matching 'success_regex'
        to indicate success. If no match is seen after 'timeout_secs',
        a HerokuTimeoutError is raised.
        """

        def _handle_timeout(signum, frame):
            raise HerokuTimeoutError(
                "Failed to start after {} seconds.".format(timeout_secs)
            )

        if self.is_running:
            self.out.log("Local Heroku is already running.")
            return

        signal.signal(signal.SIGALRM, _handle_timeout)
        signal.alarm(timeout_secs)
        self._boot()
        try:
            success = self._verify_startup()
        finally:
            signal.alarm(0)

        if not success:
            self._log_failure()
            self.stop(signal.SIGKILL)
            raise HerokuStartupError(
                "Failed to start for unknown reason: {}".format("".join(self._record))
            )
        return True

    @property
    def is_running(self):
        return self._process is not None

    def stop(self, signal=None):
        """Stop the heroku local subprocess and all of its children."""
        signal = signal or self.int_signal
        self.out.log("Cleaning up local Heroku process...")
        if self._process is None:
            self.out.log("No local Heroku process was running.")
            return

        try:
            os.killpg(os.getpgid(self._process.pid), signal)
            self.out.log("Local Heroku process terminated.")
        except OSError:
            self.out.log("Local Heroku was already terminated.")
            self.out.log(traceback.format_exc())
        finally:
            self._process = None

    def monitor(self, listener):
        """Relay the stream to listener until told to stop."""
        for line in self._stream():
            self._record.append(line)
            if self.verbose:
                self.out.blather(line)
            if listener(line) is self.MONITOR_STOP:
                return

    def _verify_startup(self):
        for line in self._stream():
            self._record.append(line)
            if self.verbose:
                self.out.blather(line)
            line = line.strip()
            if self._up_and_running(line):
                return True

            if self._redis_not_running(line):
                self.out.error(
                    "Could not connect to redis instance, "
                    "experiment may not behave correctly."
                )

            if self._worker_error(line) or self._startup_error(line):
                if not self.verbose:
                    self.out.error(
                        "There was an error while starting the server. "
                        "Run with --verbose for details."
                    )
                    self.out.error("Sign of error found in line: {}".format(line))
                return False

        return False

    def _log_failure(self):
        def _handle_final_log_timeout(signum, frame):
            raise TimeoutError()

        # Read remaining log data for up to 1 second
        signal.signal(signal.SIGALRM, _handle_final_log_timeout)
        signal.alarm(1)
        try:
            for line in self._stream():
                # Stop if the process has exited
                if self._process.poll() is not None:
                    return
                clean_line = line.strip()
                # Stop if we hit a new error indicator
                if self._worker_error(clean_line) or self._startup_error(clean_line):
                    return
                self._record.append(line)
        except TimeoutError:
            pass
        finally:
            signal.alarm(0)

    def _boot(self):
        # Child processes don't start without a HOME dir
        if not self.env.get("HOME", False):
            raise HerokuStartupError('"HOME" environment not set... aborting.')

        port = self.config.get("base_port")
        web_dynos = self.config.get("num_dynos_web")
        worker_dynos = self.config.get("num_dynos_worker")
        clock_dyno = self.config.get("clock_on")
        dyno_options = "web={},worker={}{}".format(
            web_dynos, worker_dynos, ",clock" if clock_dyno else ""
        )
        commands = [
            self.shell_command,
            "local",
            "-p",
            str(port),
            dyno_options,
        ]
        try:
            options = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "env": self.env,
                "preexec_fn": os.setsid,
            }
            if six.PY3:
                options["encoding"] = "utf-8"
            self._process = subprocess.Popen(commands, **options)
        except OSError:
            self.out.error("Couldn't start Heroku for local debugging.")
            raise

    def _stream(self):
        return iter(self._process.stdout.readline, self.STREAM_SENTINEL)

    def _up_and_running(self, line):
        return re.match(self.success_regex, line)

    def _redis_not_running(self, line):
        return re.match(r"^.*? worker.1 .*? Connection refused.$", line)

    def _worker_error(self, line):
        return re.match(r"^.*? web.1 .*? \[ERROR\] (.*?)$", line)

    def _startup_error(self, line):
        return re.match(r"\[DONE\] Killing all processes", line)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exctype, excinst, exctb):
        if self.is_running:
            self.stop()

    def __repr__(self):
        classname = self.__class__.__name__
        if not self.is_running:
            return "<{} (not running)>".format(classname)

        reprs = []
        for child in psutil.Process(self._process.pid).children(recursive=True):
            if "python" in child.name():
                name = "".join(child.cmdline())
            else:
                name = child.name()
            reprs.append(
                "<Process pid='{}', name='{}', status='{}'>".format(
                    child.pid, name, child.status()
                )
            )

        return "<{} pid='{}', children: {}>".format(classname, self._process.pid, reprs)


def sanity_check(config):
    # check if dyno size is compatible with team configuration.
    sizes = {
        config.get("dyno_type"),
        config.get("dyno_type_web", None),
        config.get("dyno_type_worker", None),
    }
    team = config.get("heroku_team", None)
    if team and "free" in sizes:
        raise RuntimeError(
            'Heroku "free" dyno type not compatible '
            "with team/org deployment. Please use a "
            'different "dyno_type" or unset the '
            '"heroku_team" configuration.'
        )
