from __future__ import unicode_literals
import functools
import io
import locale
import os
import random
import redis
import shutil
import string
import subprocess
import sys
import tempfile
import webbrowser
from pkg_resources import get_distribution

try:
    from importlib.metadata import files as files_metadata
except ImportError:
    from importlib_metadata import files as files_metadata
from six.moves.urllib.parse import urlparse

from dallinger.config import get_config
from dallinger.compat import is_command


def connect_to_redis(url=None):
    """Return a connection to Redis.

    If a URL is supplied, it will be used, otherwise an environment variable
    is checked before falling back to a default.

    Since we are generally running on Heroku, and configuring SSL certificates
    is challenging, we disable cert requirements on secure connections.
    """
    redis_url = url or os.getenv("REDIS_URL", "redis://localhost:6379")
    connection_args = {"url": redis_url}
    if urlparse(redis_url).scheme == "rediss":
        connection_args["ssl_cert_reqs"] = None

    return redis.from_url(**connection_args)


def get_base_url():
    """Returns the base url for the experiment.
    Looks into environment variable HOST first, then in the
    experiment config.
    If the URL is on Heroku makes sure the protocol is https.
    """
    config = get_config()
    host = os.getenv("HOST", config.get("host"))
    if host == "0.0.0.0":
        host = "localhost"

    if "herokuapp.com" in host:
        if host.startswith("https://"):
            base_url = host
        elif host.startswith("http://"):
            base_url = host.replace("http://", "https://")
        else:
            base_url = "https://{}".format(host)
    else:
        # debug mode
        base_port = config.get("base_port")
        port = random.randrange(base_port, base_port + config.get("num_dynos_web"))
        base_url = "http://{}:{}".format(host, port)

    return base_url


def dallinger_package_path():
    """Return the absolute path of the root directory of the installed
    Dallinger package:

    >>> utils.dallinger_package_location()
    '/Users/janedoe/projects/Dallinger3/dallinger'
    """
    dist = get_distribution("dallinger")
    src_base = os.path.join(dist.location, dist.project_name)

    return src_base


def generate_random_id(size=6, chars=string.ascii_uppercase + string.digits):
    """Generate random id numbers."""
    return "".join(random.choice(chars) for x in range(size))


def ensure_directory(path):
    """Create a matching path if it does not already exist"""
    if not os.path.exists(path):
        os.makedirs(path)


def run_command(cmd, out, ignore_errors=False):
    """We want to both send subprocess output to stdout or another file
    descriptor as the subprocess runs, *and* capture the actual exception
    message on errors. CalledProcessErrors do not reliably contain the
    underlying exception in either the 'message' or 'out' attributes, so
    we tee the stderr to a temporary file and if a CalledProcessError is
    raised we read its contents to recover stderr
    """
    tempdir = tempfile.mkdtemp()
    output_file = os.path.join(tempdir, "stderr")
    original_cmd = " ".join(cmd)
    p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.PIPE)
    t = subprocess.Popen(["tee", output_file], stdin=p.stderr, stdout=out)
    t.wait()
    p.communicate()
    p.stderr.close()
    if p.returncode != 0 and not ignore_errors:
        with open(output_file, "r") as output:
            error = output.read()
        message = 'Command: "{}": Error: "{}"'.format(
            original_cmd, error.replace("\n", "")
        )
        shutil.rmtree(tempdir, ignore_errors=True)
        raise CommandError(message)

    shutil.rmtree(tempdir, ignore_errors=True)
    return p.returncode


class CommandError(Exception):
    """Something went wrong executing a subprocess command"""


class GitError(Exception):
    """Something went wrong calling a Git command"""


class GitClient(object):
    """Minimal wrapper, mostly for mocking"""

    def __init__(self, output=None):
        self.encoding = None
        if output is None:
            self.out = sys.stdout
        else:
            self.out = output

    def init(self, config=None):
        self._run(["git", "init"])
        if config is not None:
            for k, v in config.items():
                self._run(["git", "config", k, v])

    def add(self, what):
        self._run(["git", "add", what])

    def commit(self, msg):
        self._run(["git", "commit", "-m", '"{}"'.format(msg)])

    def push(self, remote, branch):
        cmd = ["git", "push", remote, branch]
        self._run(cmd)

    def clone(self, repository):
        tempdir = tempfile.mkdtemp()
        cmd = ["git", "clone", repository, tempdir]
        self._run(cmd)
        return tempdir

    def files(self):
        cmd = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        try:
            raw = check_output(cmd).decode(locale.getpreferredencoding())
        except Exception:
            return set()

        result = {item for item in raw.split("\0") if item}
        return result

    def _run(self, cmd):
        self._log(cmd)
        try:
            run_command(cmd, self.out)
        except CommandError as e:
            raise GitError(str(e))

    def _log(self, cmd):
        msg = '{}: "{}"'.format(self.__class__.__name__, " ".join(cmd))
        if self.encoding:
            msg = msg.encode(self.encoding)
        self.out.write(msg)


