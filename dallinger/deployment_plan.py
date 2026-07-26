"""Build deterministic deployment manifests from an experiment directory.

This module is the filesystem-policy core of the proposed deployment planner.
It intentionally understands only literal exclusions and experiment-root files:
generated files, framework providers, and backend materialization belong to
later integration layers. It also provides the temporary legacy-selection
comparison needed to inspect migration compatibility. Source trees are treated
as untrusted input, so ambiguous paths, links, repositories, and special files
fail closed rather than acquiring backend-dependent meanings.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import secrets
import stat
import subprocess
import tomllib
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet, Generator, Iterable, TypeVar

POLICY_FILENAME = "deploy.toml"
SCHEMA_VERSION = 1

_POLICY_KEYS = {"version", "exclude", "legacy_diff_acknowledgement"}
_VCS_METADATA_NAMES = frozenset({".git", ".hg", ".svn", ".bzr"})
_GLOB_CHARACTERS = frozenset("*?[]{}")
_WINDOWS_FORBIDDEN_CHARACTERS = frozenset('<>:"/\\|?*')
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
_ACKNOWLEDGEMENT_PATTERN = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")
_MANIFEST_DOMAIN = "dallinger.deployment-plan.manifest"
_MANIFEST_VERSION = 1
_LEGACY_DIFF_DOMAIN = "dallinger.deployment-plan.legacy-diff"
_LEGACY_DIFF_VERSION = 1

_ErrorType = TypeVar("_ErrorType", bound=ValueError)


class DeploymentPolicyError(ValueError):
    """Raised when ``deploy.toml`` is missing, unsafe, or invalid."""


class DeploymentPlanError(ValueError):
    """Raised when an experiment tree cannot produce a safe deployment plan."""


class LegacySelectionError(ValueError):
    """Raised when legacy Git-based deployment selection cannot be inspected."""


class DeploymentCompatibilityError(ValueError):
    """Raised when a migration comparison is unsafe or stale."""


@dataclass(frozen=True)
class DeploymentPolicy:
    """The validated, normalized contents of a version 1 ``deploy.toml``."""

    version: int
    exclude: tuple[str, ...]
    legacy_diff_acknowledgement: str | None = None


@dataclass(frozen=True)
class SourceIdentity:
    """Filesystem identity used to detect source replacement or mutation."""

    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> SourceIdentity:
        """Capture the identity-relevant fields from a stat result."""
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            mode=stat.S_IMODE(value.st_mode),
            size=value.st_size,
            modified_ns=value.st_mtime_ns,
            changed_ns=value.st_ctime_ns,
        )


@dataclass(frozen=True)
class DeploymentPlanEntry:
    """One regular experiment file selected for deployment."""

    source: Path
    destination: str
    size: int
    executable: bool
    source_identity: SourceIdentity
    content_digest: str
    source_category: str = "experiment"


@dataclass(frozen=True)
class DeploymentPlan:
    """An immutable, deterministically ordered experiment-root manifest."""

    root: Path
    policy: DeploymentPolicy
    entries: tuple[DeploymentPlanEntry, ...]
    destinations: frozenset[str]
    total_size: int
    manifest_digest: str
    policy_source_identity: SourceIdentity
    policy_content_digest: str
    backend_ignore_controls: tuple[str, ...]

    def __contains__(self, destination: object) -> bool:
        """Return whether a normalized destination is present in the plan."""
        return isinstance(destination, str) and destination in self.destinations


@dataclass(frozen=True, order=True)
class DeploymentMembership:
    """A normalized destination and its filesystem type."""

    destination: str
    file_type: str


@dataclass(frozen=True)
class LegacyDeploymentComparison:
    """Structured target-versus-legacy deployment membership differences."""

    target: tuple[DeploymentMembership, ...]
    legacy: tuple[DeploymentMembership, ...]
    newly_included: tuple[DeploymentMembership, ...]
    newly_excluded: tuple[DeploymentMembership, ...]
    newly_included_digest: str
    configured_acknowledgement: str | None
    policy_path: Path
    policy_source_identity: SourceIdentity
    policy_content_digest: str
    unresolved_backend_ignore_controls: tuple[str, ...]

    @property
    def requires_acknowledgement(self) -> bool:
        """Return whether target selection adds any legacy-hidden membership."""
        return bool(self.newly_included)

    @property
    def acknowledgement_matches(self) -> bool:
        """Return whether the policy contains the current compatibility digest."""
        return self.configured_acknowledgement == self.newly_included_digest

    @property
    def has_unresolved_backend_filters(self) -> bool:
        """Return whether backend ignore controls prevent safe comparison."""
        return bool(self.unresolved_backend_ignore_controls)

    @property
    def is_compatible(self) -> bool:
        """Return whether migration can proceed under compatibility rules."""
        return not self.has_unresolved_backend_filters and (
            not self.requires_acknowledgement or self.acknowledgement_matches
        )


@dataclass(frozen=True)
class _PolicySnapshot:
    policy: DeploymentPolicy
    source_identity: SourceIdentity
    content_digest: str
    content: bytes


def parse_deployment_policy(path: str | os.PathLike[str]) -> DeploymentPolicy:
    """Load and validate a version 1 literal deployment policy."""
    _require_safe_traversal_support(DeploymentPolicyError)
    policy_path = Path(os.path.abspath(os.fspath(path)))
    parent_descriptor = _open_directory_path(policy_path.parent, DeploymentPolicyError)
    try:
        return _read_policy_snapshot(
            parent_descriptor, policy_path.name, policy_path
        ).policy
    finally:
        os.close(parent_descriptor)


def _parse_policy(raw_policy: dict) -> DeploymentPolicy:
    unknown_keys = set(raw_policy) - _POLICY_KEYS
    if unknown_keys:
        keys = ", ".join(sorted(unknown_keys))
        raise DeploymentPolicyError(f"Unknown deployment policy key(s): {keys}.")

    missing = {"version", "exclude"} - set(raw_policy)
    if missing:
        keys = ", ".join(sorted(missing))
        raise DeploymentPolicyError(f"Missing deployment policy key(s): {keys}.")

    version = raw_policy["version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise DeploymentPolicyError(
            f"Deployment policy version must be the integer {SCHEMA_VERSION}."
        )

    raw_exclusions = raw_policy["exclude"]
    if not isinstance(raw_exclusions, list) or not all(
        isinstance(item, str) for item in raw_exclusions
    ):
        raise DeploymentPolicyError(
            "Deployment policy exclude must be an array of strings."
        )

    acknowledgement = raw_policy.get("legacy_diff_acknowledgement")
    if acknowledgement is not None and (
        not isinstance(acknowledgement, str)
        or _ACKNOWLEDGEMENT_PATTERN.fullmatch(acknowledgement) is None
    ):
        raise DeploymentPolicyError(
            "legacy_diff_acknowledgement must be 'sha256:' followed by "
            "64 hexadecimal digits."
        )

    exclusions: list[str] = []
    exact_entries: set[str] = set()
    portable_entries: dict[str, str] = {}
    for raw_path in raw_exclusions:
        normalized_path = _validate_policy_path(raw_path)
        if normalized_path in exact_entries:
            raise DeploymentPolicyError(
                f"Duplicate normalized exclusion path: {normalized_path!r}."
            )
        portable_path = normalized_path.casefold()
        if portable_path in portable_entries:
            other = portable_entries[portable_path]
            raise DeploymentPolicyError(
                "Exclusion paths collide on case-insensitive filesystems: "
                f"{other!r} and {normalized_path!r}."
            )
        exact_entries.add(normalized_path)
        portable_entries[portable_path] = normalized_path
        exclusions.append(normalized_path)

    return DeploymentPolicy(
        version=version,
        exclude=tuple(sorted(exclusions)),
        legacy_diff_acknowledgement=acknowledgement,
    )


def build_deployment_plan(
    experiment_root: str | os.PathLike[str],
) -> DeploymentPlan:
    """Build a deployment plan containing regular experiment-root files."""
    _require_safe_traversal_support(DeploymentPlanError)
    root = Path(os.path.abspath(os.fspath(experiment_root)))
    root_descriptor = _open_directory_path(root, DeploymentPlanError)
    root_identity = SourceIdentity.from_stat(os.fstat(root_descriptor))
    entries: list[DeploymentPlanEntry] = []
    normalized_sources: dict[str, Path] = {}
    portable_sources: dict[str, tuple[str, Path]] = {}
    backend_ignore_controls: list[str] = []

    def register_destination(destination: str, source: Path) -> None:
        existing = normalized_sources.get(destination)
        if existing is not None and existing != source:
            raise DeploymentPlanError(
                "Source paths normalize to the same deployment destination "
                f"{destination!r}: {existing} and {source}."
            )
        portable = destination.casefold()
        portable_existing = portable_sources.get(portable)
        if portable_existing is not None and portable_existing[0] != destination:
            other_destination, other_source = portable_existing
            raise DeploymentPlanError(
                "Source paths collide on case-insensitive filesystems: "
                f"{other_destination!r} ({other_source}) and "
                f"{destination!r} ({source})."
            )
        normalized_sources[destination] = source
        portable_sources[portable] = (destination, source)

    def walk(
        directory_descriptor: int,
        source_parts: tuple[str, ...],
        destination_parts: tuple[str, ...],
    ) -> None:
        try:
            scanner = os.scandir(directory_descriptor)
        except (OSError, TypeError, NotImplementedError) as error:
            raise DeploymentPlanError(
                f"Cannot safely scan experiment directory {root.joinpath(*source_parts)}: "
                f"{error}"
            ) from error

        with scanner:
            for child in scanner:
                raw_name = child.name
                source = root.joinpath(*source_parts, raw_name)
                name = _normalize_source_component(raw_name, source)
                child_destination_parts = (*destination_parts, name)
                destination = "/".join(child_destination_parts)

                if _is_excluded(child_destination_parts, exclusions):
                    continue

                reserved_kind = _reserved_kind(child_destination_parts)
                if reserved_kind == "backend-ignore":
                    backend_ignore_controls.append(destination)
                    continue
                if reserved_kind == "policy":
                    continue
                if reserved_kind == "vcs":
                    if destination_parts:
                        raise DeploymentPlanError(
                            "Nested repository or submodule metadata is unsupported: "
                            f"{source}. Exclude the complete nested repository or move "
                            "it outside the experiment root."
                        )
                    continue
                if reserved_kind is not None:
                    continue

                register_destination(destination, source)
                try:
                    source_stat = os.stat(
                        raw_name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except OSError as error:
                    raise DeploymentPlanError(
                        f"Cannot inspect deployment source {source}: {error}"
                    ) from error

                if stat.S_ISLNK(source_stat.st_mode):
                    raise DeploymentPlanError(
                        f"Symbolic links are unsupported deployment sources: {source}. "
                        "Exclude the link or replace it with a regular file or directory."
                    )
                if stat.S_ISDIR(source_stat.st_mode):
                    child_descriptor = _open_child_directory(
                        directory_descriptor, raw_name, source, source_stat
                    )
                    child_identity = SourceIdentity.from_stat(
                        os.fstat(child_descriptor)
                    )
                    try:
                        walk(
                            child_descriptor,
                            (*source_parts, raw_name),
                            child_destination_parts,
                        )
                        if (
                            SourceIdentity.from_stat(os.fstat(child_descriptor))
                            != child_identity
                        ):
                            raise DeploymentPlanError(
                                f"Deployment directory changed while planning: {source}."
                            )
                    finally:
                        os.close(child_descriptor)
                    continue
                if not stat.S_ISREG(source_stat.st_mode):
                    source_type = _source_type(source_stat.st_mode)
                    raise DeploymentPlanError(
                        f"Unsupported {source_type} deployment source: {source}. "
                        "Only regular files and directories are supported."
                    )

                identity, content_digest = _hash_regular_file_at(
                    directory_descriptor, raw_name, source, source_stat
                )
                entries.append(
                    DeploymentPlanEntry(
                        source=source,
                        destination=destination,
                        size=identity.size,
                        executable=bool(identity.mode & 0o111),
                        source_identity=identity,
                        content_digest=content_digest,
                    )
                )

    try:
        policy_snapshot = _read_policy_snapshot(
            root_descriptor, POLICY_FILENAME, root / POLICY_FILENAME
        )
        policy = policy_snapshot.policy
        exclusions = frozenset(policy.exclude)
        policy_source = root / POLICY_FILENAME
        register_destination(POLICY_FILENAME, policy_source)
        entries.append(
            DeploymentPlanEntry(
                source=policy_source,
                destination=POLICY_FILENAME,
                size=policy_snapshot.source_identity.size,
                executable=bool(policy_snapshot.source_identity.mode & 0o111),
                source_identity=policy_snapshot.source_identity,
                content_digest=policy_snapshot.content_digest,
            )
        )
        walk(root_descriptor, (), ())
        if SourceIdentity.from_stat(os.fstat(root_descriptor)) != root_identity:
            raise DeploymentPlanError(
                f"Experiment root changed while planning: {root}."
            )
    finally:
        os.close(root_descriptor)

    ordered_entries = tuple(sorted(entries, key=lambda entry: entry.destination))
    destinations = frozenset(entry.destination for entry in ordered_entries)
    total_size = sum(entry.size for entry in ordered_entries)
    manifest_digest = _manifest_digest(ordered_entries)
    return DeploymentPlan(
        root=root,
        policy=policy,
        entries=ordered_entries,
        destinations=destinations,
        total_size=total_size,
        manifest_digest=manifest_digest,
        policy_source_identity=policy_snapshot.source_identity,
        policy_content_digest=policy_snapshot.content_digest,
        backend_ignore_controls=tuple(sorted(set(backend_ignore_controls))),
    )


def compare_legacy_deployment_selection(
    plan: DeploymentPlan,
) -> LegacyDeploymentComparison:
    """Compare a target plan with strict legacy ``ExperimentFileSource`` output."""
    target = tuple(
        DeploymentMembership(entry.destination, "regular-file")
        for entry in plan.entries
    )
    legacy = _legacy_deployment_membership(plan.root)
    target_set = frozenset(target)
    legacy_set = frozenset(legacy)
    newly_included = tuple(sorted(target_set - legacy_set))
    newly_excluded = tuple(sorted(legacy_set - target_set))
    return LegacyDeploymentComparison(
        target=target,
        legacy=legacy,
        newly_included=newly_included,
        newly_excluded=newly_excluded,
        newly_included_digest=compute_legacy_compatibility_digest(newly_included),
        configured_acknowledgement=plan.policy.legacy_diff_acknowledgement,
        policy_path=plan.root / POLICY_FILENAME,
        policy_source_identity=plan.policy_source_identity,
        policy_content_digest=plan.policy_content_digest,
        unresolved_backend_ignore_controls=plan.backend_ignore_controls,
    )


def require_deployment_compatibility(
    plan: DeploymentPlan,
) -> LegacyDeploymentComparison:
    """Require a plan's strict legacy migration comparison to be accepted."""
    comparison = compare_legacy_deployment_selection(plan)
    if comparison.has_unresolved_backend_filters:
        paths = ", ".join(comparison.unresolved_backend_ignore_controls)
        raise DeploymentCompatibilityError(
            "deploy.toml cannot be used while backend ignore controls remain: "
            f"{paths}. Migrate their rules into deploy.toml and remove them."
        )
    if comparison.requires_acknowledgement and not comparison.acknowledgement_matches:
        raise DeploymentCompatibilityError(
            "deploy.toml includes files hidden by legacy selection. Review them "
            "with `dallinger deployment-files check`, then acknowledge the "
            "current comparison with `dallinger deployment-files check "
            "--acknowledge`."
        )
    return comparison


