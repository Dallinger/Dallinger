import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import dallinger.deployment_plan as deployment_plan_module
from dallinger.command_line import dallinger
from dallinger.command_line.deployment_files import deployment_files

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="deployment planning currently requires a POSIX filesystem",
)


def _write_policy(root: Path, exclude=(), acknowledgement=None, comments=False):
    lines = ["# policy heading"] if comments else []
    lines.append("version = 1 # schema" if comments else "version = 1")
    if acknowledgement is not None:
        lines.append(f'legacy_diff_acknowledgement = "{acknowledgement}"')
    values = ", ".join(json.dumps(value) for value in exclude)
    lines.append(f"exclude = [{values}]" + (" # exclusions" if comments else ""))
    (root / "deploy.toml").write_text("\n".join(lines) + "\n")


def _write_files(root: Path, files: dict[str, str]):
    for relative, contents in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)


def _init_git(root: Path):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def _invoke(root: Path, args: list[str]):
    with CliRunner().isolated_filesystem(temp_dir=root.parent):
        os.chdir(root)
        return CliRunner().invoke(deployment_files, args)


def _invoke_registered(root: Path, args: list[str]):
    with CliRunner().isolated_filesystem(temp_dir=root.parent):
        os.chdir(root)
        return CliRunner().invoke(dallinger, ["deployment-files", *args])


def test_list_is_deterministic_and_supports_json(tmp_path):
    root = tmp_path / "experiment"
    root.mkdir()
    _write_policy(root)
    _write_files(root, {"z.txt": "z", "nested/b.txt": "b", "a.txt": "a"})

    human = _invoke(root, ["list"])
    machine = _invoke(root, ["list", "--json"])

    assert human.exit_code == 0
    assert human.output.splitlines()[:4] == [
        "a.txt",
        "deploy.toml",
        "nested/b.txt",
        "z.txt",
    ]
    payload = json.loads(machine.output)
    assert payload["destinations"] == [
        "a.txt",
        "deploy.toml",
        "nested/b.txt",
        "z.txt",
    ]
    assert payload["file_count"] == 4
    assert payload["manifest_digest"].startswith("sha256:")
    assert "root" not in payload


@pytest.mark.parametrize("args", [["list"], ["list", "--json"]])
def test_list_rejects_format_controls_with_unspoofable_diagnostics(tmp_path, args):
    _write_policy(tmp_path)
    unsafe_name = "report\u202egnp.exe"
    (tmp_path / unsafe_name).write_text("content")

    result = _invoke(tmp_path, args)

    assert result.exit_code != 0
    assert "\u202e" not in result.output
    assert "\\u202e" in result.output


