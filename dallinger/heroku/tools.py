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


class TimeoutError(Exception):
    pass


class HerokuLocalRunner(object):

    shell_command = 'heroku'
    success_regex = '^.*? \d+ workers$'
    MONITOR_STOP = object()

    def __init__(self, config, log, error, blather, verbose=True, timeout=15, env=None):
        self.config = config
        self.log = log
        self.error = error
        self.blather = blather
        self.verbose = verbose
        self.timeout = timeout
        self.env = env if env is not None else os.environ.copy()
        self._record = []
        self._running = False

    def start(self):
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.alarm(self.timeout)
        try:
            result = self._verify_startup()
        finally:
            signal.alarm(0)
        return result

    def monitor(self, dispatch):
        for line in self.stream():
            self._record.append(line)
            if self.verbose:
                self.blather(line)
            for regex, handler in dispatch.items():
                match = re.search(regex, line)
                if match:
                    response = handler(match)
                    if response is self.MONITOR_STOP:
                        return

    def stream(self):
        return iter(self._process.stdout.readline, '')

    def stop(self, int_signal=signal.SIGTERM):
        self.log("Cleaning up local Heroku process...")
        if not self._running:
            self.log("No local Heroku process was running.")
            return

        try:
            os.killpg(os.getpgid(self._process.pid), int_signal)
            self.log("Local Heroku process terminated")
        except OSError:
            self.log("Local Heroku process already terminated")
            self.log(traceback.format_exc())
        finally:
            self._running = False

    def _verify_startup(self):
        for line in iter(self._process.stdout.readline, ''):
            self._record.append(line)
            if self.verbose:
                self.blather(line)
            line = line.strip()
            if self._up_and_running(line):
                return True

            if self._redis_not_running(line):
                self.error(
                    'Could not connect to redis instance, '
                    'experiment may not behave correctly.'
                )

            if self.verbose:
                continue

            if self._worker_error(line):
                self.error(line)
            if self._startup_error(line):
                self.error(
                    'There was an error while starting the server. '
                    'Run with --verbose for details.'
                )
        return False

    def _handle_timeout(self, signum, frame):
        msg = "Timeout of {} exceeded! {}".format(
            self.timeout, ''.join(self._record))
        raise TimeoutError(msg)

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
            self._running = True
            return p
        except OSError:
            self.error("Couldn't start Heroku for local debugging.")
            raise

    def _up_and_running(self, line):
        return re.match(self.success_regex, line)

    def _redis_not_running(self, line):
        return re.match('^.*? worker.1 .*? Connection refused.$', line)

    def _worker_error(self, line):
        return re.match('^.*? web.1 .*? \[ERROR\] (.*?)$', line)

    def _startup_error(self, line):
        return re.match('\[DONE\] Killing all processes', line)
