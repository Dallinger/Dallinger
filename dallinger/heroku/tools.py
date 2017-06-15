"""Miscellaneous tools for Heroku."""

import signal
import os
import pexpect
import re
import subprocess
import traceback
from cached_property import cached_property

from dallinger.config import get_config
from dallinger.compat import unicode


def app_name(id):
    """Convert a UUID to a valid Heroku app name."""
    return "dlgr-" + id[0:8]


def auth_token():
    """A Heroku authenication token."""
    return unicode(subprocess.check_output(["heroku", "auth:token"]).rstrip())


def log_in():
    """Ensure that the user is logged in to Heroku."""
    p = pexpect.spawn("heroku auth:whoami")
    p.interact()


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


class HerokuStartupError(RuntimeError):
    """The Heroku subprocess did not start"""


class HerokuTimeoutError(HerokuStartupError):
    """The Heroku subprocess does not appear to have started within
    the maximum allowed time.
    """


class HerokuLocalWrapper(object):

    shell_command = 'heroku'
    success_regex = '^.*? \d+ workers$'
    # On Windows, use 'CTRL_C_EVENT', otherwise SIGINT
    int_signal = getattr(signal, 'CTRL_C_EVENT', signal.SIGINT)
    MONITOR_STOP = object()

    def __init__(self, config, output, verbose=True, timeout=16, env=None):
        self.config = config
        self.out = output
        self.verbose = verbose
        self.timeout = timeout
        self.env = env if env is not None else os.environ.copy()
        self._record = []
        self._running = False

    def start(self):
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.alarm(self.timeout)
        try:
            self._running = self._verify_startup()
        finally:
            signal.alarm(0)

        if not self._running:
            raise HerokuStartupError(
                "Failed to start for unknown reason: {}".format(self._record)
            )

        return True

    def monitor(self, listener):
        """Relay the stream to listener until told to stop.
        """
        for line in self.stream():
            self._record.append(line)
            if self.verbose:
                self.out.blather(line)
            if listener.notify(line) is self.MONITOR_STOP:
                return

    def stream(self):
        return iter(self._process.stdout.readline, '')

    def stop(self):
        self.out.log("Cleaning up local Heroku process...")
        if not self._running:
            self.out.log("No local Heroku process was running.")
            return

        try:
            os.killpg(os.getpgid(self._process.pid), self.int_signal)
            self.out.log("Local Heroku process terminated")
        except OSError:
            self.out.log("Local Heroku process already terminated")
            self.out.log(traceback.format_exc())
        finally:
            self._running = False

    def _verify_startup(self):
        for line in self.stream():
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

            if self.verbose:
                continue  # we already logged everything

            if self._worker_error(line):
                self.out.error(line)
            if self._startup_error(line):
                self.out.error(
                    'There was an error while starting the server. '
                    'Run with --verbose for details.'
                )
        return False

    def _handle_timeout(self, signum, frame):
        msg = "Timeout of {} seconds exceeded! {}".format(
            self.timeout, ''.join(self._record))
        raise HerokuTimeoutError(msg)

    @cached_property
    def _process(self):
        port = self.config.get('port')
        web_dynos = self.config.get('num_dynos_web', 1)
        worker_dynos = self.config.get('num_dynos_worker', 1)
        commands = [
            self.shell_command, 'local', '-p', str(port),
            "web={},worker={}".format(web_dynos, worker_dynos)
        ]
        try:
            p = subprocess.Popen(
                commands,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self.env,
                preexec_fn=os.setsid,
            )
            return p
        except OSError:
            self.out.error("Couldn't start Heroku for local debugging.")
            raise

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
