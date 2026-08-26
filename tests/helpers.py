"""Shared helpers for Dallinger tests."""

import json
from pathlib import Path


def write_deployment_policy(root, exclude=(), exclude_anywhere=None):
    """Write a minimal version 1 ``deploy.toml`` and return its path."""
    lines = [
        "version = 1",
        f"exclude = [{_toml_string_array(exclude)}]",
    ]
    if exclude_anywhere is not None:
        lines.append(f"exclude_anywhere = [{_toml_string_array(exclude_anywhere)}]")
    path = Path(root) / "deploy.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def _toml_string_array(values):
    """Format values as a TOML inline string array body."""
    return ", ".join(json.dumps(value) for value in values)


def write_files(root, files):
    """Write relative text files under ``root``."""
    root = Path(root)
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
