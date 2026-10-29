#!/usr/bin/env python3
"""
This script is used to update the constraints.txt files in the demos directory
when preparing a new Dallinger release.

The script reads the Dallinger version from dallinger/version.py and uses it to
reference the correct GitHub tag (e.g., v12.0.0) in the constraint files.

Each experiment's .python-version is set to the Python minor version of the root
Dockerfile, the image that deployed experiments run on, and the constraints are
compiled for that version. The interpreter running this script does not matter.

Note 1: you should make sure that you have pushed the latest version of your branch
before running this script, so that GitHub's hosted dev-requirements.txt file is up to date.

Note 2: generated constraints used to look like this:

ansi2html==1.9.2
    # via
    #   -c ../../../../dev-requirements.txt
    #   dallinger

They now look like this:

ansi2html==1.9.2
    # via
    #   -c https://raw.githubusercontent.com/Dallinger/Dallinger/v12.1.0/dev-requirements.txt
    #   dallinger

The original format was neater, but the advantage of the latter is that it is consistent
with what the user will get if they run `dallinger constraints generate` themselves.

The compile calls ``generate_constraints(upgrade=True)``. Packages pinned by
Dallinger's dev requirements stay at those pins. Every other package in the
experiment lock, including dependencies named only in the experiment's
requirements such as NLTK, moves to the newest version that requirements file
allows.
"""
# This was originally a shell script, but for better cross-platform support
# we've now ported it to Python.

import hashlib
import os
import re
import subprocess
from pathlib import Path

import dallinger
from dallinger.constraints import generate_constraints, working_directory

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMOS_DIR = REPO_ROOT / "demos" / "dlgr" / "demos"
# The test experiment's constraints.txt is a committed fixture; regenerate it
# alongside the demos so it does not drift from the released dependency pins.
TEST_EXPERIMENT_DIR = REPO_ROOT / "tests" / "experiment"


def get_docker_python_version():
    """Return the Python minor version (e.g. ``3.14``) of Dallinger's Docker image."""
    dockerfile = REPO_ROOT / "Dockerfile"
    match = re.search(
        r"^FROM python:(\d+\.\d+)\b", dockerfile.read_text(), flags=re.MULTILINE
    )
    if match is None:
        raise RuntimeError(f"Could not find a 'FROM python:X.Y' line in {dockerfile}")
    return match.group(1)


def write_python_version_file(demo_dir, python_version):
    # Note: we only constrain to the level of minor version to minimize the friction
    # of upgrading to Python patch versions.
    file = demo_dir / ".python-version"
    file.write_text(f"{python_version}\n", encoding="utf-8")


def md5_cmd(filepath):
    """Return the md5 hash of a file."""
    with open(filepath, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def get_current_branch():
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    return result.stdout.strip()


def get_dallinger_version():
    return dallinger.version.__version__


def replace_in_file(path, pattern, repl):
    text = path.read_text()
    new_text = re.sub(pattern, repl, text, flags=re.MULTILINE)
    path.write_text(new_text)


def refresh_experiment_constraints(demo_dir):
    """Recompile one experiment's constraints, including its extra dependencies.

    ``upgrade=True`` refreshes packages that are not part of Dallinger's own lock.
    """
    with working_directory(demo_dir):
        generate_constraints(upgrade=True)


def main():
    os.chdir(REPO_ROOT)
    current_branch = get_current_branch()
    dallinger_version = get_dallinger_version()
    version_tag = f"v{dallinger_version}"
    python_version = get_docker_python_version()
    print(f"Current branch: {current_branch}")
    print(f"Dallinger version: {dallinger_version}")
    print(f"Using version tag: {version_tag}")
    print(f"Python version (from Dockerfile): {python_version}")

    experiment_dirs = [
        path for path in sorted(DEMOS_DIR.iterdir()) if path.is_dir()
    ] + [TEST_EXPERIMENT_DIR]
    for demo_dir in experiment_dirs:
        config_txt = demo_dir / "config.txt"
        requirements_txt = demo_dir / "requirements.txt"
        constraints_txt = demo_dir / "constraints.txt"
        if not config_txt.exists():
            continue
        print(f"Compiling {demo_dir.name}")
        # 0. Update .python-version
        write_python_version_file(demo_dir, python_version)
        # 1. Replace dallinger with github requirement in requirements.txt (using current branch)
        if requirements_txt.exists():
            req_text = requirements_txt.read_text()
            github_req = (
                f"dallinger@git+https://github.com/Dallinger/Dallinger@{current_branch}"
            )
            new_req_text = re.sub(
                r"^dallinger$", github_req, req_text, flags=re.MULTILINE
            )
            requirements_txt.write_text(new_req_text)
        # 2. Run constraints generator (using current branch for GitHub reference)
        refresh_experiment_constraints(demo_dir)
        # 3. Remove extras from constraints.txt
        con_text = constraints_txt.read_text()
        # Remove extras: [something== to ==
        con_text = re.sub(r"\[.*==", "==", con_text)
        constraints_txt.write_text(con_text)
        # 4. Revert requirements.txt change
        req_text = requirements_txt.read_text()
        req_text = re.sub(
            rf"^dallinger@git\+https://github.com/Dallinger/Dallinger@{current_branch}$",
            "dallinger",
            req_text,
            flags=re.MULTILINE,
        )
        requirements_txt.write_text(req_text)
        # 5. Update constraints.txt to use released dallinger version
        con_text = constraints_txt.read_text()
        # Replace dallinger github reference with version
        con_text = re.sub(
            r"^dallinger @ git\+https://github.com/Dallinger/Dallinger@.*$",
            f"dallinger=={dallinger_version}",
            con_text,
            flags=re.MULTILINE,
        )
        # Replace branch reference with version tag in constraint URLs
        con_text = re.sub(
            rf"https://raw\.githubusercontent\.com/Dallinger/Dallinger/{re.escape(current_branch)}/",
            f"https://raw.githubusercontent.com/Dallinger/Dallinger/{version_tag}/",
            con_text,
        )
        constraints_txt.write_text(con_text)


if __name__ == "__main__":
    main()