def validate_deployment_plan_entry(
    plan: DeploymentPlan,
    entry: DeploymentPlanEntry,
) -> None:
    """Validate a planned source's current type and filesystem identity."""
    with _open_planned_entry(plan, entry):
        pass


def materialize_deployment_plan_entry(
    plan: DeploymentPlan,
    entry: DeploymentPlanEntry,
    destination: str | os.PathLike[str],
) -> None:
    """Atomically copy and verify one planned file into a trusted destination."""
    target = Path(os.path.abspath(os.fspath(destination)))
    target.parent.mkdir(parents=True, exist_ok=True)
    # The caller owns and trusts the staging path. Resolve its already-created
    # parent once so benign platform aliases such as macOS /var -> /private/var
    # are accepted; all operations within that canonical directory use dir_fd
    # and no-follow semantics.
    try:
        canonical_parent = target.parent.resolve(strict=True)
    except OSError as error:
        raise DeploymentPlanError(
            f"Cannot resolve trusted deployment destination {target.parent}: {error}"
        ) from error
    parent_descriptor = _open_directory_path(canonical_parent, DeploymentPlanError)
    temporary_name = f".dallinger-deployment-{secrets.token_hex(12)}"
    temporary_descriptor: int | None = None
    try:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        temporary_descriptor = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        digest = hashlib.sha256()
        copied_size = 0
        with _open_planned_entry(plan, entry) as source_descriptor:
            while block := os.read(source_descriptor, 1024 * 1024):
                digest.update(block)
                copied_size += len(block)
                _write_all(temporary_descriptor, block)
            if (
                SourceIdentity.from_stat(os.fstat(source_descriptor))
                != entry.source_identity
            ):
                raise DeploymentPlanError(
                    f"Deployment source changed while being copied: {entry.source}."
                )

        copied_digest = f"sha256:{digest.hexdigest()}"
        if copied_size != entry.size or copied_digest != entry.content_digest:
            raise DeploymentPlanError(
                f"Deployment source content digest changed: {entry.source}."
            )
        os.fchmod(temporary_descriptor, entry.source_identity.mode)
        os.fsync(temporary_descriptor)
        os.close(temporary_descriptor)
        temporary_descriptor = None
        os.link(
            temporary_name,
            target.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        os.unlink(temporary_name, dir_fd=parent_descriptor)
        temporary_name = ""
        os.fsync(parent_descriptor)
    except DeploymentPlanError:
        raise
    except OSError as error:
        raise DeploymentPlanError(
            f"Cannot materialize deployment entry {entry.destination!r}: {error}"
        ) from error
    finally:
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        os.close(parent_descriptor)


@contextmanager
def _open_planned_entry(
    plan: DeploymentPlan,
    entry: DeploymentPlanEntry,
) -> Generator[int, None, None]:
    """Open a planned source through no-follow root-relative traversal."""
    try:
        relative_source = entry.source.relative_to(plan.root)
    except ValueError as error:
        raise DeploymentPlanError(
            f"Deployment source is outside its plan root: {entry.source}."
        ) from error
    if not relative_source.parts or ".." in relative_source.parts:
        raise DeploymentPlanError(
            f"Deployment source is not a safe root-relative path: {entry.source}."
        )

    directory_descriptors = [_open_directory_path(plan.root, DeploymentPlanError)]
    source_descriptor: int | None = None
    current_source = plan.root
    try:
        for component in relative_source.parts[:-1]:
            current_source /= component
            try:
                expected_stat = os.stat(
                    component,
                    dir_fd=directory_descriptors[-1],
                    follow_symlinks=False,
                )
            except OSError as error:
                raise DeploymentPlanError(
                    f"Cannot inspect deployment directory {current_source}: {error}"
                ) from error
            if not stat.S_ISDIR(expected_stat.st_mode):
                raise DeploymentPlanError(
                    f"Deployment directory changed type: {current_source}."
                )
            directory_descriptors.append(
                _open_child_directory(
                    directory_descriptors[-1],
                    component,
                    current_source,
                    expected_stat,
                )
            )

        name = relative_source.parts[-1]
        try:
            expected_stat = os.stat(
                name,
                dir_fd=directory_descriptors[-1],
                follow_symlinks=False,
            )
        except OSError as error:
            raise DeploymentPlanError(
                f"Cannot inspect deployment source {entry.source}: {error}"
            ) from error
        if stat.S_ISLNK(expected_stat.st_mode):
            raise DeploymentPlanError(
                f"Deployment source changed to a symbolic link: {entry.source}."
            )
        if not stat.S_ISREG(expected_stat.st_mode):
            raise DeploymentPlanError(
                f"Deployment source changed type: {entry.source}."
            )
        if SourceIdentity.from_stat(expected_stat) != entry.source_identity:
            raise DeploymentPlanError(
                f"Deployment source changed since planning: {entry.source}."
            )

        try:
            source_descriptor = os.open(
                name,
                _file_open_flags(),
                dir_fd=directory_descriptors[-1],
            )
        except OSError as error:
            raise DeploymentPlanError(
                f"Cannot safely open deployment source {entry.source}: {error}"
            ) from error
        if (
            SourceIdentity.from_stat(os.fstat(source_descriptor))
            != entry.source_identity
        ):
            raise DeploymentPlanError(
                f"Deployment source changed while being opened: {entry.source}."
            )
        yield source_descriptor
    finally:
        if source_descriptor is not None:
            os.close(source_descriptor)
        for descriptor in reversed(directory_descriptors):
            os.close(descriptor)


def _write_all(descriptor: int, content: bytes) -> None:
    """Write a complete block to an open descriptor."""
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write while materializing deployment entry")
        view = view[written:]


def compute_legacy_compatibility_digest(
    memberships: Iterable[DeploymentMembership],
) -> str:
    """Hash path/type membership with an explicit compatibility domain/version."""
    canonical_memberships = sorted(set(memberships))
    manifest = {
        "domain": _LEGACY_DIFF_DOMAIN,
        "version": _LEGACY_DIFF_VERSION,
        "memberships": [
            {
                "destination": membership.destination,
                "file_type": membership.file_type,
            }
            for membership in canonical_memberships
        ],
    }
    encoded_manifest = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded_manifest).hexdigest()}"


