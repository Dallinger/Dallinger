import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from dallinger.command_line import dallinger
from dallinger.command_line.deployment_files import deployment_files
from dallinger.deployment_plan import parse_deployment_policy

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="deployment planning currently requires a POSIX filesystem",
)


def _write_policy(root: Path, exclude=()):
    values = ", ".join(json.dumps(value) for value in exclude)
    (root / "deploy.toml").write_text(f"version = 1\nexclude = [{values}]\n")


def _write_files(root: Path, files: dict[str, str]):
    for relative, contents in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)


def test_list_emits_sorted_destinations_and_summary(tmp_path):
    _write_policy(tmp_path, ["local"])
    _write_files(tmp_path, {"a.txt": "a", "m/n.txt": "n", "local/x.txt": "x"})
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        # click isolated_filesystem uses a subdirectory; recreate fixtures there.
        cwd = Path.cwd()
        _write_policy(cwd, ["local"])
        _write_files(cwd, {"a.txt": "a", "m/n.txt": "n", "local/x.txt": "x"})
        result = runner.invoke(deployment_files, ["list"])

    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert lines[:-1] == ["a.txt", "deploy.toml", "m/n.txt"]
    assert "3 files" in lines[-1]
    assert "manifest" not in result.output


def test_list_json_omits_manifest_digest(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        cwd = Path.cwd()
        _write_policy(cwd)
        _write_files(cwd, {"asset.txt": "x"})
        result = runner.invoke(deployment_files, ["list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["destinations"] == ["asset.txt", "deploy.toml"]
    assert "manifest_digest" not in payload
    assert payload["file_count"] == 2


def test_init_creates_starter_policy_once(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        first = runner.invoke(deployment_files, ["init"])
        second = runner.invoke(deployment_files, ["init"])
        policy = Path.cwd() / "deploy.toml"

    assert first.exit_code == 0
    assert policy.is_file()
    parsed = parse_deployment_policy(policy)
    assert parsed.version == 1
    assert parsed.exclude[:2] == (".deploy", ".env")
    assert "legacy_diff_acknowledgement" not in policy.read_text()
    assert second.exit_code != 0
    assert "Refusing to overwrite" in second.output


def test_list_fails_without_policy(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(deployment_files, ["list"])

    assert result.exit_code != 0


def test_deployment_files_group_is_registered():
    runner = CliRunner()
    result = runner.invoke(dallinger, ["deployment-files", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "init" in result.output
    assert "check" not in result.output
