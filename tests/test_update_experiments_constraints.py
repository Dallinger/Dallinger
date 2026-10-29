import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "update_experiments_constraints",
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "update_experiments_constraints.py",
)
update_experiments_constraints = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(update_experiments_constraints)
get_docker_python_version = update_experiments_constraints.get_docker_python_version


def test_docker_python_version_reads_the_repository_dockerfile():
    assert get_docker_python_version().count(".") == 1


def test_docker_python_version_requires_one_version_across_stages(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM python:3.14.1-bookworm as wheels\nFROM python:3.14-slim\n",
        encoding="utf-8",
    )
    assert get_docker_python_version(dockerfile) == "3.14"

    dockerfile.write_text(
        "FROM python:3.14-bookworm as wheels\nFROM python:3.13-bookworm\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match=r"\['3.13', '3.14'\]"):
        get_docker_python_version(dockerfile)

    dockerfile.write_text("FROM ubuntu:24.04\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="none"):
        get_docker_python_version(dockerfile)