def acknowledge_legacy_deployment_comparison(
    comparison: LegacyDeploymentComparison,
) -> None:
    """Atomically acknowledge one current, fully resolved migration comparison."""
    if comparison.has_unresolved_backend_filters:
        paths = ", ".join(comparison.unresolved_backend_ignore_controls)
        raise DeploymentCompatibilityError(
            "Cannot acknowledge while source backend ignore controls remain: "
            f"{paths}. Migrate their filtering into deploy.toml and remove them."
        )
    digest = compute_legacy_compatibility_digest(comparison.newly_included)
    if digest != comparison.newly_included_digest:
        raise DeploymentCompatibilityError(
            "Cannot acknowledge an internally inconsistent migration comparison."
        )
    _update_legacy_diff_acknowledgement(
        comparison.policy_path,
        digest,
        comparison.policy_source_identity,
        comparison.policy_content_digest,
    )


def _update_legacy_diff_acknowledgement(
    path: Path,
    digest: str,
    expected_identity: SourceIdentity,
    expected_content_digest: str,
) -> None:
    """Safely replace a policy only while its compared snapshot is current."""
    parent_descriptor = _open_directory_path(path.parent, DeploymentPolicyError)
    temporary_name: str | None = None
    try:
        snapshot = _read_policy_snapshot(parent_descriptor, path.name, path)
        _require_expected_policy_snapshot(
            snapshot, expected_identity, expected_content_digest
        )
        updated = _updated_policy_content(snapshot, digest)
        temporary_name = _write_policy_temporary_file(
            parent_descriptor,
            path.name,
            updated,
            snapshot.source_identity.mode,
        )

        current_snapshot = _read_policy_snapshot(parent_descriptor, path.name, path)
        _require_expected_policy_snapshot(
            current_snapshot, expected_identity, expected_content_digest
        )
        try:
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_name = None
            os.fsync(parent_descriptor)
        except OSError as error:
            raise DeploymentPolicyError(
                f"Cannot atomically update deployment policy {path}: {error}"
            ) from error
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        os.close(parent_descriptor)


