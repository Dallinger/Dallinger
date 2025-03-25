from __future__ import unicode_literals

import functools
import io
import locale
import logging
import os
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
import webbrowser
from hashlib import md5
from importlib.metadata import files as files_metadata
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unicodedata import normalize

import requests
from faker import Faker
from flask import request
from pythonjsonlogger import jsonlogger

from dallinger import db
from dallinger.compat import is_command
from dallinger.config import get_config
from dallinger.version import __version__

try:
    from pip._vendor import pkg_resources
except ImportError:
    pkg_resources = None

fake = Faker()

JSON_LOGFILE = "logs.jsonl"


def attach_json_logger(log):
    fmt = jsonlogger.JsonFormatter(
        "%(name)s %(asctime)s %(levelname)s %(filename)s %(lineno)s %(message)s"
    )
    handler = logging.FileHandler(JSON_LOGFILE)
    handler.setFormatter(fmt)
    log.addHandler(handler)


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
    return os.path.dirname(find_spec("dallinger").origin)


def generate_random_id(size=6, chars=string.ascii_uppercase + string.digits):
    """Generate random id numbers."""
    return "".join(random.choice(chars) for x in range(size))


def ensure_directory(path):
    """Create a matching path if it does not already exist"""
    if not os.path.exists(path):
        os.makedirs(path)


def expunge_directory(path_string):
    """Remove all content from a directory."""
    for filepath in Path(path_string).iterdir():
        try:
            if filepath.is_file() or filepath.is_symlink():
                filepath.unlink()
            elif filepath.is_dir():
                shutil.rmtree(filepath)
        except Exception as e:
            print("Failed to delete %s. Reason: %s" % (filepath, e))


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
        "--user-data-dir={}".format(profile_directory),
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
    parts = []
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
                value = f'<span class="statistics-value all-failures">{value}</span>'
            elif failed_percentage > 0:
                value = f'<span class="statistics-value some-failures">{value}</span>'
            elif data["count"]:
                value = f'<span class="statistics-value no-failures">{value}</span>'
            return value

        for k in data:
            item = struct_to_html(data[k])
            parts.append(
                f'<span class="nowrap"><span class="statistics-key">{k}</span>: <span class="statistics-value">{item}</span></span>'
            )
    else:
        return str(data)

    return "<br>".join(parts)


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
            return open(egg_link).readlines()[0].strip()
    return None


def check_local_db_connection(log):
    """Verify that the local Postgres server is running."""
    try:
        log("Checking your local Postgres database connection...")
        db.check_connection()
    except Exception:
        log("There was a problem connecting!")
        raise


def check_experiment_dependencies(requirements_file):
    """Verify that the dependencies defined in a requirements file are
    in fact installed.
    If the environment variable SKIP_DEPENDENCY_CHECK is set, no check
    will be performed.
    """
    if os.environ.get("SKIP_DEPENDENCY_CHECK"):
        return
    try:
        with open(requirements_file, "r") as f:
            dependencies = [
                re.split("@|\\ |>|<|=|\\[", line)[0].strip()
                for line in f.readlines()
                if line[:3] != "-e " and line[0].strip() not in ["#", ""]
            ]
    except (OSError, IOError):
        dependencies = []

    for dep in dependencies:
        if find_spec(dep) is None:
            try:
                pkg_resources.get_distribution(dep)
            except (pkg_resources.DistributionNotFound, AttributeError):
                raise ValueError(
                    f"Please install the '{dep}' package to run this experiment."
                )


def develop_target_path(config):
    """Extract the target `dallinger develop` working directory from
    configuration, and return it as a Path.
    """
    develop_path_string = config.get("dallinger_develop_directory", None)
    try:
        develop_path = Path(develop_path_string).expanduser()
    except TypeError:
        raise ValueError(
            'The Dallinger configuration value "dallinger_develop_directory" '
            'must be a file path, like "~/dallinger_develop".\n'
            'Your value is "{}" which cannot be translated '
            "to a file path.".format(develop_path_string)
        )
    if not develop_path.name.isidentifier():
        raise ValueError(
            'The directory in the Dallinger configuration value "dallinger_develop_directory" '
            "must be a valid python identifier: only letters, numbers and underscores are allowed.\n"
            'The directory name "{}" is not a valid identifier.'.format(
                develop_path.name
            )
        )

    return develop_path


