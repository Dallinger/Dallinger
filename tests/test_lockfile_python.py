import importlib.util
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


def test_resolve_lockfile_python_reads_requires_python(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nrequires-python = ">=3.11"\n', encoding="utf-8")

    with patch.object(
        lockfile_python, "latest_cpython_patch", return_value="3.11.17"
    ) as latest:
        assert lockfile_python.resolve_lockfile_python(pyproject) == "3.11.17"

    latest.assert_called_once_with("3.11")