def _updated_policy_content(snapshot: _PolicySnapshot, digest: str) -> bytes:
    """Return policy bytes with only the acknowledgement value changed."""
    try:
        text = snapshot.content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DeploymentPolicyError("Deployment policy is not valid UTF-8.") from error
    assignment = re.compile(
        r"""(?mx)
        ^
        (?P<prefix>
            [ \t]*
            (?:"legacy_diff_acknowledgement"|legacy_diff_acknowledgement)
            [ \t]*=[ \t]*
        )
        (?P<value>"(?:\\.|[^"\r\n])*"|'[^'\r\n]*')
        """
    )
    replacement = rf'\g<prefix>"{digest}"'
    updated, replacements = assignment.subn(replacement, text, count=1)
    if not replacements:
        if snapshot.policy.legacy_diff_acknowledgement is not None:
            raise DeploymentPolicyError(
                "Cannot safely update the existing multiline "
                "legacy_diff_acknowledgement assignment."
            )
        newline = "\r\n" if "\r\n" in text else "\n"
        version_assignment = re.compile(
            r'(?m)^[ \t]*(?:"version"|version)[ \t]*=[^\r\n]*(?:\r?\n|$)'
        )
        match = version_assignment.search(text)
        if match is None:
            raise DeploymentPolicyError(
                "Cannot safely locate the deployment policy version assignment."
            )
        version_line = match.group(0)
        if not version_line.endswith(("\n", "\r")):
            version_line += newline
        insertion = version_line + f'legacy_diff_acknowledgement = "{digest}"' + newline
        updated = text[: match.start()] + insertion + text[match.end() :]

    try:
        _parse_policy(tomllib.loads(updated))
    except tomllib.TOMLDecodeError as error:
        raise DeploymentPolicyError(
            f"Cannot safely update deployment policy TOML: {error}"
        ) from error
    return updated.encode("utf-8")


