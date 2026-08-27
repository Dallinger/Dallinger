import json
import os
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from dallinger.command_line import dallinger
from dallinger.command_line.deployment_files import (
    _STARTER_EXCLUDE_NAMES,
    _STARTER_EXCLUDE_PATHS,
    _STARTER_EXCLUDE_SUFFIXES,
    deployment_files,
)
from dallinger.deployment_plan import parse_deployment_policy
from tests.helpers import write_deployment_policy, write_files

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="deployment planning currently requires a POSIX filesystem",
)


def test_list_emits_sorted_destinations_and_summary(tmp_path):
    write_deployment_policy(tmp_path, ["local"])
    write_files(tmp_path, {"a.txt": "a", "m/n.txt": "n", "local/x.txt": "x"})
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        # click isolated_filesystem uses a subdirectory; recreate fixtures there.
        cwd = Path.cwd()
        write_deployment_policy(cwd, ["local"])
        write_files(cwd, {"a.txt": "a", "m/n.txt": "n", "local/x.txt": "x"})
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
        write_deployment_policy(cwd)
        write_files(cwd, {"asset.txt": "x"})
        result = runner.invoke(deployment_files, ["list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["destinations"] == ["asset.txt", "deploy.toml"]
    assert "manifest_digest" not in payload
    assert payload["file_count"] == 2


def test_docs_starter_example_matches_cli_exclusions():
    docs = Path(__file__).resolve().parents[1] / "docs" / "source" / "deploy_toml.rst"
    text = docs.read_text()
    paths = _quoted_toml_array(text, "paths")
    names = _quoted_toml_array(text, "names")
    suffixes = _quoted_toml_array(text, "suffixes")
    assert paths == _STARTER_EXCLUDE_PATHS
    assert names == _STARTER_EXCLUDE_NAMES
    assert suffixes == _STARTER_EXCLUDE_SUFFIXES


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
    assert parsed.exclude_paths == tuple(sorted(_STARTER_EXCLUDE_PATHS))
    assert parsed.exclude_names == tuple(sorted(_STARTER_EXCLUDE_NAMES))
    assert parsed.exclude_suffixes == tuple(sorted(_STARTER_EXCLUDE_SUFFIXES))
    assert "legacy_diff_acknowledgement" not in policy.read_text()
    assert second.exit_code != 0
    assert "Refusing to overwrite" in second.output


def test_list_fails_without_policy(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(deployment_files, ["list"])

    assert result.exit_code == 2
    assert "deploy.toml" in result.output


def test_list_invalid_policy_is_usage_error(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path.cwd().joinpath("deploy.toml").write_text("version = 2\nexclude = []\n")
        result = runner.invoke(deployment_files, ["list"])

    assert result.exit_code == 2
    assert "version" in result.output


def test_deployment_files_group_is_registered():
    runner = CliRunner()
    result = runner.invoke(dallinger, ["deployment-files", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "init" in result.output
    assert "check" not in result.output


def _quoted_toml_array(text, key):
    match = re.search(rf"{re.escape(key)} = \[([^\]]+)\]", text)
    assert match is not None
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))
