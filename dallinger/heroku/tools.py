"""Miscellaneous tools for Heroku."""

import signal
import os
import psutil
import re
try:
    from pipes import quote
except ImportError:
    # Python >= 3.3
    from shlex import quote
import subprocess
import traceback

from dallinger.config import get_config
from dallinger.compat import unicode


class HerokuApp(object):
    """Representation of a Heroku app"""

    def __init__(self, dallinger_uid, output, team=None):
        self.dallinger_uid = dallinger_uid
        self.out = output
        self.team = team

    def bootstrap(self):
        """Creates the heroku app and local git remote. Call this once you're
        in the local repo you're going to use.
        """
        cmd = [
            "heroku",
            "apps:create",
            self.name,
            "--buildpack",
            "https://github.com/thenovices/heroku-buildpack-scipy",
        ]

        # If a team is specified, assign the app to the team.
        if self.team:
            cmd.extend(["--org", self.team])

        self._run_command(cmd)

    @property
    def name(self):
        return "dlgr-" + self.dallinger_uid[0:8]

    @property
    def url(self):
        return "https://{}.herokuapp.com/".format(self.name)

    def addon(self, name):
        """Set up an addon"""
        cmd = ["heroku", "addons:create", name, "--app", self.name]
        self._run_command(cmd)

    def buildpack(self, url):
        """Add a buildpack by URL."""
        cmd = ["heroku", "buildpacks:add", url, "--app", self.name]
        self._run_command(cmd)

    @property
    def db_uri(self):
        """Not sure what this returns"""
        output = self.get("DATABASE", subcommand="pg:credentials")
        match = re.search('(postgres://.*)$', output)
        return match.group(1)

    @property
    def db_url(self):
        """Return the URL for the app's database once we know
        it's fully built
        """
        subprocess.check_call(["heroku", "pg:wait", "--app", self.name])
        url = self.get('DATABASE_URL')
        return url.rstrip().decode('utf8')

    def destroy(self):
        """Destroy an app and all its add-ons"""
        result = subprocess.check_output(
            ["heroku", "apps:destroy", "--app", self.name, "--confirm", self.name]
        )
        return result

    def get(self, key, subcommand="config:get"):
        """Get a app config value by name"""
        cmd = ["heroku", subcommand, key, "--app", self.name]
        return subprocess.check_output(cmd)

    def open_logs(self):
        """Show the logs."""
        cmd = ["heroku", "addons:open", "papertrail", "--app", self.name]
        self._run_command(cmd)

    @property
    def redis_url(self):
        return self.get("REDIS_URL")

    def scale_up_dynos(self, dyno_type, web_count, worker_count, clock_on=False):
        """Scale up the Heroku dynos."""
        dynos = {
            "web": web_count,
            "worker": worker_count,
        }

        for process, count in dynos.items():
            subprocess.check_call([
                "heroku",
                "ps:scale",
                "{}={}:{}".format(process, count, dyno_type),
                "--app", self.name,
            ])

        if clock_on:
            subprocess.check_call([
                "heroku",
                "ps:scale",
                "clock=1:{}".format(dyno_type),
                "--app", self.name,
            ])

    def set(self, key, value):
        """Configure an app key/value pair"""
        cmd = [
            "heroku",
            "config:set",
            "{}={}".format(key, quote(str(value))),
            "--app", self.name
        ]
        subprocess.check_call(cmd, stdout=self.out)

    def _run_command(self, cmd):
        return subprocess.check_call(cmd, stdout=self.out)


def app_name(id):
    """Convert a UUID to a valid Heroku app name."""
    return "dlgr-" + id[0:8]


def auth_token():
    """A Heroku authenication token."""
    return unicode(subprocess.check_output(["heroku", "auth:token"]).rstrip())


def create(id, out, team=None):
    """Create a new Heroku app"""
    create_cmd = [
        "heroku",
        "apps:create",
        app_name(id),
        "--buildpack",
        "https://github.com/thenovices/heroku-buildpack-scipy",
    ]

    # If a team is specified, assign the app to the team.
    if team:
        create_cmd.extend(["--org", team])

    subprocess.check_call(create_cmd, stdout=out)


def addon(app, name, out):
    """Add an extension to an app"""
    cmd = ["heroku", "addons:create", name, "--app", app]
    subprocess.check_call(cmd, stdout=out)


def log_in():
    """Ensure that the user is logged in to Heroku."""
    try:
        subprocess.check_output(["heroku", "auth:whoami"])
    except Exception:
        raise Exception("You are not logged into Heroku.")