def _require_expected_policy_snapshot(
    snapshot: _PolicySnapshot,
    expected_identity: SourceIdentity,
    expected_content_digest: str,
) -> None:
    """Reject a policy snapshot that differs from the compared plan."""
    if (
        snapshot.source_identity != expected_identity
        or snapshot.content_digest != expected_content_digest
    ):
        raise DeploymentCompatibilityError(
            "deploy.toml changed since the migration comparison; rerun "
            "`dallinger deployment-files check` before acknowledging."
        )


def _write_policy_temporary_file(
    parent_descriptor: int,
    policy_name: str,
    content: bytes,
    mode: int,
) -> str:
    """Create, sync, and close a same-directory regular temporary file."""
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    temporary_name = ""
    descriptor: int | None = None
    for _ in range(100):
        temporary_name = f".{policy_name}.tmp-{secrets.token_hex(12)}"
        try:
            descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=parent_descriptor,
            )
            break
        except FileExistsError:
            continue
        except OSError as error:
            raise DeploymentPolicyError(
                f"Cannot create temporary deployment policy: {error}"
            ) from error
    if descriptor is None:
        raise DeploymentPolicyError(
            "Cannot allocate a unique temporary deployment policy."
        )

    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DeploymentPolicyError(
                "Temporary deployment policy is not a regular file."
            )
        os.fchmod(descriptor, mode)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while updating deployment policy")
            view = view[written:]
        os.fsync(descriptor)
    except (OSError, DeploymentPolicyError) as error:
        try:
            os.close(descriptor)
        finally:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        if isinstance(error, DeploymentPolicyError):
            raise
        raise DeploymentPolicyError(
            f"Cannot write temporary deployment policy: {error}"
        ) from error
    os.close(descriptor)
    return temporary_name


