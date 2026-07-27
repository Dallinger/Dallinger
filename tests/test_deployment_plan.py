import json
import os
import unicodedata
from pathlib import Path

import pytest

import dallinger.deployment_plan as deployment_plan
from dallinger.deployment_plan import (
    DeploymentPlanError,
    DeploymentPolicyError,
    build_deployment_plan,
    parse_deployment_policy,
    validate_explicit_provider_destination,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="deployment planning currently requires a POSIX filesystem",
)


def write_policy(root: Path, exclude=()) -> Path:
    values = ", ".join(json.dumps(value) for value in exclude)
    path = root / "deploy.toml"
    path.write_text(f"version = 1\nexclude = [{values}]\n")
    return path


def write_files(root: Path, files: dict[str, str]) -> None:
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_parse_valid_policy_normalizes_and_sorts_exclusions(tmp_path):
    decomposed = unicodedata.normalize("NFD", "café")
    policy = parse_deployment_policy(write_policy(tmp_path, ["z/data", decomposed]))

    assert policy.version == 1
    assert policy.exclude == ("café", "z/data")


@pytest.mark.parametrize(
    "contents, message",
    [
        ("exclude = []\n", "version"),
        ("version = 1\n", "exclude"),
        ('version = 1\nexclude = []\nextra = "x"\n', "Unknown"),
        ("version = 2\nexclude = []\n", "version"),
        ("version = true\nexclude = []\n", "version"),
        ('version = 1\nexclude = "data"\n', "array of strings"),
        ("version = 1\nexclude = [1]\n", "array of strings"),
        (
            "version = 1\nexclude = []\nlegacy_diff_acknowledgement = "
            f'"sha256:{"a" * 64}"\n',
            "Unknown",
        ),
    ],
)
def test_parse_rejects_unknown_missing_version_and_invalid_types(
    tmp_path, contents, message
):
    path = tmp_path / "deploy.toml"
    path.write_text(contents)

    with pytest.raises(DeploymentPolicyError, match=message):
        parse_deployment_policy(path)


@pytest.mark.parametrize(
    "excluded",
    [
        "",
        "/absolute",
        "has\\slash",
        "!negated",
        "glob*",
        "a//b",
        ".",
        "..",
        "deploy.toml",
        ".git",
        "config.txt",
        ".dockerignore",
    ],
)
def test_parse_rejects_nonliteral_or_unsafe_paths(tmp_path, excluded):
    with pytest.raises(DeploymentPolicyError):
        parse_deployment_policy(write_policy(tmp_path, [excluded]))


def test_parse_rejects_duplicate_normalized_paths(tmp_path):
    decomposed = unicodedata.normalize("NFD", "café")
    with pytest.raises(DeploymentPolicyError, match="Duplicate"):
        parse_deployment_policy(write_policy(tmp_path, ["café", decomposed]))


def test_explicit_provider_rejects_reserved_destination_prefixes():
    with pytest.raises(DeploymentPlanError, match="reserved"):
        validate_explicit_provider_destination("config.txt")
    with pytest.raises(DeploymentPlanError, match="reserved"):
        validate_explicit_provider_destination(".dockerignore")


def test_explicit_provider_allows_nested_config_and_normalizes_nfc():
    decomposed = unicodedata.normalize("NFD", "café")
    assert (
        validate_explicit_provider_destination(f"nested/{decomposed}/file.txt")
        == "nested/café/file.txt"
    )


def test_parse_rejects_symlinked_policy(tmp_path):
    target = tmp_path / "policy.toml"
    target.write_text("version = 1\nexclude = []\n")
    (tmp_path / "deploy.toml").symlink_to(target)

    with pytest.raises(DeploymentPolicyError, match="symbolic link"):
        parse_deployment_policy(tmp_path / "deploy.toml")


def test_plan_is_sorted_and_independent_of_creation_order(tmp_path):
    write_policy(tmp_path)
    write_files(tmp_path, {"z.txt": "z", "a.txt": "a", "m/n.txt": "n"})

    plan = build_deployment_plan(tmp_path)

    assert [entry.destination for entry in plan.entries] == [
        "a.txt",
        "deploy.toml",
        "m/n.txt",
        "z.txt",
    ]


