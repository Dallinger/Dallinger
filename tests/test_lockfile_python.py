import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "lockfile_python",
    Path(__file__).resolve().parents[1] / "scripts" / "lockfile_python.py",
)
lockfile_python = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lockfile_python)


def test_minimum_python_series_uses_the_lower_bound_minor():
    assert lockfile_python.minimum_python_series(">=3.11") == "3.11"
    assert lockfile_python.minimum_python_series(">=3.11.5") == "3.11"
    assert lockfile_python.minimum_python_series(">= 3.12,<3.15") == "3.12"


def test_minimum_python_series_rejects_a_missing_lower_bound():
    with pytest.raises(ValueError, match="requires-python"):
        lockfile_python.minimum_python_series(">=3")


def test_latest_cpython_patch_ignores_other_interpreters_and_prereleases():
    installations = [
        {"implementation": "cpython", "variant": "default", "version": "3.11.9"},
        {"implementation": "cpython", "variant": "default", "version": "3.11.17"},
        {"implementation": "cpython", "variant": "default", "version": "3.11.18rc1"},
        {"implementation": "pypy", "variant": "default", "version": "3.11.16"},
        {"implementation": "graalpy", "variant": "default", "version": "3.11.0"},
        {"implementation": "cpython", "variant": "freethreaded", "version": "3.11.17"},
        {"implementation": "cpython", "variant": "default", "version": "3.12.1"},
    ]

    assert lockfile_python.latest_cpython_patch("3.11", installations) == "3.11.17"


def test_latest_cpython_patch_reports_a_missing_series():
    with pytest.raises(ValueError, match="CPython 3.11"):
        lockfile_python.latest_cpython_patch("3.11", [])


def test_resolve_lockfile_python_reads_requires_python(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nrequires-python = ">=3.11"\n', encoding="utf-8")
    payload = json.dumps(
        [
            {
                "implementation": "cpython",
                "variant": "default",
                "version": "3.11.17",
            }
        ]
    )

    with patch.object(
        lockfile_python.subprocess, "check_output", return_value=payload
    ) as check_output:
        assert lockfile_python.resolve_lockfile_python(pyproject) == "3.11.17"

    assert check_output.call_args.args[0][3] == "3.11"