class _StrictLegacyGitFiles:
    """Supply ``ExperimentFileSource`` with cwd-independent, fail-closed Git files."""

    def __init__(self, root: Path):
        self.root = root

    def files(self) -> set[str]:
        command = [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ]
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as error:
            raise LegacySelectionError(
                f"Legacy Git file selection failed for {self.root}: {error}."
            ) from error
        if result.returncode:
            raise LegacySelectionError(
                "Legacy Git file selection failed for "
                f"{self.root} with exit status {result.returncode}."
            )
        try:
            output = result.stdout.decode()
        except UnicodeDecodeError as error:
            raise LegacySelectionError(
                f"Legacy Git file selection returned undecodable paths for {self.root}."
            ) from error
        return {item for item in output.split("\0") if item}


def _legacy_deployment_membership(
    experiment_root: Path,
) -> tuple[DeploymentMembership, ...]:
    """Evaluate current legacy filtering while binding Git to the same root."""
    from dallinger.utils import ExperimentFileSource

    root = Path(os.path.abspath(experiment_root))
    file_source = ExperimentFileSource(
        root,
        selection="legacy",
        git_client=_StrictLegacyGitFiles(root),
    )
    destination_root = root.parent / f".{root.name}-legacy-destination"
    memberships: list[DeploymentMembership] = []
    try:
        locations = file_source.map_locations_to(destination_root)
        for source, destination in locations:
            relative = os.path.relpath(destination, destination_root)
            if relative == os.pardir or relative.startswith(os.pardir + os.sep):
                raise LegacySelectionError(
                    f"Legacy selection produced an unsafe destination: {destination}."
                )
            memberships.append(
                DeploymentMembership(
                    unicodedata.normalize("NFC", Path(relative).as_posix()),
                    _legacy_source_type(Path(source)),
                )
            )
    except LegacySelectionError:
        raise
    except OSError as error:
        raise LegacySelectionError(
            f"Legacy deployment selection failed for {root}: {error}."
        ) from error
    return tuple(sorted(set(memberships)))


