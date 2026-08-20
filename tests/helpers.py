"""Shared helpers for Dallinger tests."""

import json
from pathlib import Path


def write_deployment_policy(root, exclude=()):
    """Write a minimal version 1 ``deploy.toml`` and return its path."""
    values = ", ".join(json.dumps(value) for value in exclude)
    path = Path(root) / "deploy.toml"
    path.write_text(f"version = 1\nexclude = [{values}]\n")
    return path


def write_files(root, files):
    """Write relative text files under ``root``."""
    root = Path(root)
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
