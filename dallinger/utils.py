from __future__ import unicode_literals
import functools
import io
import locale
import os
import pkg_resources
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
import webbrowser

from faker import Faker
from flask import request
from hashlib import md5
from pathlib import Path
from pkg_resources import get_distribution
from unicodedata import normalize

try:
    from importlib.metadata import files as files_metadata
except ImportError:
    from importlib_metadata import files as files_metadata

from dallinger import db
from dallinger.config import get_config
from dallinger.compat import is_command


fake = Faker()


def get_base_url():
    """Returns the base url for the experiment.
    Looks into environment variable HOST first, then in the
    experiment config.
    If the URL is on Heroku makes sure the protocol is https.
    """
    try:
        return f"{request.scheme}://{request.host}"
    except RuntimeError:
        pass
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


def setup_experiment(
    log, debug=True, verbose=False, app=None, exp_config=None, local_checks=True
):
    """Checks the experiment's python dependencies, then prepares a temp directory
    with files merged from the custom experiment and Dallinger.

    The resulting directory includes all the files necessary to deploy to
    Heroku.
    """

    # Verify that the Postgres server is running.
    if local_checks:
        try:
            log("Checking your local Postgres database connection...")
            db.check_connection()
        except Exception:
            log("There was a problem connecting!")
            raise

        # Check that the demo-specific requirements are satisfied.
        try:
            with open("requirements.txt", "r") as f:
                dependencies = [r for r in f.readlines() if r[:3] != "-e "]
        except (OSError, IOError):
            dependencies = []
        pkg_resources.require(dependencies)
    ensure_constraints_file_presence(os.getcwd())
    # Generate a unique id for this experiment.
    from dallinger.experiment import Experiment

    experiment_uid = heroku_app_id = Experiment.make_uuid(app)
    log("Experiment UID: {}".format(experiment_uid))

    # Load and update the config
    config = get_config()
    if not config.ready:
        config.load()  #
    if exp_config:
        config.extend(exp_config)

    # If the user provided an app name, store it. We'll use it as the basis for
    # the Heroku app ID. We still have a fair amount of ambiguity around what
    # this value actually represents (it's not used as _only_ the Heroku app ID).
    if app:
        heroku_app_id = str(app)
        log("Using custom Heroku ID root: {}".format(heroku_app_id))

    config.extend(
        {
            "id": str(experiment_uid),
            "heroku_app_id_root": str(heroku_app_id),
        }
    )

    if not config.get("dashboard_password", None):
        config.set("dashboard_password", fake.password(length=20, special_chars=False))

    temp_dir = assemble_experiment_temp_dir(log, config, for_remote=not local_checks)
    log("Deployment temp directory: {}".format(temp_dir), chevrons=False)

    # Zip up the temporary directory and place it in the cwd.
    if not debug:
        log("Freezing the experiment package...")
        shutil.make_archive(
            os.path.join(os.getcwd(), "snapshots", heroku_app_id + "-code"),
            "zip",
            temp_dir,
        )

    return (heroku_app_id, temp_dir)


def ensure_constraints_file_presence(directory: str):
    """Looks into the path represented by the string `directory`.
    Does nothing if a `constraints.txt` file exists there and is
    newer than a sibling `requirements.txt` file.
    If it exists but is not up to date a ValueError exception is raised.
    Otherwise it creates the constraints.txt file based on the
    contents of the `requirements.txt` file.

    If the `requirements.txt` does not exist one is created with
    `dallinger` as its only dependency.
    """
    constraints_path = Path(directory) / "constraints.txt"
    requirements_path = Path(directory) / "requirements.txt"
    if not requirements_path.exists():
        requirements_path.write_text("dallinger\n")
    requirements_path_hash = md5(requirements_path.read_bytes()).hexdigest()
    if constraints_path.exists():
        if requirements_path_hash in constraints_path.read_text():
            return
        else:
            raise ValueError(
                "\nChanges detected to requirements.txt: run the command\n    dallinger generate-constraints\nand retry"
            )

    prev_cwd = os.getcwd()
    try:
        os.chdir(directory)
        print("Compiling constraints.txt file from requirements.txt")
        compile_info = f"dallinger generate-constraints\n#\n# Compiled from a requirement.txt file with md5sum: {requirements_path_hash}"
        check_output(
            ["pip-compile", "requirements.txt", "-o", "constraints.txt"],
            env=dict(
                os.environ,
                CUSTOM_COMPILE_COMMAND=compile_info,
            ),
        )
    finally:
        os.chdir(prev_cwd)
    # Make the path the experiment requirements.txt file relative
    constraints_contents = constraints_path.read_text()
    constraints_contents_amended = re.sub(
        "via -r .*requirements.txt", "via -r requirements.txt", constraints_contents
    )
    constraints_path.write_text(constraints_contents_amended)