def bootstrap_development_session(exp_config, experiment_path, log):
    check_local_db_connection(log)
    check_experiment_dependencies(Path(experiment_path) / "requirements.txt")

    # Generate a unique id for this experiment.
    from dallinger.experiment import Experiment

    experiment_uid = Experiment.make_uuid()
    log("Experiment UID: {}".format(experiment_uid))

    # Load and update the config
    config = get_config()
    if not config.ready:
        config.load()  #
    config.extend(exp_config)
    config.extend(
        {
            "id": str(experiment_uid),
            "heroku_app_id_root": str(experiment_uid),
        }
    )
    if not config.get("dashboard_password", None):
        config.set("dashboard_password", fake.password(length=20, special_chars=False))

    source_path = Path(dallinger_package_path()) / "dev_server"
    destination_path = develop_target_path(config)

    log("Wiping develop directory and re-writing it...")
    ensure_directory(destination_path)
    expunge_directory(destination_path)
    collate_experiment_files(
        config,
        experiment_path=experiment_path,
        destination=destination_path,
        copy_func=symlink_file,
    )

    copy_file(source_path / "app.py", destination_path / "app.py")
    copy_file(source_path / "run.sh", destination_path / "run.sh")
    (destination_path / "run.sh").chmod(0o744)  # Make run script executable

    config.write(directory=destination_path)

    return (experiment_uid, destination_path)


