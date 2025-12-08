#!/usr/bin/env python3
"""
This script is used to update the constraints.txt files in the demos directory
when preparing a new Dallinger release.

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
"""
# This was originally a shell script, but for better cross-platform support
# we've now ported it to Python.

import hashlib
import os
import platform
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMOS_DIR = REPO_ROOT / "demos" / "dlgr" / "demos"
CONSTRAINTS_SCRIPT = REPO_ROOT / "dallinger" / "constraints.py"


def write_python_version_file(demo_dir):
    # Note: we only constrain to the level of minor version to minimize the friction
    # of upgrading to Python patch versions.
    file = demo_dir / ".python-version"
    version = platform.python_version_tuple()
    major = version[0]
    minor = version[1]
    file.write_text(f"{major}.{minor}\n", encoding="utf-8")


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
    result = subprocess.run(
        ["dallinger", "--version"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    return result.stdout.strip()


def replace_in_file(path, pattern, repl):
    text = path.read_text()
    new_text = re.sub(pattern, repl, text, flags=re.MULTILINE)
    path.write_text(new_text)


def main():
    os.chdir(REPO_ROOT)
    current_branch = get_current_branch()
    dallinger_version = get_dallinger_version()
    print(f"Current branch: {current_branch}")
    print(f"Dallinger version: {dallinger_version}")

    for demo_dir in DEMOS_DIR.iterdir():
        if not demo_dir.is_dir():
            continue
        config_txt = demo_dir / "config.txt"
        requirements_txt = demo_dir / "requirements.txt"
        constraints_txt = demo_dir / "constraints.txt"
        if not config_txt.exists():
            continue
        print(f"Compiling {demo_dir.name}")
        # 0. Update .python-version
        write_python_version_file(demo_dir)
        # 1. Replace dallinger with github requirement in requirements.txt
        if requirements_txt.exists():
            req_text = requirements_txt.read_text()
            github_req = (
                f"dallinger@git+https://github.com/Dallinger/Dallinger@{current_branch}"
            )
            new_req_text = re.sub(
                r"^dallinger$", github_req, req_text, flags=re.MULTILINE
            )
            requirements_txt.write_text(new_req_text)
        # 2. Run constraints generator
        subprocess.run(
            ["uv", "run", str(CONSTRAINTS_SCRIPT), "generate"], cwd=demo_dir, check=True
        )
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
        con_text = re.sub(
            r"^dallinger @ git\+https://github.com/Dallinger/Dallinger@.*$",
            f"dallinger=={dallinger_version}",
            con_text,
            flags=re.MULTILINE,
        )
        constraints_txt.write_text(con_text)


if __name__ == "__main__":
    main()
