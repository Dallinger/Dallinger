import hashlib
import json
import os
import subprocess
import unicodedata
from pathlib import Path

import pytest

import dallinger.deployment_plan as deployment_plan
from dallinger.deployment_plan import (
    DeploymentCompatibilityError,
    DeploymentMembership,
    DeploymentPlanError,
    DeploymentPolicyError,
    _ExclusionIndex,
    _is_excluded,
    acknowledge_legacy_deployment_comparison,
    build_deployment_plan,
    compare_legacy_deployment_selection,
    compute_legacy_compatibility_digest,
    parse_deployment_policy,
)

SAFE_DESCRIPTOR_PLATFORM = (
    os.name == "posix"
    and hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)
pytestmark = pytest.mark.skipif(
    not SAFE_DESCRIPTOR_PLATFORM,
    reason="deployment planning requires safe POSIX descriptor traversal",
)


def write_policy(root: Path, exclude=(), acknowledgement=None) -> Path:
    lines = ["version = 1"]
    if acknowledgement is not None:
        lines.append(f"legacy_diff_acknowledgement = {json.dumps(acknowledgement)}")
    values = ", ".join(json.dumps(value) for value in exclude)
    lines.append(f"exclude = [{values}]")
    path = root / "deploy.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def write_files(root: Path, files: dict[str, str]) -> None:
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_parse_valid_policy_normalizes_and_sorts_exclusions(tmp_path):
    decomposed = unicodedata.normalize("NFD", "café")
    acknowledgement = "sha256:" + "A1" * 32
    policy = parse_deployment_policy(
        write_policy(
            tmp_path,
            ["z/data", decomposed],
            acknowledgement=acknowledgement,
        )
    )

    assert policy.version == 1
    assert policy.exclude == ("café", "z/data")
    assert policy.legacy_diff_acknowledgement == acknowledgement.lower()