def setup_experiment(
    log, debug=True, verbose=False, app=None, exp_config=None, local_checks=True
):
    """Checks the experiment's python dependencies, then prepares a temp directory
    with files merged from the custom experiment and Dallinger.

    The resulting directory includes all the files necessary to deploy to
    Heroku.
    """
    if local_checks:
        check_local_db_connection(log)
        check_experiment_dependencies(Path(os.getcwd()) / "requirements.txt")

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

    If the environment variable SKIP_DEPENDENCY_CHECK is set, no action
    will be performed.
    """
    if os.environ.get("SKIP_DEPENDENCY_CHECK"):
        return
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
        url = f"https://raw.githubusercontent.com/Dallinger/Dallinger/v{__version__}/dev-requirements.txt"
        try:
            response = requests.get(url)
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                """It looks like you're offline. Dallinger can't generate constraints
To get a valid constraints.txt file you can copy the requirements.txt file:
cp requirements.txt constraints.txt"""
            )
        if response.status_code != 200:
            print(f"{url} not found. Using local dev-requirements.txt")
            url_path = abspath_from_egg("dallinger", "dev-requirements.txt")
            if not url_path.exists():
                print(
                    f"{url_path} is not a valid file. Either use a released dallinger version for this experiment or install dallinger in editable mode"
                )
                raise ValueError(
                    "Can't find constraints for dallinger version {__version__}"
                )
            url = str(url_path)
        print(f"Compiling constraints.txt file from requirements.txt and {url}")
        compile_info = f"dallinger generate-constraints\n#\n# Compiled from a requirement.txt file with md5sum: {requirements_path_hash}"
        with TemporaryDirectory() as tmpdirname:
            tmpfile = Path(tmpdirname) / "requirements.txt"
            tmpfile.write_text(Path("requirements.txt").read_text() + "\n-c " + url)
            check_output(
                [
                    "pip-compile",
                    "-v",
                    str(tmpfile),
                    "-o",
                    "constraints.txt",
                ],
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
    collate_experiment_files(
        config, experiment_path=os.getcwd(), destination=dst, copy_func=copy_file
    )

    # Write out the loaded configuration
    config.write(filter_sensitive=True, directory=dst)

    # Write out the experiment id
    with open(os.path.join(dst, "experiment_id.txt"), "w") as file:
        file.write(exp_id)

    # Write out a runtime.txt file based on configuration
    pyversion = config.get("heroku_python_version", None)
    if pyversion:
        with open(os.path.join(dst, "runtime.txt"), "w") as file:
            file.write("python-{}".format(pyversion))

    requirements_path = Path(dst) / "requirements.txt"
    # Overwrite the requirements.txt file with the contents of the constraints.txt file
    if not os.environ.get("SKIP_DEPENDENCY_CHECK"):
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


def copy_file(from_path, to_path):
    """Actually copy a file from one location to another."""
    shutil.copyfile(from_path, to_path)


def symlink_file(from_path, to_path):
    """Symbolically link a file from one location to another."""
    os.symlink(from_path, to_path)


def collate_experiment_files(config, experiment_path, destination, copy_func):
    """Coordinates getting required files from various sources into a
    target directory.
    """
    # Order matters here, since the first files copied "win" if there's a
    # collision:
    ExperimentFileSource(experiment_path).apply_to(destination, copy_func=copy_func)
    ExplicitFileSource(experiment_path).apply_to(destination, copy_func=copy_func)
    DallingerFileSource(config, dallinger_package_path()).apply_to(
        destination, copy_func=copy_func
    )


class FileSource(object):
    """Include files from some source in an experiment run."""

    @property
    def files(self):
        """A Set of all files copyable in the source directory, accounting for
        exclusions.
        """
        return {src for (src, dst) in self.map_locations_to("")}

    @property
    def size(self):
        """Combined size of all files, accounting for exclusions."""
        return sum(
            [os.path.getsize(path) for path in self.files if not os.path.islink(path)]
        )

    def apply_to(self, destination, copy_func=copy_file):
        """Copy files based iterable of source and destination tuples.
        Files are not overwritten if they already exist.
        """
        for from_path, to_path in self.map_locations_to(destination):
            target_folder = os.path.dirname(to_path)
            ensure_directory(target_folder)
            if os.path.exists(to_path):
                continue
            copy_func(from_path, to_path)

    def map_locations_to(self, destination):
        """Return a generator of two-tuples, where the first element is
        the source file path, and the second is the corresponding path in the
        target location under @dst.
        """
        raise NotImplementedError()


class DallingerFileSource(FileSource):
    """The core Dallinger framework is a source for files to be used in an
    experiment run. These include the /frontend directory contents,
    a Heroku Procfile, and a Docker script.
    """

    def __init__(self, config, root_dir="."):
        self.config = config
        self.root = os.path.abspath(root_dir)

    def map_locations_to(self, dst):
        src = os.path.join(self.root, "frontend")
        for dirpath, dirnames, filenames in os.walk(src, topdown=True):
            for fn in filenames:
                dst_fileparts = (dst, os.path.relpath(dirpath, src), fn)
                dst_filepath = os.path.join(*dst_fileparts)
                yield (
                    os.path.join(dirpath, fn),
                    dst_filepath,
                )

        # Heroku Procfile
        if self.config.get("clock_on"):
            clock_src = os.path.join(self.root, "heroku", "Procfile")
            yield (clock_src, os.path.join(dst, "Procfile"))
        else:
            # If the clock process has been disabled, overwrite the Procfile:
            clock_src = os.path.join(self.root, "heroku", "Procfile_no_clock")
            yield (clock_src, os.path.join(dst, "Procfile"))

        # Docker image file
        scriptname = "prepare_docker_image.sh"
        docker_src = os.path.join(self.root, "docker", scriptname)
        dst_prepare_docker_image = os.path.join(dst, scriptname)

        yield (docker_src, dst_prepare_docker_image)


class ExperimentFileSource(FileSource):
    """Treat an experiment directory as a potential source of files for
    copying to a temp directory as part of a deployment (debug or otherwise).
    """

    def __init__(self, root_dir="."):
        self.root = os.path.abspath(root_dir)
        self.git = GitClient()

    def map_locations_to(self, dst):
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
                fn = os.path.basename(legit)
                dst_fileparts = [dst, os.path.relpath(legit, self.root)]
                dst_filepath = os.path.join(*dst_fileparts)
                yield (
                    os.path.join(dirpath, fn),
                    dst_filepath,
                )


class ExplicitFileSource(FileSource):
    """Add files that are explicitly requested by the experimenter with a hook function."""

    def __init__(self, root_dir="."):
        self.root = root_dir

    def map_locations_to(self, dst):
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
                                os.path.abspath(os.path.join(dirpath, fn)),
                                os.path.abspath(dst_filepath),
                            )
                else:
                    dst_filepath = os.path.join(dst, filename)
                    yield (os.path.abspath(src), os.path.abspath(dst_filepath))


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
            "local_only",
            "node_modules",
            "snapshots",
            "data",
            "develop",
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


def route_name_from_func_name(func_name: str) -> str:
    return func_name


def deferred_route_decorator(
    route, registered_routes, rename_route_name=route_name_from_func_name
):
    def new_func(func):
        # Check `__func__` in case we have a classmethod or staticmethod
        base_func = getattr(func, "__func__", func)
        func_name = getattr(base_func, "__name__", None)
        if func_name is not None:
            route["func_name"] = func_name
            route["name"] = rename_route_name(func_name)
            if route not in registered_routes:
                registered_routes.append(route)
        return func

    return new_func


def get_from_config(key):
    config = get_config()
    if not config.ready:
        config.load()
    return config.get(key)


class ClassPropertyDescriptor(object):
    def __init__(self, fget, fset=None):
        self.fget = fget
        self.fset = fset

    def __get__(self, obj, cls=None):
        if cls is None:
            cls = type(obj)
        return self.fget.__get__(obj, cls)()

    def __set__(self, obj, value):
        if not self.fset:
            raise AttributeError("can't set attribute")
        type_ = type(obj)
        return self.fset.__get__(obj, type_)(value)

    def setter(self, func):
        if not isinstance(func, (classmethod, staticmethod)):
            func = classmethod(func)
        self.fset = func
        return self


def classproperty(func):
    """
    Defines an analogous version of @property but for classes,
    after https://stackoverflow.com/questions/5189699/how-to-make-a-class-property.
    """
    if not isinstance(func, (classmethod, staticmethod)):
        func = classmethod(func)

    return ClassPropertyDescriptor(func)
