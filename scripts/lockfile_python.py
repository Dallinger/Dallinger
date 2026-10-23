"""Choose the Python version used to compile Dallinger's lockfiles.

``uv pip compile --python-version 3.11`` resolves as Python 3.11.0. The
lockfiles have to install on the oldest supported Python line, so the compile
target is the latest CPython patch of that line.
"""

import json
import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_LOWER_BOUND = re.compile(r">=\s*(\d+)\.(\d+)")
_RELEASE = re.compile(r"\d+\.\d+\.\d+")


def minimum_python_series(requires_python: str) -> str:
    """Return the ``major.minor`` series from a ``requires-python`` lower bound."""
    match = _LOWER_BOUND.search(requires_python)
    if match is None:
        raise ValueError(
            "requires-python must include a minimum version such as >=3.11, "
            f"got {requires_python!r}"
        )
    return f"{match.group(1)}.{match.group(2)}"


def latest_cpython_patch(series: str, installations: list) -> str:
    """Return the newest CPython patch in *series* from ``uv python list`` JSON."""
    versions = []
    prefix = f"{series}."
    for row in installations:
        if row.get("implementation") != "cpython":
            continue
        if row.get("variant") not in (None, "default"):
            continue
        version = row.get("version") or ""
        if not version.startswith(prefix) or _RELEASE.fullmatch(version) is None:
            continue
        versions.append(tuple(int(part) for part in version.split(".")))
    if not versions:
        raise ValueError(f"uv did not report a CPython {series} patch release")
    return ".".join(str(part) for part in max(versions))


def resolve_lockfile_python(pyproject_path: Path = REPO_ROOT / "pyproject.toml") -> str:
    """Return the latest CPython patch of the oldest Python this project supports."""
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    requires_python = project["project"]["requires-python"]
    series = minimum_python_series(requires_python)
    raw = subprocess.check_output(
        [
            "uv",
            "python",
            "list",
            series,
            "--all-versions",
            "--output-format",
            "json",
        ],
        text=True,
    )
    return latest_cpython_patch(series, json.loads(raw))


def main() -> None:
    print(resolve_lockfile_python())


if __name__ == "__main__":
    main()