def db_uri(app):
    output = subprocess.check_output([
        "heroku",
        "pg:credentials",
        "DATABASE",
        "--app", app_name(app)
    ])
    match = re.search('(postgres://.*)$', output)
    return match.group(1)


def scale_up_dynos(app):
    """Scale up the Heroku dynos."""
    config = get_config()
    if not config.ready:
        config.load()

    dyno_type = config.get('dyno_type')

    num_dynos = {
        "web": config.get('num_dynos_web'),
        "worker": config.get('num_dynos_worker'),
    }

    for process in ["web", "worker"]:
        subprocess.check_call([
            "heroku",
            "ps:scale",
            "{}={}:{}".format(process, num_dynos[process], dyno_type),
            "--app", app,
        ])

    if config.get('clock_on'):
        subprocess.check_call([
            "heroku",
            "ps:scale",
            "clock=1:{}".format(dyno_type),
            "--app", app,
        ])


def open_logs(app):
    """Show the logs."""
    if app is None:
        raise TypeError("Select an experiment using the --app flag.")
    else:
        subprocess.check_call([
            "heroku", "addons:open", "papertrail", "--app", app_name(app)
        ])


def destroy(app):
    """Destroy an app and all its add-ons"""
    result = subprocess.check_output(
        ["heroku", "apps:destroy", "--app", app, "--confirm", app]
    )
    return result


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

    shell_command = 'heroku'
    success_regex = '^.*? \d+ workers$'
    # On Windows, use 'CTRL_C_EVENT', otherwise SIGINT
    int_signal = getattr(signal, 'CTRL_C_EVENT', signal.SIGINT)
    MONITOR_STOP = object()
    STREAM_SENTINEL = ' '

    def __init__(self, config, output, verbose=True, env=None):
        self.config = config
        self.out = output
        self.verbose = verbose
        self.env = env if env is not None else os.environ.copy()
        self._record = []
        self._process = None

    def start(self, timeout_secs=45):
        """Start the heroku local subprocess group and verify that
        it has started successfully.

        The subprocess output is checked for a line matching 'success_regex'
        to indicate success. If no match is seen after 'timeout_secs',
        a HerokuTimeoutError is raised.
        """
        def _handle_timeout(signum, frame):
            raise HerokuTimeoutError(
                "Failed to start after {} seconds.".format(
                    timeout_secs, self._record)
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
            self.stop(signal.SIGKILL)
            raise HerokuStartupError(
                "Failed to start for unknown reason: {}".format(self._record)
            )
        return True

    @property
    def is_running(self):
        return self._process is not None

    def stop(self, signal=None):
        """Stop the heroku local subprocess and all of its children.
        """
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
        """Relay the stream to listener until told to stop.
        """
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
                    'Could not connect to redis instance, '
                    'experiment may not behave correctly.'
                )

            if self._worker_error(line) or self._startup_error(line):
                if not self.verbose:
                    self.out.error(
                        'There was an error while starting the server. '
                        'Run with --verbose for details.'
                    )
                    self.out.error("Sign of error found in line: ".format(line))
                return False

        return False

    def _boot(self):
        port = self.config.get('base_port')
        web_dynos = self.config.get('num_dynos_web', 1)
        worker_dynos = self.config.get('num_dynos_worker', 1)
        commands = [
            self.shell_command, 'local', '-p', str(port),
            "web={},worker={}".format(web_dynos, worker_dynos)
        ]
        try:
            self._process = subprocess.Popen(
                commands,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self.env,
                preexec_fn=os.setsid,
            )
        except OSError:
            self.out.error("Couldn't start Heroku for local debugging.")
            raise

    def _stream(self):
        return iter(self._process.stdout.readline, self.STREAM_SENTINEL)

    def _up_and_running(self, line):
        return re.match(self.success_regex, line)

    def _redis_not_running(self, line):
        return re.match('^.*? worker.1 .*? Connection refused.$', line)

    def _worker_error(self, line):
        return re.match('^.*? web.1 .*? \[ERROR\] (.*?)$', line)

    def _startup_error(self, line):
        return re.match('\[DONE\] Killing all processes', line)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exctype, excinst, exctb):
        self.stop()

    def __repr__(self):
        classname = self.__class__.__name__
        if not self.is_running:
            return "<{} (not running)>".format(classname)

        reprs = []
        for child in psutil.Process(self._process.pid).children(recursive=True):
            if 'python' in child.name():
                name = ''.join(child.cmdline())
            else:
                name = child.name()
            reprs.append("<Process pid='{}', name='{}', status='{}'>".format(
                child.pid, name, child.status())
            )

        return "<{} pid='{}', children: {}>".format(
            classname, self._process.pid, reprs
        )