def _legacy_source_type(source: Path) -> str:
    """Describe legacy membership without reading source contents."""
    try:
        mode = source.lstat().st_mode
    except OSError as error:
        raise LegacySelectionError(
            f"Cannot inspect legacy deployment source {source}: {error}."
        ) from error
    if stat.S_ISREG(mode):
        return "regular-file"
    if stat.S_ISLNK(mode):
        return "symlink"
    return _source_type(mode)


def _validate_policy_path(value: str) -> str:
    """Validate and NFC-normalize one literal root-relative exclusion."""
    if not value:
        raise DeploymentPolicyError("Exclusion paths must not be empty.")
    if "\\" in value:
        raise DeploymentPolicyError(
            f"Exclusion paths must use POSIX separators: {value!r}."
        )
    if value.startswith("/") or ntpath.splitdrive(value)[0]:
        raise DeploymentPolicyError(
            f"Exclusion paths must be relative to the experiment root: {value!r}."
        )
    if value.startswith("!"):
        raise DeploymentPolicyError(
            f"Negated exclusion paths are unsupported: {value!r}."
        )
    if any(character in _GLOB_CHARACTERS for character in value):
        raise DeploymentPolicyError(
            f"Glob syntax is unsupported in exclusion paths: {value!r}."
        )

    components = value.split("/")
    if any(not component for component in components):
        raise DeploymentPolicyError(
            f"Exclusion paths must not contain empty components: {value!r}."
        )

    normalized_parts = tuple(
        _normalize_portable_component(
            component,
            context=f"exclusion path {value!r}",
            error_type=DeploymentPolicyError,
        )
        for component in components
    )
    normalized = "/".join(normalized_parts)
    if _reserved_kind(normalized_parts) is not None:
        raise DeploymentPolicyError(
            f"Deployment policy cannot exclude required or reserved path {normalized!r}."
        )
    return normalized


def _normalize_source_component(name: str, source: Path) -> str:
    """Normalize one filesystem name for use as a POSIX destination component."""
    return _normalize_portable_component(
        name, context=f"deployment source {source}", error_type=DeploymentPlanError
    )


def _normalize_portable_component(
    component: str,
    *,
    context: str,
    error_type: type[_ErrorType],
) -> str:
    """Validate and NFC-normalize one portable destination component."""
    normalized = unicodedata.normalize("NFC", component)
    if not normalized or normalized in {".", ".."}:
        raise error_type(f"Invalid path component in {context}: {component!r}.")
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise error_type(
            f"Path component is not valid Unicode in {context}."
        ) from error
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in normalized):
        raise error_type(f"Control characters are unsupported in {context}.")
    forbidden = _WINDOWS_FORBIDDEN_CHARACTERS.intersection(normalized)
    if forbidden:
        characters = "".join(sorted(forbidden))
        raise error_type(
            f"Windows-forbidden character(s) {characters!r} are unsupported in {context}."
        )
    if normalized.endswith((" ", ".")):
        raise error_type(
            f"Path components must not end with a space or dot in {context}."
        )
    device_stem = normalized.split(".", 1)[0].casefold()
    if device_stem in _WINDOWS_DEVICE_NAMES:
        raise error_type(
            f"Windows device name {normalized!r} is unsupported in {context}."
        )
    return normalized


def _is_excluded(
    destination_parts: tuple[str, ...], exclusions: AbstractSet[str]
) -> bool:
    """Check exact ancestors against an exclusion set by path depth."""
    return any(
        "/".join(destination_parts[:depth]) in exclusions
        for depth in range(1, len(destination_parts) + 1)
    )


def _reserved_kind(destination_parts: tuple[str, ...]) -> str | None:
    """Classify non-overridable paths using portable case-insensitive names."""
    basename = destination_parts[-1].casefold()
    if len(destination_parts) == 1 and basename == POLICY_FILENAME:
        return "policy"
    if basename in _VCS_METADATA_NAMES:
        return "vcs"
    if len(destination_parts) == 1 and basename == "config.txt":
        return "configuration"
    if basename == ".slugignore" or basename.endswith(".dockerignore"):
        return "backend-ignore"
    return None


