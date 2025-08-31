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
from importlib.metadata import files as files_metadata
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def generate_constraints(input_path, output_path):
    """
    Generate a constraints.txt file for the current directory.

    The process takes as a starting point the contents of the input_path file,
    and relates this to the dev-requirements.txt file for the requested Dallinger version.
    This dev-requirements.txt file is sourced from the Dallinger GitHub repository,
    paying attention to the precise version of Dallinger that is requested by input_path.

    ``uv pip compile`` is used if uv is available, otherwise ``pip-compile`` is used.

    Parameters
    ----------
    input_path : str
        The path to the input file, typically requirements.txt or pyproject.toml.
    output_path : str
        The path to the output file, typically constraints.txt.
    """
    dallinger_reference = _get_dallinger_reference(input_path)
    dallinger_dev_requirements_path = _get_dallinger_dev_requirements_path(
        dallinger_reference
    )
    _test_dallinger_dev_requirements_path(dallinger_dev_requirements_path)

    print(
        f"Compiling constraints.txt file from {input_path} and {dallinger_dev_requirements_path}"
    )
    compile_info = f"dallinger generate-constraints\n#\n# Compiled from a {Path(input_path).name} file with md5sum: {_hash_input_file(input_path)}"

    _pip_compile(
        input_path,
        output_path,
        constraints=[dallinger_dev_requirements_path],
        compile_info=compile_info,
    )

    _make_paths_relative(output_path)


def ensure_constraints_file_presence(directory: str):
    """
    Ensures that a ``constraints.txt`` file exists in the directory.

    This ``constraints.txt`` is generated from an input file,
    either ``requirements.txt`` (default) or pyproject.toml
    (if neither are present, a ``requirements.txt`` file is created with
    ``dallinger`` as its only dependency).

    The generated ``constraints.txt`` file contains the MD5 hash of the input file.
    If ``ensure_constraints_file_presence`` is called when a ``constraints.txt`` file
    already exists, then it is checked to see whether it contains the same MD5 hash
    as the input file. If it does, then no action is taken. If it does not, then a
    ``ValueError`` is raised.

    If the environment variable SKIP_DEPENDENCY_CHECK is set, no action
    will be performed.
    """
    if os.environ.get("SKIP_DEPENDENCY_CHECK"):
        return

    input_path = _find_input_path(directory)
    output_path = Path(directory) / "constraints.txt"

    if output_path.exists():
        _assert_constraints_up_to_date(output_path, input_path)
        return

    generate_constraints(input_path, output_path)


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


def _hash_input_file(input_path: Path) -> str:
    with open(input_path, "rb") as f:
        return md5(f.read()).hexdigest()


def _constraints_up_to_date(constraints_path: Path, input_path: Path) -> bool:
    return _hash_input_file(input_path) in constraints_path.read_text()


def _assert_constraints_up_to_date(constraints_path: Path, input_path: Path):
    if not _constraints_up_to_date(constraints_path, input_path):
        raise ValueError(
            "\nChanges detected to requirements.txt: run the command\n    dallinger generate-constraints\nand retry"
        )


def _get_dallinger_reference(input_path: Path) -> str:
    explicit_reference = _get_explicit_dallinger_reference(input_path)
    if explicit_reference:
        return explicit_reference
    else:
        return _get_implied_dallinger_reference(input_path)


def _get_explicit_dallinger_reference(input_path: Path) -> str | None:
    release = _get_explicit_dallinger_numbered_release(input_path)
    if release:
        return f"v{release}"
    else:
        return _get_explicit_dallinger_github_requirement(input_path)


def _get_explicit_dallinger_numbered_release(input_path: Path) -> str | None:
    # Should catch patterns like dallinger[docker,test]==11.5.0
    pattern = re.compile(r"dallinger(?:\[[^\]]+\])?==([0-9]+\.[0-9]+\.[0-9]+)")
    with open(input_path, "r") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                return match.group(1)
    return None


def _get_explicit_dallinger_github_requirement(input_path: Path) -> str | None:
    # dallinger@git+https://github.com/Dallinger/Dallinger.git@my-branch#egg=dallinger
    pattern = re.compile(
        r"dallinger@git\+https://github\.com/Dallinger/Dallinger(?:\.git)?@([^\s#]+)(?:#.*)?"
    )
    with open(input_path, "r") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                return match.group(1)
    return None


def _get_implied_dallinger_reference(input_path: Path) -> str:
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmpfile:
        _pip_compile(input_path, tmpfile.name, constraints=None)
        retrieved = _get_explicit_dallinger_reference(Path(tmpfile.name))
        if retrieved is None:
            raise ValueError(
                f"Failed to retrieve an implied Dallinger reference from {input_path}. "
                "Consider specifying Dallinger explicitly in the requirements.txt file."
            )
    return retrieved


def _get_dallinger_dev_requirements_path(dallinger_reference: str) -> str:
    return f"https://raw.githubusercontent.com/Dallinger/Dallinger/{dallinger_reference}/dev-requirements.txt"


def _test_dallinger_dev_requirements_path(url: str):
    try:
        response = requests.get(url, timeout=10)
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            """It looks like you're offline. Dallinger can't generate constraints
To get a valid constraints.txt file you can copy the requirements.txt file:
cp requirements.txt constraints.txt"""
        ) from e
    if response.status_code != 200:
        raise ValueError(
            f"{url} not found. Please make sure your specified Dallinger "
            "version exists in the Dallinger repository. "
        )


def _pip_compile(
    in_file, out_file, constraints: Optional[list] = None, compile_info=None
):
    use_uv = uv_available()
    if use_uv:
        logger.info("Calling `uv pip-compile`...")
        cmd = ["uv", "pip", "compile"]
    else:
        logger.info(
            "Calling `pip-compile` (consider installing uv for faster compilation)..."
        )
        cmd = ["pip-compile"]
    cmd += [
        # "--verbose",
        str(in_file),
        "--output-file",
        str(out_file),
    ]
    if constraints:
        for constraint in constraints:
            cmd += ["--constraint", constraint]

    env = dict(os.environ)
    if compile_info:
        if use_uv:
            env["UV_CUSTOM_COMPILE_COMMAND"] = compile_info
        else:
            env["CUSTOM_COMPILE_COMMAND"] = compile_info
    _check_output(
        cmd,
        env=env,
    )


def uv_available() -> bool:
    """
    Check whether uv is available for use.
    """
    # return False
    try:
        _check_output(["uv", "--version"])
        return True
    except subprocess.CalledProcessError:
        return False


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


if __name__ == "__main__":
    directory = Path.cwd()
    input_path = _find_input_path(directory)
    output_path = directory / "constraints.txt"
    generate_constraints(input_path, output_path)