def assemble_experiment_temp_dir(log, config, for_remote=False):
    """Create a temp directory from which to run an experiment.
    If for_remote is set to True the preparation includes bundling
    the local dallinger version if it was installed in editable mode.
    This is always needed for docker debug and deployment, but not needed for
    local Heroku debugging.

    The new directory will include:
    - Copies of custom experiment files which don't match the exclusion policy
    - Templates and static resources from Dallinger
    - An export of the loaded configuration
    - Heroku-specific files (Procile, runtime.txt) from Dallinger
    - A requirements.txt file with the contents from the constraints.txt file
      in the experiment (Dallinger should have generated one with pip-compile
      if needed by the time we reach this code)
    - A dallinger zip (only if dallinger is installed in editable mode)
    - A prepare_docker_image.sh.sh script (possibly empty)

    Assumes the experiment root directory is the current working directory.

    Returns the absolute path of the new directory.
    """
    exp_id = config.get("id")
    dst = os.path.join(tempfile.mkdtemp(), exp_id)

    # Copy local experiment files, minus some
    ExperimentFileSource(os.getcwd()).selective_copy_to(dst)

    # Export the loaded configuration
    config.write(filter_sensitive=True, directory=dst)

    # Save the experiment id
    with open(os.path.join(dst, "experiment_id.txt"), "w") as file:
        file.write(exp_id)

    # Copy Dallinger files
    dallinger_root = dallinger_package_path()
    ensure_directory(os.path.join(dst, "static", "scripts"))
    ensure_directory(os.path.join(dst, "static", "css"))
    frontend_files = [
        os.path.join("static", "css", "bootstrap.min.css"),
        os.path.join("static", "css", "dallinger.css"),
        os.path.join("static", "css", "dashboard.css"),
        os.path.join("static", "scripts", "jquery-3.5.1.min.js"),
        os.path.join("static", "scripts", "popper.min.js"),
        os.path.join("static", "scripts", "bootstrap.min.js"),
        os.path.join("static", "scripts", "clipboard.min.js"),
        os.path.join("static", "scripts", "dallinger2.js"),
        os.path.join("static", "scripts", "network-monitor.js"),
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("static", "scripts", "require.js"),
        os.path.join("static", "scripts", "reconnecting-websocket.js"),
        os.path.join("static", "scripts", "spin.min.js"),
        os.path.join("static", "scripts", "tracker.js"),
        os.path.join("static", "scripts", "store+json2.min.js"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "error-complete.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("templates", "questionnaire.html"),
        os.path.join("templates", "exit_recruiter.html"),
        os.path.join("templates", "exit_recruiter_mturk.html"),
        os.path.join("templates", "waiting.html"),
        os.path.join("templates", "login.html"),
        os.path.join("templates", "dashboard_lifecycle.html"),
        os.path.join("templates", "dashboard_database.html"),
        os.path.join("templates", "dashboard_heroku.html"),
        os.path.join("templates", "dashboard_home.html"),
        os.path.join("templates", "dashboard_monitor.html"),
        os.path.join("templates", "dashboard_mturk.html"),
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

    dst_prepare_docker_image = Path(dst) / "prepare_docker_image.sh"
    if not dst_prepare_docker_image.exists():
        shutil.copyfile(
            Path(dallinger_root) / "docker" / "prepare_docker_image.sh",
            dst_prepare_docker_image,
        )

    ExplicitFileSource(os.getcwd()).selective_copy_to(dst)

    requirements_path = Path(dst) / "requirements.txt"
    # Overwrite the requirements.txt file with the contents of the constraints.txt file
    (Path(dst) / "constraints.txt").replace(requirements_path)
    if for_remote:
        dallinger_path = get_editable_dallinger_path()
        if dallinger_path and not os.environ.get("DALLINGER_NO_EGG_BUILD"):
            log(
                "Dallinger is installed as an editable package, "
                "and so will be copied and deployed in its current state, "
                "ignoring the dallinger version specified in your experiment's "
                "requirements.txt file!\n"
                "If you don't need this you can speed up startup time by setting "
                "the environment variable DALLINGER_NO_EGG_BUILD:\n"
                "    export DALLINGER_NO_EGG_BUILD=1\n"
                "or you can install dallinger without the editable (-e) flag."
            )
            egg_name = build_and_place(dallinger_path, dst)
            # Replace the line about dallinger in requirements.txt so that
            # it refers to the just generated package
            constraints_text = requirements_path.read_text()
            new_constraints_text = re.sub(
                "dallinger==.*", f"file:{egg_name}", constraints_text
            )
            requirements_path.write_text(new_constraints_text)
    return dst


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
        return set(self._walk())

    @property
    def size(self):
        """Combined size of all files, accounting for exclusions."""
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
                normalized = {normalize("NFC", str(f)): f for f in legit_files}
                legit_files = {v for k, v in normalized.items() if k in git_files}
            for legit in legit_files:
                yield legit


class ExplicitFileSource(object):
    """Add files that are explicitly requested by the experimenter with a hook function."""

    def __init__(self, root_dir="."):
        self.root = root_dir

    def _get_mapping(self, dst):
        from dallinger.config import initialize_experiment_package

        initialize_experiment_package(dst)
        from dallinger.experiment import load

        exp_class = load()
        extra_files = getattr(exp_class, "extra_files", None)
        if extra_files is None:
            try:
                from dallinger_experiment.experiment import extra_files
            except ImportError:
                try:
                    from dallinger_experiment.dallinger_experiment import extra_files
                except ImportError:
                    pass

        if extra_files is not None:
            for src, filename in extra_files():
                filename = filename.lstrip("/")
                if os.path.isdir(src):
                    for dirpath, dirnames, filenames in os.walk(src, topdown=True):
                        for fn in filenames:
                            dst_fileparts = (
                                [dst, filename] + [os.path.relpath(dirpath, src)] + [fn]
                            )
                            dst_filepath = os.path.join(*dst_fileparts)
                            yield (
                                os.path.join(dirpath, fn),
                                dst_filepath,
                            )
                else:
                    dst_filepath = os.path.join(dst, filename)
                    yield (src, dst_filepath)

    @property
    def files(self):
        """A Set of all files copyable in the source directory, accounting for
        exclusions.
        """
        return {src for (src, dst) in self._get_mapping("")}

    @property
    def size(self):
        """Combined size of all files, accounting for exclusions."""
        return sum([os.path.getsize(path) for path in self.files])

    def selective_copy_to(self, destination):
        """Write files declared in extra_files from the source directory
        to another directory.
        """
        for from_path, to_path in self._get_mapping(destination):
            target_folder = os.path.dirname(to_path)
            ensure_directory(target_folder)
            shutil.copyfile(from_path, to_path)


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


def build_and_place(source: str, destination: str) -> str:
    """Builds a python egg with the source found at `source` and places it in
    `destination`.
    Only works if dallinger is currently installed in editable mode.

    Returns the full path of the newly created distribution file.
    """
    old_dir = os.getcwd()
    try:
        os.chdir(source)
        check_output(["python", "-m", "build"])
        # The built package is the last addition to the `dist` directory
        package_path = max(Path(source).glob("dist/*"), key=os.path.getctime)
        shutil.copy(package_path, destination)
    finally:
        os.chdir(old_dir)
    return package_path.name


def deferred_route_decorator(route, registered_routes):
    def new_func(func):
        # Check `__func__` in case we have a classmethod or staticmethod
        base_func = getattr(func, "__func__", func)
        name = getattr(base_func, "__name__", None)
        if name is not None:
            route["func_name"] = name
            if route not in registered_routes:
                registered_routes.append(route)
        return func

    return new_func