def _require_safe_traversal_support(
    error_type: type[_ErrorType],
) -> None:
    """Fail unless native POSIX descriptor-relative containment is available."""
    supported = (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    )
    if not supported:
        raise error_type(
            "Deployment planning currently requires POSIX descriptor-relative "
            "traversal with O_NOFOLLOW and O_DIRECTORY; Windows/reparse-point "
            "sources are not supported by this prototype."
        )


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _file_open_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_directory_path(
    path: Path,
    error_type: type[_ErrorType],
) -> int:
    """Open an absolute directory one no-follow component at a time."""
    if not path.is_absolute():
        raise error_type(f"Safe directory traversal requires an absolute path: {path}.")

    descriptor: int | None = None
    try:
        descriptor = os.open("/", _directory_open_flags())
        for component in path.parts[1:]:
            child_descriptor = os.open(
                component, _directory_open_flags(), dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child_descriptor
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise error_type(f"Deployment source directory is not a directory: {path}.")
        return descriptor
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise error_type(
            f"Cannot safely open deployment source directory {path}: {error}"
        ) from error


def _open_child_directory(
    parent_descriptor: int,
    name: str,
    source: Path,
    expected_stat: os.stat_result,
) -> int:
    """Open a child directory without following a replacement link."""
    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_descriptor)
    except OSError as error:
        raise DeploymentPlanError(
            f"Cannot safely open deployment directory {source}: {error}"
        ) from error

    opened_identity = SourceIdentity.from_stat(os.fstat(descriptor))
    if opened_identity != SourceIdentity.from_stat(expected_stat):
        os.close(descriptor)
        raise DeploymentPlanError(
            f"Deployment directory changed while being opened: {source}."
        )
    return descriptor


def _read_policy_snapshot(
    parent_descriptor: int,
    name: str,
    source: Path,
) -> _PolicySnapshot:
    """Parse and hash a policy from one no-follow descriptor snapshot."""
    try:
        expected_stat = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as error:
        raise DeploymentPolicyError(
            f"Cannot inspect deployment policy {source}: {error}"
        ) from error

    if stat.S_ISLNK(expected_stat.st_mode):
        raise DeploymentPolicyError(
            f"Deployment policy {source} must not be a symbolic link."
        )
    if not stat.S_ISREG(expected_stat.st_mode):
        raise DeploymentPolicyError(
            f"Deployment policy {source} must be a regular file."
        )

    try:
        descriptor = os.open(name, _file_open_flags(), dir_fd=parent_descriptor)
    except OSError as error:
        raise DeploymentPolicyError(
            f"Cannot safely open deployment policy {source}: {error}"
        ) from error

    try:
        identity, content_digest, content = _read_open_descriptor(
            descriptor,
            source,
            expected_stat,
            collect_content=True,
            error_type=DeploymentPolicyError,
        )
    finally:
        os.close(descriptor)

    try:
        raw_policy = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DeploymentPolicyError(
            f"Invalid TOML in deployment policy {source}: {error}"
        ) from error
    return _PolicySnapshot(
        policy=_parse_policy(raw_policy),
        source_identity=identity,
        content_digest=content_digest,
        content=content,
    )


def _hash_regular_file_at(
    parent_descriptor: int,
    name: str,
    source: Path,
    expected_stat: os.stat_result,
) -> tuple[SourceIdentity, str]:
    """Hash a regular file through its parent descriptor."""
    try:
        descriptor = os.open(name, _file_open_flags(), dir_fd=parent_descriptor)
    except OSError as error:
        raise DeploymentPlanError(
            f"Cannot open deployment source {source}: {error}"
        ) from error

    try:
        identity, content_digest, _ = _read_open_descriptor(
            descriptor,
            source,
            expected_stat,
            collect_content=False,
            error_type=DeploymentPlanError,
        )
    finally:
        os.close(descriptor)

    return identity, content_digest


def _read_open_descriptor(
    descriptor: int,
    source: Path,
    expected_stat: os.stat_result,
    *,
    collect_content: bool,
    error_type: type[_ErrorType],
) -> tuple[SourceIdentity, str, bytes]:
    """Read and hash one already-open descriptor, checking identity twice."""
    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise error_type(
                f"Deployment source changed type while planning: {source}."
            )
        opened_identity = SourceIdentity.from_stat(opened_stat)
        if opened_identity != SourceIdentity.from_stat(expected_stat):
            raise error_type(f"Deployment source changed while planning: {source}.")

        digest = hashlib.sha256()
        content_blocks: list[bytes] = []
        while block := os.read(descriptor, 1024 * 1024):
            digest.update(block)
            if collect_content:
                content_blocks.append(block)

        if SourceIdentity.from_stat(os.fstat(descriptor)) != opened_identity:
            raise error_type(f"Deployment source changed while being hashed: {source}.")
    except OSError as error:
        raise error_type(f"Cannot hash deployment source {source}: {error}") from error

    return (
        opened_identity,
        f"sha256:{digest.hexdigest()}",
        b"".join(content_blocks),
    )


def _manifest_digest(entries: tuple[DeploymentPlanEntry, ...]) -> str:
    manifest = {
        "domain": _MANIFEST_DOMAIN,
        "version": _MANIFEST_VERSION,
        "entries": [
            {
                "content_digest": entry.content_digest,
                "destination": entry.destination,
                "executable": entry.executable,
                "size": entry.size,
                "source_category": entry.source_category,
            }
            for entry in entries
        ],
    }
    encoded_manifest = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded_manifest).hexdigest()}"


def _source_type(mode: int) -> str:
    if stat.S_ISFIFO(mode):
        return "FIFO"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "character-device"
    if stat.S_ISBLK(mode):
        return "block-device"
    return "special-file"