@pytest.mark.parametrize(
    "contents, message",
    [
        ("exclude = []\n", "version"),
        ("version = 1\n", "exclude"),
        (
            'version = 1\nlegacy_diff_acknowledgement = "sha256:value"\n',
            "exclude",
        ),
        ('version = 1\nexclude = []\nextra = "x"\n', "Unknown"),
        ("version = 2\nexclude = []\n", "version"),
        ("version = true\nexclude = []\n", "version"),
        ('version = 1\nexclude = "data"\n', "array of strings"),
        ("version = 1\nexclude = [1]\n", "array of strings"),
        (
            "version = 1\nexclude = []\nlegacy_diff_acknowledgement = 1\n",
            "64 hexadecimal",
        ),
        (
            'version = 1\nexclude = []\nlegacy_diff_acknowledgement = "sha256:123"\n',
            "64 hexadecimal",
        ),
        (
            f'version = 1\nexclude = []\nlegacy_diff_acknowledgement = "md5:{"a" * 64}"\n',
            "64 hexadecimal",
        ),
        (
            f'version = 1\nexclude = []\nlegacy_diff_acknowledgement = """sha256:{"a" * 64}"""\n',
            "Multiline TOML strings",
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
        ".",
        "..",
        "a/./b",
        "a/../b",
        "a//b",
        "a/",
        "/absolute",
        "C:relative",
        "C:/absolute",
        r"folder\file",
        "file*",
        "file?",
        "file[0]",
        "{one,two}",
        "!included",
        "nul\x00name",
        "control\x1fname",
        "format\u202ename",
        "name:stream",
        'bad"name',
        "trailing.",
        "trailing ",
        "CON",
        "com1.txt",
        "Lpt9",
    ],
)
def test_parse_rejects_nonliteral_or_unsafe_paths(tmp_path, excluded):
    with pytest.raises(DeploymentPolicyError):
        parse_deployment_policy(write_policy(tmp_path, [excluded]))


@pytest.mark.parametrize(
    "exclusions",
    [
        ["same", "same"],
        ["café", unicodedata.normalize("NFD", "café")],
        ["Readme", "README"],
    ],
)
def test_parse_rejects_normalized_and_portable_duplicates(tmp_path, exclusions):
    with pytest.raises(DeploymentPolicyError, match="Duplicate|collide"):
        parse_deployment_policy(write_policy(tmp_path, exclusions))


@pytest.mark.parametrize(
    "reserved",
    [
        "deploy.toml",
        "config.txt",
        ".git",
        "vendor/.git",
        ".dockerignore",
        "Dockerfile.production.dockerignore",
        ".slugignore",
        "DEPLOY.TOML",
        "CONFIG.TXT",
        "vendor/.GIT",
        "Dockerfile.DOCKERIGNORE",
        ".SLUGIGNORE",
    ],
)
def test_parse_rejects_excluding_required_or_reserved_paths(tmp_path, reserved):
    with pytest.raises(DeploymentPolicyError, match="required or reserved"):
        parse_deployment_policy(write_policy(tmp_path, [reserved]))


def test_parse_rejects_symlinked_policy(tmp_path):
    target = tmp_path / "policy-target.toml"
    target.write_text("version = 1\nexclude = []\n")
    (tmp_path / "deploy.toml").symlink_to(target)

    with pytest.raises(DeploymentPolicyError, match="symbolic link"):
        parse_deployment_policy(tmp_path / "deploy.toml")


def test_plan_is_sorted_and_independent_of_creation_order(tmp_path):
    roots = [tmp_path / "first", tmp_path / "second"]
    file_orders = [
        {"z.txt": "z", "nested/b.txt": "b", "a.txt": "a"},
        {"a.txt": "a", "nested/b.txt": "b", "z.txt": "z"},
    ]
    plans = []
    for root, files in zip(roots, file_orders):
        root.mkdir()
        write_policy(root)
        write_files(root, files)
        plans.append(build_deployment_plan(root))

    expected = ["a.txt", "deploy.toml", "nested/b.txt", "z.txt"]
    assert [[entry.destination for entry in plan.entries] for plan in plans] == [
        expected,
        expected,
    ]
    assert plans[0].manifest_digest == plans[1].manifest_digest
    assert (
        plans[0].manifest_digest
        == "sha256:5096e17c6b50d1c789b82c3a4219068c67d070e2bfc5ffadca261e708a876341"
    )


def test_plan_treats_ignored_tracked_and_untracked_files_equally(tmp_path):
    write_policy(tmp_path)
    write_files(
        tmp_path,
        {
            ".gitignore": "ignored.txt\n",
            "ignored.txt": "ignored",
            "tracked.txt": "tracked",
            "untracked.txt": "untracked",
        },
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)

    plan = build_deployment_plan(tmp_path)

    assert plan.destinations == {
        ".gitignore",
        "deploy.toml",
        "ignored.txt",
        "tracked.txt",
        "untracked.txt",
    }


def test_plan_applies_literal_prefixes_allows_missing_and_includes_policy(tmp_path):
    write_policy(tmp_path, ["cache", "static/private", "missing"])
    write_files(
        tmp_path,
        {
            "cache": "excluded exact file",
            "static/private/secret.txt": "excluded descendant",
            "static/public/asset.txt": "included",
        },
    )

    plan = build_deployment_plan(tmp_path)

    assert plan.destinations == {"deploy.toml", "static/public/asset.txt"}
    assert "deploy.toml" in plan
    assert "static/private/secret.txt" not in plan
    assert plan.total_size == sum(entry.size for entry in plan.entries)


def test_plan_policy_entry_uses_the_parsed_descriptor_snapshot(tmp_path, monkeypatch):
    policy_path = write_policy(tmp_path)
    original_bytes = policy_path.read_bytes()
    original_scandir = os.scandir
    replaced = False

    def replace_policy_before_walk(path):
        nonlocal replaced
        if not replaced:
            replaced = True
            policy_path.write_text('version = 1\nexclude = ["later"]\n')
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", replace_policy_before_walk)
    plan = build_deployment_plan(tmp_path)
    policy_entry = next(
        entry for entry in plan.entries if entry.destination == "deploy.toml"
    )

    assert plan.policy.exclude == ()
    assert policy_entry.content_digest == (
        "sha256:" + hashlib.sha256(original_bytes).hexdigest()
    )
    assert policy_entry.source_identity != deployment_plan.SourceIdentity.from_stat(
        policy_path.stat()
    )


def test_plan_omits_reserved_source_paths(tmp_path):
    write_policy(tmp_path)
    write_files(
        tmp_path,
        {
            "CONFIG.TXT": "raw secret",
            ".GIT/objects/example": "metadata",
            ".hg/store/example": "metadata",
            ".svn/entries": "metadata",
            ".DOCKERIGNORE": "*",
            "Dockerfile.production.DOCKERIGNORE": "*",
            "docker/custom.DockerIgnore": "*",
            ".SLUGIGNORE": "*",
            "nested/.SlugIgnore": "*",
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


@pytest.mark.parametrize(
    "name",
    [
        "name:stream",
        "CON.txt",
        "trailing.",
        "trailing ",
        "control\x1fname",
        "format\u202ename",
    ],
)
def test_plan_rejects_nonportable_source_components(tmp_path, name):
    write_policy(tmp_path)
    (tmp_path / name).write_text("content")

    with pytest.raises(DeploymentPlanError, match="unsupported|must not end"):
        build_deployment_plan(tmp_path)


def test_format_control_diagnostic_escapes_spoofing_character(tmp_path):
    write_policy(tmp_path)
    name = "report\u202egnp.exe"
    (tmp_path / name).write_text("content")

    with pytest.raises(DeploymentPlanError) as captured:
        build_deployment_plan(tmp_path)

    message = str(captured.value)
    assert "\u202e" not in message
    assert "\\u202e" in message
    json_diagnostic = json.dumps({"error": message}, ensure_ascii=False)
    assert "\u202e" not in json_diagnostic
    assert "\\\\u202e" in json_diagnostic


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
    assert entry.source_identity.inode == script.stat().st_ino
    assert entry.content_digest.startswith("sha256:")
    assert entry.source_category == "experiment"
    assert "run.sh" in plan
    assert Path("run.sh") not in plan


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
    assert "mixed/private" not in candidates
    assert "mixed/public" in candidates
    complete = candidates["complete"]
    assert complete.source == tmp_path / "complete"
    assert complete.source_identity.inode == (tmp_path / "complete").stat().st_ino
    assert tuple(
        entry.destination
        for entry in plan.entries[complete.entry_start : complete.entry_stop]
    ) == ("complete/first.txt", "complete/nested/second.txt")
    assert complete.entry_count == 2


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


def test_plan_rejects_symlink_in_experiment_root_ancestor(tmp_path):
    real_parent = tmp_path / "real"
    root = real_parent / "experiment"
    root.mkdir(parents=True)
    write_policy(root)
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(DeploymentPlanError, match="safely open"):
        build_deployment_plan(alias / "experiment")


def test_plan_contains_directory_replacement_with_symlink(tmp_path, monkeypatch):
    write_policy(tmp_path)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "inside.txt").write_text("inside")
    outside = tmp_path.with_name(f"{tmp_path.name}-outside")
    outside.mkdir()
    (outside / "outside.txt").write_text("outside")
    moved = tmp_path / "moved"
    original_open_child = deployment_plan._open_child_directory
    replaced = False

    def replace_before_directory_open(parent_descriptor, name, source, expected_stat):
        nonlocal replaced
        if name == "nested" and not replaced:
            replaced = True
            nested.rename(moved)
            nested.symlink_to(outside, target_is_directory=True)
        return original_open_child(parent_descriptor, name, source, expected_stat)

    monkeypatch.setattr(
        deployment_plan, "_open_child_directory", replace_before_directory_open
    )
    with pytest.raises(DeploymentPlanError, match="safely open deployment directory"):
        build_deployment_plan(tmp_path)


def test_plan_detects_file_mutation_while_hashing(tmp_path, monkeypatch):
    write_policy(tmp_path)
    source = tmp_path / "large.bin"
    source.write_bytes(b"a" * (2 * 1024 * 1024))
    source_inode = source.stat().st_ino
    original_read = os.read
    mutated = False

    def mutate_after_first_block(descriptor, size):
        nonlocal mutated
        block = original_read(descriptor, size)
        if not mutated and block and os.fstat(descriptor).st_ino == source_inode:
            mutated = True
            source.write_bytes(b"changed")
        return block

    monkeypatch.setattr(os, "read", mutate_after_first_block)
    with pytest.raises(DeploymentPlanError, match="changed while being hashed"):
        build_deployment_plan(tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_plan_rejects_special_files(tmp_path):
    write_policy(tmp_path)
    os.mkfifo(tmp_path / "events.fifo")

    with pytest.raises(DeploymentPlanError, match="FIFO"):
        build_deployment_plan(tmp_path)


@pytest.mark.parametrize("marker_type", ["directory", "file"])
def test_plan_rejects_nested_repositories_and_submodules(tmp_path, marker_type):
    write_policy(tmp_path)
    marker = tmp_path / "vendor" / ".git"
    marker.parent.mkdir()
    if marker_type == "directory":
        marker.mkdir()
    else:
        marker.write_text("gitdir: ../.git/modules/vendor\n")

    with pytest.raises(DeploymentPlanError, match="Nested repository or submodule"):
        build_deployment_plan(tmp_path)


@pytest.mark.parametrize(
    "first, second",
    [
        ("Readme", "README"),
        ("café", unicodedata.normalize("NFD", "café")),
    ],
)
def test_plan_rejects_portable_destination_collisions(tmp_path, first, second):
    write_policy(tmp_path)
    (tmp_path / first).write_text("first")
    (tmp_path / second).write_text("second")

    with pytest.raises(DeploymentPlanError, match="collide|normalize"):
        build_deployment_plan(tmp_path)


def test_plan_fails_closed_without_supported_posix_primitives(tmp_path, monkeypatch):
    monkeypatch.setattr(deployment_plan.os, "name", "nt")

    with pytest.raises(DeploymentPlanError, match="Windows/reparse-point"):
        build_deployment_plan(tmp_path)


def test_exclusion_lookup_scales_with_path_depth():
    class CountingExclusions(set):
        checks = 0

        def __contains__(self, value):
            self.checks += 1
            return super().__contains__(value)

    exclusions = CountingExclusions({f"unrelated/{number}" for number in range(1_000)})
    exclusions.add("static/private")

    assert _is_excluded(("static", "private", "asset.txt"), exclusions)
    assert exclusions.checks == 2


def test_descendant_exclusion_lookup_scales_logarithmically():
    class CountingPath(str):
        comparisons = 0

        def __lt__(self, other):
            type(self).comparisons += 1
            return super().__lt__(other)

    exclusions = [
        CountingPath(f"excluded-{number:05}/private") for number in range(4_096)
    ]
    index = _ExclusionIndex(exclusions)
    CountingPath.comparisons = 0

    for number in range(2_000):
        assert not index.has_at_or_below((f"included-{number:05}",))

    assert CountingPath.comparisons < 60_000


def test_plan_digest_is_stable_and_changes_with_content_or_mode(tmp_path):
    write_policy(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("first")
    first = build_deployment_plan(tmp_path)

    os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 1))
    touched = build_deployment_plan(tmp_path)
    assert touched.manifest_digest == first.manifest_digest

    source.write_text("second")
    changed_content = build_deployment_plan(tmp_path)
    assert changed_content.manifest_digest != first.manifest_digest
    first_entry = next(
        entry for entry in first.entries if entry.destination == "source.txt"
    )
    changed_entry = next(
        entry for entry in changed_content.entries if entry.destination == "source.txt"
    )
    assert changed_entry.content_digest != first_entry.content_digest

    source.chmod(0o755)
    changed_mode = build_deployment_plan(tmp_path)
    assert changed_mode.manifest_digest != changed_content.manifest_digest


def test_legacy_compatibility_digest_is_canonical_and_versioned():
    newly_included = [
        DeploymentMembership("ignored.txt", "regular-file"),
        DeploymentMembership("ignored.txt", "regular-file"),
    ]
    newly_excluded = [DeploymentMembership("required.txt", "regular-file")]

    digest = compute_legacy_compatibility_digest(
        newly_included=reversed(newly_included),
        newly_excluded=reversed(newly_excluded),
    )

    assert (
        digest
        == "sha256:1c3f9a4214139a1c1c2f93612eefaf82841009777892b6451684ee25038e44a3"
    )
    assert digest != compute_legacy_compatibility_digest(
        newly_included=newly_excluded,
        newly_excluded=newly_included,
    )


def test_zero_difference_has_stable_digest_without_requiring_acknowledgement(
    tmp_path,
):
    write_policy(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    comparison = compare_legacy_deployment_selection(build_deployment_plan(tmp_path))

    assert comparison.newly_included == ()
    assert comparison.newly_excluded == ()
    assert (
        comparison.compatibility_digest
        == "sha256:cdc352fa36186033d98d20ddd3984c1d4481e19342ab9ff7c6e6c08353acd66f"
    )
    assert comparison.requires_acknowledgement is False
    assert comparison.is_compatible is True


def test_legacy_comparison_binds_git_to_plan_root(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    root.mkdir()
    write_policy(root)
    write_files(root, {".gitignore": "ignored.txt\n", "ignored.txt": "ignored"})
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    plan = build_deployment_plan(root)
    monkeypatch.chdir(tmp_path)

    comparison = compare_legacy_deployment_selection(plan)

    assert comparison.newly_included == (
        DeploymentMembership("ignored.txt", "regular-file"),
    )


def test_excluded_path_does_not_create_portable_collision(tmp_path):
    write_policy(tmp_path, ["cache"])
    write_files(tmp_path, {"cache": "local", "CACHE": "deployed"})

    plan = build_deployment_plan(tmp_path)

    assert "cache" not in plan
    assert "CACHE" in plan


def test_reserved_backend_controls_do_not_create_portable_collision(tmp_path):
    write_policy(tmp_path)
    write_files(
        tmp_path,
        {
            ".dockerignore": "first",
            ".DOCKERIGNORE": "second",
        },
    )

    plan = build_deployment_plan(tmp_path)

    assert plan.backend_ignore_controls == (".DOCKERIGNORE", ".dockerignore")
    assert plan.destinations == {"deploy.toml"}


def _comparison_for_acknowledgement(root: Path):
    write_policy(root)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return compare_legacy_deployment_selection(build_deployment_plan(root))


@pytest.mark.parametrize(
    "key",
    [
        "'legacy_diff_acknowledgement'",
        r'"legacy_diff_acknowledge\u006dent"',
    ],
)
def test_acknowledgement_updates_all_supported_quoted_key_syntaxes(tmp_path, key):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    initial = _comparison_for_acknowledgement(tmp_path)
    uppercase_digest = (
        "sha256:" + initial.compatibility_digest.removeprefix("sha256:").upper()
    )
    policy_path = tmp_path / "deploy.toml"
    policy_path.write_text(f"version = 1\n{key} = '{uppercase_digest}'\nexclude = []\n")
    comparison = compare_legacy_deployment_selection(build_deployment_plan(tmp_path))

    assert comparison.configured_acknowledgement == initial.compatibility_digest
    assert comparison.acknowledgement_matches

    acknowledge_legacy_deployment_comparison(comparison)

    updated = policy_path.read_text()
    assert f'{key} = "{initial.compatibility_digest}"' in updated
    assert parse_deployment_policy(policy_path).legacy_diff_acknowledgement == (
        initial.compatibility_digest
    )


def test_acknowledgement_rejects_stale_policy(tmp_path):
    comparison = _comparison_for_acknowledgement(tmp_path)
    policy_path = tmp_path / "deploy.toml"
    policy_path.write_text(policy_path.read_text() + "# changed\n")
    changed = policy_path.read_bytes()

    with pytest.raises(DeploymentCompatibilityError, match="changed since"):
        acknowledge_legacy_deployment_comparison(comparison)

    assert policy_path.read_bytes() == changed
    assert not list(tmp_path.glob(".deploy.toml.tmp-*"))


def test_acknowledgement_detects_race_before_atomic_replace(tmp_path, monkeypatch):
    comparison = _comparison_for_acknowledgement(tmp_path)
    policy_path = tmp_path / "deploy.toml"
    original_writer = deployment_plan._write_policy_temporary_file

    def write_temporary_then_race(*args, **kwargs):
        temporary_name = original_writer(*args, **kwargs)
        policy_path.write_text(policy_path.read_text() + "# raced\n")
        return temporary_name

    monkeypatch.setattr(
        deployment_plan,
        "_write_policy_temporary_file",
        write_temporary_then_race,
    )

    with pytest.raises(DeploymentCompatibilityError, match="changed since"):
        acknowledge_legacy_deployment_comparison(comparison)

    assert "# raced" in policy_path.read_text()
    assert "legacy_diff_acknowledgement" not in policy_path.read_text()
    assert not list(tmp_path.glob(".deploy.toml.tmp-*"))


def test_acknowledgement_rejects_replacement_policy_symlink(tmp_path):
    comparison = _comparison_for_acknowledgement(tmp_path)
    policy_path = tmp_path / "deploy.toml"
    target = tmp_path / "target.toml"
    target.write_text(policy_path.read_text())
    target_before = target.read_bytes()
    policy_path.unlink()
    policy_path.symlink_to(target)

    with pytest.raises(DeploymentPolicyError, match="symbolic link"):
        acknowledge_legacy_deployment_comparison(comparison)

    assert policy_path.is_symlink()
    assert target.read_bytes() == target_before
    assert not list(tmp_path.glob(".deploy.toml.tmp-*"))


def test_acknowledgement_replace_failure_is_atomic(tmp_path, monkeypatch):
    comparison = _comparison_for_acknowledgement(tmp_path)
    policy_path = tmp_path / "deploy.toml"
    original = policy_path.read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("injected replace failure")

    monkeypatch.setattr(deployment_plan.os, "replace", fail_replace)

    with pytest.raises(DeploymentPolicyError, match="atomically update"):
        acknowledge_legacy_deployment_comparison(comparison)

    assert policy_path.read_bytes() == original
    assert not list(tmp_path.glob(".deploy.toml.tmp-*"))