def test_check_reports_included_excluded_and_json_without_contents(tmp_path):
    _init_git(tmp_path)
    _write_policy(tmp_path, exclude=["excluded.txt"])
    _write_files(
        tmp_path,
        {
            ".gitignore": "ignored.txt\n",
            "ignored.txt": "DO NOT PRINT THIS SECRET",
            "excluded.txt": "excluded",
        },
    )

    result = _invoke(tmp_path, ["check", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["newly_included"] == [
        {"path": "ignored.txt", "type": "regular-file"}
    ]
    assert payload["newly_excluded"] == [
        {"path": "excluded.txt", "type": "regular-file"}
    ]
    digest = payload["acknowledgement"]["digest"]
    assert digest.startswith("sha256:")
    assert payload["acknowledgement"] == {
        "configured": None,
        "digest": digest,
        "matches": False,
        "required": True,
    }
    assert "compatibility_digest" not in payload
    assert "DO NOT PRINT THIS SECRET" not in result.output


def test_check_prints_manual_acknowledgement_and_detects_invalidation(tmp_path):
    _init_git(tmp_path)
    _write_policy(tmp_path, comments=True)
    _write_files(tmp_path, {".gitignore": "*.secret\n", "first.secret": "first"})
    policy_path = tmp_path / "deploy.toml"
    original_policy = policy_path.read_bytes()

    missing = _invoke(tmp_path, ["check"])
    payload = json.loads(_invoke(tmp_path, ["check", "--json"]).output)
    digest = payload["acknowledgement"]["digest"]

    assert missing.exit_code == 1
    assert "Acknowledgement: missing" in missing.output
    assert f'legacy_diff_acknowledgement = "{digest}"' in missing.output
    assert policy_path.read_bytes() == original_policy

    _write_policy(tmp_path, acknowledgement=digest, comments=True)
    matching = _invoke(tmp_path, ["check"])
    (tmp_path / "second.secret").write_text("second")
    invalidated = _invoke(tmp_path, ["check"])

    assert matching.exit_code == 0
    assert "Acknowledgement: matches" in matching.output
    assert invalidated.exit_code == 1
    assert "Acknowledgement: mismatch" in invalidated.output


def test_acknowledgement_covers_exclusion_only_difference(tmp_path):
    _init_git(tmp_path)
    required_input = tmp_path / "required-input.txt"
    required_input.write_text("tracked ordinary input")
    subprocess.run(["git", "add", "required-input.txt"], cwd=tmp_path, check=True)
    _write_policy(tmp_path, exclude=["required-input.txt"])
    policy_path = tmp_path / "deploy.toml"
    original_policy = policy_path.read_bytes()

    unreviewed = _invoke(tmp_path, ["check", "--json"])
    payload = json.loads(unreviewed.output)

    assert unreviewed.exit_code == 1
    assert payload["newly_included"] == []
    assert payload["newly_excluded"] == [
        {"path": "required-input.txt", "type": "regular-file"}
    ]
    assert payload["acknowledgement"]["required"] is True
    assert policy_path.read_bytes() == original_policy

    _write_policy(
        tmp_path,
        exclude=["required-input.txt"],
        acknowledgement=payload["acknowledgement"]["digest"],
    )
    reviewed = _invoke(tmp_path, ["check"])
    assert reviewed.exit_code == 0
    assert "Acknowledgement: matches" in reviewed.output


def test_init_reports_untranslated_rules_and_refuses_overwrite(tmp_path):
    _init_git(tmp_path)
    (tmp_path / ".gitignore").write_bytes(b"\xff\xfe")

    created = _invoke(tmp_path, ["init"])
    original = (tmp_path / "deploy.toml").read_bytes()
    repeated = _invoke(tmp_path, ["init"])

    assert created.exit_code == 0
    assert "Git ignore patterns were not translated" in created.output
    assert "Legacy recursive basename rules were not translated" in created.output
    assert "*.db, *.dmg, data, node_modules" in created.output
    assert "reorganize" in created.output
    assert "manually add or update" in created.output
    assert "commit deploy.toml" in created.output
    assert "version = 1" in original.decode()
    assert '"node_modules"' in original.decode()
    assert repeated.exit_code != 0
    assert "Refusing to overwrite" in repeated.output
    assert (tmp_path / "deploy.toml").read_bytes() == original


@pytest.mark.parametrize(
    "policy_contents, expected",
    [
        (None, "Cannot inspect deployment policy"),
        ("version = 1\nexclude = [\n", "Invalid TOML"),
    ],
)
def test_list_and_check_refuse_missing_or_invalid_policy(
    tmp_path, policy_contents, expected
):
    _init_git(tmp_path)
    if policy_contents is not None:
        (tmp_path / "deploy.toml").write_text(policy_contents)

    listed = _invoke(tmp_path, ["list"])
    checked = _invoke(tmp_path, ["check"])

    assert listed.exit_code != 0
    assert expected in listed.output
    assert checked.exit_code != 0
    assert expected in checked.output


def test_check_distinguishes_git_failure(tmp_path, monkeypatch):
    _init_git(tmp_path)
    _write_policy(tmp_path)
    monkeypatch.setattr(
        deployment_plan_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=128, stdout=b"", stderr=b"failure"
        ),
    )

    result = _invoke(tmp_path, ["check"])

    assert result.exit_code != 0
    assert "Legacy Git file selection failed" in result.output
    assert "exit status 128" in result.output
    assert "Newly included" not in result.output


def test_check_blocks_unresolved_backend_ignore_controls(tmp_path):
    _init_git(tmp_path)
    _write_policy(tmp_path)
    _write_files(
        tmp_path,
        {
            ".dockerignore": "DO NOT PRINT",
            "Dockerfile.production.dockerignore": "DO NOT PRINT",
            "nested/.slugignore": "DO NOT PRINT",
        },
    )
    original_policy = (tmp_path / "deploy.toml").read_bytes()

    checked = _invoke(tmp_path, ["check", "--json"])
    human = _invoke(tmp_path, ["check"])

    assert checked.exit_code == 1
    payload = json.loads(checked.output)
    assert payload["backend_filters"] == {
        "paths": [
            ".dockerignore",
            "Dockerfile.production.dockerignore",
            "nested/.slugignore",
        ],
        "status": "unsafe/unresolved",
    }
    assert "DO NOT PRINT" not in checked.output
    assert human.exit_code != 0
    assert "Migrate their filtering into deploy.toml" in human.output
    assert (tmp_path / "deploy.toml").read_bytes() == original_policy


def test_check_has_no_acknowledge_option(tmp_path):
    _write_policy(tmp_path)

    result = _invoke(tmp_path, ["check", "--acknowledge"])

    assert result.exit_code == 2
    assert "No such option '--acknowledge'" in result.output


def test_group_is_registered_and_runs_list_on_main_cli(tmp_path):
    _write_policy(tmp_path)
    (tmp_path / "example.txt").write_text("example")

    result = _invoke_registered(tmp_path, ["list", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["destinations"] == [
        "deploy.toml",
        "example.txt",
    ]