def test_plan_applies_literal_prefixes_allows_missing_and_includes_policy(tmp_path):
    write_policy(tmp_path, ["static/private", "missing"])
    write_files(
        tmp_path,
        {
            "static/private/secret.txt": "excluded descendant",
            "static/public/asset.txt": "included",
        },
    )

    plan = build_deployment_plan(tmp_path)

    assert plan.destinations == {"deploy.toml", "static/public/asset.txt"}
    assert "deploy.toml" in plan
    assert "static/private/secret.txt" not in plan
    assert plan.total_size == sum(entry.size for entry in plan.entries)


def test_plan_omits_reserved_source_paths(tmp_path):
    write_policy(tmp_path)
    write_files(
        tmp_path,
        {
            "config.txt": "raw secret",
            ".git/objects/example": "metadata",
            ".dockerignore": "*",
            "Dockerfile.production.dockerignore": "*",
            ".slugignore": "*",
            "nested/config.txt": "ordinary nested file",
            ".gitignore": "*.secret",
        },
    )

    plan = build_deployment_plan(tmp_path)

    assert plan.destinations == {
        ".gitignore",
        "deploy.toml",
        "nested/config.txt",
    }


def test_plan_records_entry_metadata_and_membership(tmp_path):
    write_policy(tmp_path)
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)

    plan = build_deployment_plan(tmp_path)
    entry = next(item for item in plan.entries if item.destination == "run.sh")

    assert entry.source == script
    assert entry.size == script.stat().st_size
    assert entry.executable is True
    assert entry.mode & 0o111
    assert entry.source_category == "experiment"
    assert "run.sh" in plan


def test_plan_records_only_fully_selected_directory_link_candidates(tmp_path):
    write_policy(tmp_path, ["mixed/private"])
    write_files(
        tmp_path,
        {
            "complete/first.txt": "first",
            "complete/nested/second.txt": "second",
            "mixed/private/secret.txt": "secret",
            "mixed/public/visible.txt": "visible",
        },
    )

    plan = build_deployment_plan(tmp_path)
    candidates = {
        candidate.destination: candidate for candidate in plan.directory_link_candidates
    }

    assert "complete" in candidates
    assert "complete/nested" in candidates
    assert "mixed" not in candidates
    assert "mixed/public" in candidates
    complete = candidates["complete"]
    assert tuple(
        entry.destination
        for entry in plan.entries[complete.entry_start : complete.entry_stop]
    ) == ("complete/first.txt", "complete/nested/second.txt")


def test_plan_rejects_selected_symlink_but_prunes_excluded_symlink(tmp_path):
    write_policy(tmp_path, ["excluded-link"])
    target = tmp_path / "target.txt"
    target.write_text("target")
    (tmp_path / "excluded-link").symlink_to(target)
    selected = tmp_path / "selected-link"
    selected.symlink_to(target)

    with pytest.raises(DeploymentPlanError, match="Symbolic links"):
        build_deployment_plan(tmp_path)

    selected.unlink()
    assert "excluded-link" not in build_deployment_plan(tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_plan_rejects_special_files(tmp_path):
    write_policy(tmp_path)
    os.mkfifo(tmp_path / "events.fifo")

    with pytest.raises(DeploymentPlanError, match="FIFO"):
        build_deployment_plan(tmp_path)


def test_plan_rejects_nested_repositories(tmp_path):
    write_policy(tmp_path)
    marker = tmp_path / "vendor" / ".git"
    marker.parent.mkdir()
    marker.mkdir()

    with pytest.raises(DeploymentPlanError, match="Nested repository"):
        build_deployment_plan(tmp_path)


def test_plan_fails_closed_on_non_posix_platforms(tmp_path, monkeypatch):
    monkeypatch.setattr(deployment_plan.os, "name", "nt")

    with pytest.raises(DeploymentPlanError, match="POSIX"):
        build_deployment_plan(tmp_path)


def test_exclusion_lookup_checks_ancestors():
    exclusions = frozenset({"static/private"})
    assert deployment_plan._is_excluded(("static", "private", "x"), exclusions)
    assert not deployment_plan._is_excluded(("static", "public", "x"), exclusions)
    assert deployment_plan._has_exclusion_at_or_below(("static",), exclusions)
    assert not deployment_plan._has_exclusion_at_or_below(("other",), exclusions)