class ParticipationTime(object):

    grace_period_seconds = 120

    def __init__(self, participant, reference_time, config):
        self.participant = participant
        self.when = reference_time
        self.allowed_hours = config.get("duration")
        self.app_id = config.get("app_id", "unknown")

    @property
    def assignment_id(self):
        return self.participant.assignment_id

    @property
    def allowed_minutes(self):
        return self.allowed_hours * 60

    @property
    def allowed_seconds(self):
        return self.allowed_hours * 60.0 * 60.0

    @property
    def active_seconds(self):
        delta = self.when - self.participant.creation_time
        return delta.total_seconds()

    @property
    def active_minutes(self):
        return self.active_seconds / 60

    @property
    def excess_minutes(self):
        return (self.active_seconds - self.allowed_seconds) / 60

    @property
    def is_overdue(self):
        total_allowed_seconds = self.allowed_seconds + self.grace_period_seconds
        return self.active_seconds > total_allowed_seconds


def wrap_subprocess_call(func, wrap_stdout=True):
    @functools.wraps(func)
    def wrapper(*popenargs, **kwargs):
        out = kwargs.get("stdout", None)
        err = kwargs.get("stderr", None)
        replay_out = False
        replay_err = False
        if out is None and wrap_stdout:
            try:
                sys.stdout.fileno()
            except io.UnsupportedOperation:
                kwargs["stdout"] = tempfile.NamedTemporaryFile()
                replay_out = True
        if err is None:
            try:
                sys.stderr.fileno()
            except io.UnsupportedOperation:
                kwargs["stderr"] = tempfile.NamedTemporaryFile()
                replay_err = True
        try:
            return func(*popenargs, **kwargs)
        finally:
            if replay_out:
                kwargs["stdout"].seek(0)
                sys.stdout.write(kwargs["stdout"].read())
            if replay_err:
                kwargs["stderr"].seek(0)
                sys.stderr.write(kwargs["stderr"].read())

    return wrapper


check_call = wrap_subprocess_call(subprocess.check_call)
call = wrap_subprocess_call(subprocess.call)
check_output = wrap_subprocess_call(subprocess.check_output, wrap_stdout=False)


def open_browser(url):
    """Open a browser with a fresh profile"""
    _new_webbrowser_profile().open(url, new=1, autoraise=True)


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


def _new_webbrowser_profile():
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
        config = get_config()
        chrome_path = config.get("chrome-path")
        if os.path.exists(chrome_path):
            return _make_chrome(chrome_path)
        else:
            return webbrowser
    else:
        return webbrowser


def struct_to_html(data):
    parts = ["<ul>"]
    if isinstance(data, (list, tuple)):
        for i in data:
            parts.append(struct_to_html(i))
    elif isinstance(data, dict):
        if len(data) == 2 and "count" in data and "failed" in data:
            if data["count"]:
                failed_percentage = float(data["failed"]) / data["count"] * 100
            else:
                failed_percentage = 0
            value = "{} total, {} failed ({:.1f}%)".format(
                data["count"], data["failed"], failed_percentage
            )
            if failed_percentage == 100:
                value = '<span class="all-failures">{}</span>'.format(value)
            elif failed_percentage > 0:
                value = '<span class="some-failures">{}</span>'.format(value)
            elif data["count"]:
                value = '<span class="no-failures">{}</span>'.format(value)
            return value

        for k in data:
            item = struct_to_html(data[k])
            parts.append("<li>{}: {}</li>".format(k, item))
    else:
        return str(data)

    parts.append("</ul>")
    return "\n".join(parts)


def abspath_from_egg(egg, path):
    """Given a path relative to the egg root, find the absolute
    filesystem path for that resource.
    For instance this file's absolute path can be found invoking
    `abspath_from_egg("dallinger", "dallinger/utils.py")`.
    Returns a `pathlib.Path` object or None if the path was not found.
    """
    for file in files_metadata(egg):
        if str(file) == path:
            return file.locate()
    return None


def get_editable_dallinger_path():
    """In case dallinger was installed as editable package
    (for instance with `pip install -e`) it returns its location.
    Otherwise returns None.
    """
    for path_item in sys.path:
        egg_link = os.path.join(path_item, "dallinger.egg-link")
        if os.path.isfile(egg_link):
            return open(egg_link).read().split()[0]
    return None
