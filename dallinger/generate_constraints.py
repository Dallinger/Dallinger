import contextlib
import functools
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
from hashlib import md5
from os import PathLike
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

from dallinger.utils import abspath_from_egg

logger = logging.getLogger(__name__)


def generate_constraints(input_path: PathLike, constraints_path: PathLike):
    dallinger_version = _get_dallinger_version(input_path)
    dallinger_dev_requirements_path = _get_dallinger_dev_requirements_path(
        dallinger_version
    )

    print(
        f"Compiling constraints.txt file from {input_path} and {dallinger_dev_requirements_path}"
    )
    compile_info = f"dallinger generate-constraints\n#\n# Compiled from a {Path(input_path).name} file with md5sum: {_hash_input_file(input_path)}"

    with TemporaryDirectory() as tmpdirname:
        tmpfile = Path(tmpdirname) / "requirements.txt"
        tmpfile.write_text(
            Path("requirements.txt").read_text()
            + "\n-c "
            + dallinger_dev_requirements_path
        )
        _check_output(
            [
                "pip-compile",
                "-v",
                str(tmpfile),
                "-o",
                str(constraints_path),
            ],
            env=dict(
                os.environ,
                CUSTOM_COMPILE_COMMAND=compile_info,
            ),
        )

    _make_paths_relative(constraints_path)


def ensure_constraints_file_presence(directory: str):
    """Looks into the path represented by the string `directory`.
    Does nothing if a `constraints.txt` file exists there and contains
    the same md5sum as the `requirements.txt` file.
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

    input_path = _find_input_path(directory)
    constraints_path = Path(directory) / "constraints.txt"

    if constraints_path.exists():
        _assert_constraints_up_to_date(constraints_path, input_path)
        return

    generate_constraints(input_path, constraints_path)


def _find_input_path(directory: str) -> Path:
    requirements_path = Path(directory) / "requirements.txt"
    pyproject_path = Path(directory) / "pyproject.toml"

    if requirements_path.exists():
        input_path = requirements_path
    elif pyproject_path.exists():
        input_path = pyproject_path
    else:
        logger.warning(
            "No requirements.txt or pyproject.toml file found, will autogenerate a requirements.txt"
        )
        requirements_path.write_text("dallinger\n")
        input_path = requirements_path

    return input_path


def _hash_input_file(input_path: PathLike) -> str:
    with open(input_path, "rb") as f:
        return md5(f.read()).hexdigest()


def _constraints_up_to_date(constraints_path: Path, input_path: Path) -> bool:
    return _hash_input_file(input_path) in constraints_path.read_text()


def _assert_constraints_up_to_date(constraints_path: Path, input_path: Path):
    if not _constraints_up_to_date(constraints_path, input_path):
        raise ValueError(
            "\nChanges detected to requirements.txt: run the command\n    dallinger generate-constraints\nand retry"
        )


def _get_dallinger_version(input_path: PathLike) -> str:
    explicit_version = _get_explicit_dallinger_version(input_path)
    if explicit_version:
        return explicit_version
    else:
        return _get_implied_dallinger_version(input_path)


def _get_explicit_dallinger_version(input_path: PathLike) -> str | None:
    """Extract the Dallinger version string from a file.

    Parameters
    ----------
    input_path : Path
        Path to the file to search.

    Returns
    -------
    str
        The extracted version string (e.g., '10.2.1'), or None if not found.
    """
    version = _get_explicit_dallinger_release_version(input_path)
    if version:
        return version
    else:
        return _get_explicit_dallinger_github_requirement(input_path)


def _get_explicit_dallinger_release_version(input_path: PathLike) -> str | None:
    pattern = re.compile(r"dallinger==([0-9]+\.[0-9]+\.[0-9]+)")
    with open(input_path, "r") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                return match.group(1)
    return None


def _get_explicit_dallinger_github_requirement(input_path: PathLike) -> str | None:
    # dallinger@git+https://github.com/Dallinger/Dallinger.git@my-branch#egg=dallinger
    pattern = re.compile(
        r"dallinger@git\+https:\/\/github\.com\/Dallinger\/Dallinger(?:\.git)?@([^\s#]+)(?:#.*)?"
    )
    with open(input_path, "r") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                return match.group(1)
    return None


def _get_implied_dallinger_version(input_path: PathLike) -> str:
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmpfile:
        _check_output(
            [
                "pip-compile",
                "-v",
                str(input_path),
                "-o",
                str(tmpfile),
            ],
        )
        retrieved = _get_explicit_dallinger_version(tmpfile.name)
    if retrieved is None:
        raise ValueError(
            f"Failed to retrieve an implied Dallinger version from {input_path}. "
            "Consider specifying Dallinger explicitly ."
        )
    return retrieved


def _get_dallinger_dev_requirements_path(dallinger_version: str) -> str:
    url = f"https://raw.githubusercontent.com/Dallinger/Dallinger/v{dallinger_version}/dev-requirements.txt"
    try:
        response = requests.get(url, timeout=10)
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            """It looks like you're offline. Dallinger can't generate constraints
To get a valid constraints.txt file you can copy the requirements.txt file:
cp requirements.txt constraints.txt"""
        ) from e
    if response.status_code != 200:
        print(f"{url} not found. Using local dev-requirements.txt")
        url_path = abspath_from_egg("dallinger", "dev-requirements.txt")
        if not url_path.exists():
            print(
                f"{url_path} is not a valid file. Either use a released dallinger version for this experiment or install dallinger in editable mode"
            )
            raise ValueError(
                f"Can't find constraints for dallinger version {dallinger_version}"
            )
        url = str(url_path)
    return url


def _make_paths_relative(constraints_path: Path):
    constraints_contents = constraints_path.read_text()
    constraints_contents_amended = re.sub(
        "via -r .*requirements.txt", "via -r requirements.txt", constraints_contents
    )
    constraints_path.write_text(constraints_contents_amended)


@contextlib.contextmanager
def working_directory(path):
    start_dir = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(start_dir)


def _wrap_subprocess_call(func, wrap_stdout=True):
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


_check_call = _wrap_subprocess_call(subprocess.check_call)  # noqa
_call = _wrap_subprocess_call(subprocess.call)  # noqa
_check_output = _wrap_subprocess_call(
    subprocess.check_output, wrap_stdout=False
)  # noqa
