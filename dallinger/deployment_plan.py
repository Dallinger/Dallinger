"""Build deterministic deployment manifests from an experiment directory.

This module is the filesystem-policy core of the proposed deployment planner.
It intentionally understands only literal exclusions and experiment-root files:
generated files, framework providers, and backend materialization belong to
later integration layers. It also provides the temporary legacy-selection
comparison needed to inspect migration compatibility. Source trees are treated
as untrusted input, so ambiguous paths, links, repositories, and special files
fail closed rather than acquiring backend-dependent meanings.

Traversal uses ordinary ``lstat`` / ``scandir`` checks (no symlink following).
Containment rejects symlinks, special files, and paths outside the experiment
root. The planner does not re-validate filesystem identity between planning and
materialization; that window is short and the working tree is trusted.
"""

from __future__ import annotations

import bisect
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
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet, Iterable, TypeVar

POLICY_FILENAME = "deploy.toml"
SCHEMA_VERSION = 1

_POLICY_KEYS = {"version", "exclude", "legacy_diff_acknowledgement"}
_VCS_METADATA_NAMES = frozenset({".git", ".hg", ".svn", ".bzr"})
_GENERATED_ROOT_DESTINATION_NAMES = frozenset(
    {
        "config.txt",
        "constraints.txt",
        "experiment_id.txt",
        "requirements.txt",
        "runtime.txt",
    }
)
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
_LEGACY_DIFF_VERSION = 2

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
class DeploymentPlanEntry:
    """One regular experiment file selected for deployment."""

    source: Path
    destination: str
    size: int
    mode: int
    executable: bool
    content_digest: str
    source_category: str = "experiment"


@dataclass(frozen=True)
class DeploymentDirectoryLinkCandidate:
    """One fully selected source directory eligible for a development link."""

    source: Path
    destination: str
    entry_start: int
    entry_stop: int

    @property
    def entry_count(self) -> int:
        """Return the number of planned files covered by this directory."""
        return self.entry_stop - self.entry_start


@dataclass(frozen=True)
class DeploymentPlan:
    """An immutable, deterministically ordered experiment-root manifest."""

    root: Path
    policy: DeploymentPolicy
    entries: tuple[DeploymentPlanEntry, ...]
    destinations: frozenset[str]
    total_size: int
    manifest_digest: str
    backend_ignore_controls: tuple[str, ...]
    directory_link_candidates: tuple[DeploymentDirectoryLinkCandidate, ...]

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
    compatibility_digest: str
    configured_acknowledgement: str | None
    unresolved_backend_ignore_controls: tuple[str, ...]

    @property
    def requires_acknowledgement(self) -> bool:
        """Return whether target and legacy membership differ."""
        return bool(self.newly_included or self.newly_excluded)

    @property
    def acknowledgement_matches(self) -> bool:
        """Return whether the policy contains the current compatibility digest."""
        return self.configured_acknowledgement == self.compatibility_digest

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
    size: int
    mode: int
    content_digest: str


@dataclass(frozen=True)
class _TraversedDirectoryCandidate:
    source: Path
    destination: str
    entry_count: int


class _ExclusionIndex:
    """Index literal exclusions for logarithmic descendant queries."""

    def __init__(self, exclusions: Iterable[str]):
        self._ordered = tuple(sorted(exclusions))

    def has_at_or_below(self, destination_parts: tuple[str, ...]) -> bool:
        """Return whether an exclusion equals or descends from a destination."""
        if not destination_parts:
            return bool(self._ordered)
        destination = "/".join(destination_parts)
        exact_index = bisect.bisect_left(self._ordered, destination)
        if (
            exact_index < len(self._ordered)
            and self._ordered[exact_index] == destination
        ):
            return True
        prefix = destination + "/"
        descendant_index = bisect.bisect_left(self._ordered, prefix, lo=exact_index)
        return descendant_index < len(self._ordered) and self._ordered[
            descendant_index
        ].startswith(prefix)


def parse_deployment_policy(path: str | os.PathLike[str]) -> DeploymentPolicy:
    """Load and validate a version 1 literal deployment policy."""
    _require_posix_support(DeploymentPolicyError)
    policy_path = Path(os.path.abspath(os.fspath(path)))
    return _read_policy_snapshot(policy_path).policy


def validate_explicit_provider_destination(
    destination: str | os.PathLike[str],
) -> str:
    """Validate one root-relative destination supplied by ``extra_files()``."""
    value = os.fspath(destination)
    if not value or value.startswith("/") or ntpath.splitdrive(value)[0]:
        raise DeploymentPlanError(
            f"Explicit file provider destination must be root-relative: {value!r}."
        )
    if "\\" in value:
        raise DeploymentPlanError(
            f"Explicit file provider destinations must use POSIX separators: {value!r}."
        )

    components = value.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise DeploymentPlanError(
            "Explicit file provider destination contains an unsafe path component: "
            f"{value!r}."
        )
    normalized_parts = tuple(
        _normalize_portable_component(
            component,
            context=f"explicit file provider destination {value!r}",
            error_type=DeploymentPlanError,
        )
        for component in components
    )
    normalized = "/".join(normalized_parts)
    reserved_kind = _reserved_kind(normalized_parts)
    if (
        reserved_kind is None
        and normalized_parts[0].casefold() in _GENERATED_ROOT_DESTINATION_NAMES
    ):
        reserved_kind = "generated"
    if reserved_kind is not None:
        raise DeploymentPlanError(
            "Explicit file provider cannot target reserved deployment destination "
            f"{normalized!r} ({reserved_kind})."
        )
    return normalized


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
    if acknowledgement is not None:
        acknowledgement = acknowledgement.lower()

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
    _require_posix_support(DeploymentPlanError)
    root = Path(os.path.abspath(os.fspath(experiment_root)))
    _assert_no_symlink_components(root, DeploymentPlanError)
    try:
        root_stat = root.lstat()
    except OSError as error:
        raise DeploymentPlanError(
            f"Cannot inspect experiment root {root}: {error}"
        ) from error
    if not stat.S_ISDIR(root_stat.st_mode):
        raise DeploymentPlanError(f"Experiment root is not a directory: {root}.")

    entries: list[DeploymentPlanEntry] = []
    normalized_sources: dict[str, Path] = {}
    portable_sources: dict[str, tuple[str, Path]] = {}
    backend_ignore_controls: list[str] = []
    traversed_directory_candidates: list[_TraversedDirectoryCandidate] = []

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
        directory: Path,
        source_parts: tuple[str, ...],
        destination_parts: tuple[str, ...],
    ) -> bool:
        """Traverse one directory and report whether all descendants are selected."""
        all_descendants_selected = not _has_exclusion_at_or_below(
            destination_parts, exclusion_index
        )
        try:
            scanner = os.scandir(directory)
        except OSError as error:
            raise DeploymentPlanError(
                f"Cannot scan experiment directory {directory}: {error}"
            ) from error

        with scanner:
            for child in scanner:
                raw_name = child.name
                source = directory / raw_name
                name = _normalize_source_component(raw_name, source)
                child_destination_parts = (*destination_parts, name)
                destination = "/".join(child_destination_parts)

                if _is_excluded(child_destination_parts, exclusions):
                    all_descendants_selected = False
                    continue

                reserved_kind = _reserved_kind(child_destination_parts)
                if reserved_kind == "backend-ignore":
                    backend_ignore_controls.append(destination)
                    all_descendants_selected = False
                    continue
                if reserved_kind == "policy":
                    all_descendants_selected = False
                    continue
                if reserved_kind == "vcs":
                    if destination_parts:
                        raise DeploymentPlanError(
                            "Nested repository or submodule metadata is unsupported: "
                            f"{source}. Exclude the complete nested repository or move "
                            "it outside the experiment root."
                        )
                    all_descendants_selected = False
                    continue
                if reserved_kind is not None:
                    all_descendants_selected = False
                    continue

                register_destination(destination, source)
                try:
                    source_stat = child.stat(follow_symlinks=False)
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
                    child_entry_start = len(entries)
                    child_all_selected = walk(
                        source,
                        (*source_parts, raw_name),
                        child_destination_parts,
                    )
                    child_entry_count = len(entries) - child_entry_start
                    if child_all_selected and child_entry_count:
                        traversed_directory_candidates.append(
                            _TraversedDirectoryCandidate(
                                source=source,
                                destination=destination,
                                entry_count=child_entry_count,
                            )
                        )
                    if not child_all_selected:
                        all_descendants_selected = False
                    continue
                if not stat.S_ISREG(source_stat.st_mode):
                    source_type = _source_type(source_stat.st_mode)
                    raise DeploymentPlanError(
                        f"Unsupported {source_type} deployment source: {source}. "
                        "Only regular files and directories are supported."
                    )

                mode = stat.S_IMODE(source_stat.st_mode)
                content_digest = _hash_regular_file(source)
                entries.append(
                    DeploymentPlanEntry(
                        source=source,
                        destination=destination,
                        size=source_stat.st_size,
                        mode=mode,
                        executable=bool(mode & 0o111),
                        content_digest=content_digest,
                    )
                )
        return all_descendants_selected

    policy_snapshot = _read_policy_snapshot(root / POLICY_FILENAME)
    policy = policy_snapshot.policy
    exclusions = frozenset(policy.exclude)
    exclusion_index = _ExclusionIndex(exclusions)
    policy_source = root / POLICY_FILENAME
    register_destination(POLICY_FILENAME, policy_source)
    entries.append(
        DeploymentPlanEntry(
            source=policy_source,
            destination=POLICY_FILENAME,
            size=policy_snapshot.size,
            mode=policy_snapshot.mode,
            executable=bool(policy_snapshot.mode & 0o111),
            content_digest=policy_snapshot.content_digest,
        )
    )
    walk(root, (), ())

    ordered_entries = tuple(sorted(entries, key=lambda entry: entry.destination))
    ordered_destinations = tuple(entry.destination for entry in ordered_entries)
    destinations = frozenset(entry.destination for entry in ordered_entries)
    directory_link_candidates = tuple(
        sorted(
            (
                _finalize_directory_candidate(candidate, ordered_destinations)
                for candidate in traversed_directory_candidates
            ),
            key=lambda candidate: candidate.destination,
        )
    )
    total_size = sum(entry.size for entry in ordered_entries)
    manifest_digest = _manifest_digest(ordered_entries)
    return DeploymentPlan(
        root=root,
        policy=policy,
        entries=ordered_entries,
        destinations=destinations,
        total_size=total_size,
        manifest_digest=manifest_digest,
        backend_ignore_controls=tuple(sorted(set(backend_ignore_controls))),
        directory_link_candidates=directory_link_candidates,
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
        compatibility_digest=compute_legacy_compatibility_digest(
            newly_included=newly_included,
            newly_excluded=newly_excluded,
        ),
        configured_acknowledgement=plan.policy.legacy_diff_acknowledgement,
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
            "deploy.toml changes file membership relative to legacy selection. "
            "Review newly included and newly excluded paths with `dallinger "
            "deployment-files check`, then manually set "
            "legacy_diff_acknowledgement to the compatibility digest it prints."
        )
    return comparison


def materialize_deployment_plan_entry(
    plan: DeploymentPlan,
    entry: DeploymentPlanEntry,
    destination: str | os.PathLike[str],
) -> None:
    """Copy and verify one planned file into a trusted destination."""
    target = Path(os.path.abspath(os.fspath(destination)))
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_source_under_root(plan.root, entry.source)
    try:
        source_stat = entry.source.lstat()
    except OSError as error:
        raise DeploymentPlanError(
            f"Cannot inspect deployment source {entry.source}: {error}"
        ) from error
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise DeploymentPlanError(
            f"Deployment source is not a regular file: {entry.source}."
        )

    temporary = target.parent / f".dallinger-deployment-{secrets.token_hex(12)}"
    digest = hashlib.sha256()
    copied_size = 0
    try:
        with entry.source.open("rb") as source_handle, temporary.open(
            "xb"
        ) as temporary_handle:
            while block := source_handle.read(1024 * 1024):
                digest.update(block)
                copied_size += len(block)
                temporary_handle.write(block)

        copied_digest = f"sha256:{digest.hexdigest()}"
        if copied_size != entry.size or copied_digest != entry.content_digest:
            raise DeploymentPlanError(
                f"Deployment source content digest changed: {entry.source}."
            )
        os.chmod(temporary, entry.mode)
        # Fail if the final component already exists (including as a symlink)
        # rather than following or replacing it.
        os.link(temporary, target)
        temporary.unlink()
        temporary = None
    except DeploymentPlanError:
        raise
    except OSError as error:
        raise DeploymentPlanError(
            f"Cannot materialize deployment entry {entry.destination!r}: {error}"
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _finalize_directory_candidate(
    candidate: _TraversedDirectoryCandidate,
    ordered_destinations: tuple[str, ...],
) -> DeploymentDirectoryLinkCandidate:
    """Map one traversal candidate to its contiguous ordered plan-entry span."""
    prefix = candidate.destination + "/"
    entry_start = bisect.bisect_left(ordered_destinations, prefix)
    entry_stop = bisect.bisect_left(
        ordered_destinations, candidate.destination + "0", lo=entry_start
    )
    if entry_stop - entry_start != candidate.entry_count:
        raise DeploymentPlanError(
            "Deployment directory candidate does not cover exactly its planned "
            f"descendants: {candidate.source}."
        )
    return DeploymentDirectoryLinkCandidate(
        source=candidate.source,
        destination=candidate.destination,
        entry_start=entry_start,
        entry_stop=entry_stop,
    )


def compute_legacy_compatibility_digest(
    *,
    newly_included: Iterable[DeploymentMembership] = (),
    newly_excluded: Iterable[DeploymentMembership] = (),
) -> str:
    """Hash directional path/type changes in a canonical domain/version."""
    changes = {("included", membership) for membership in newly_included}
    changes.update(("excluded", membership) for membership in newly_excluded)
    canonical_changes = sorted(changes)
    manifest = {
        "domain": _LEGACY_DIFF_DOMAIN,
        "version": _LEGACY_DIFF_VERSION,
        "changes": [
            {
                "direction": direction,
                "destination": membership.destination,
                "file_type": membership.file_type,
            }
            for direction, membership in canonical_changes
        ],
    }
    encoded_manifest = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded_manifest).hexdigest()}"


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
        name,
        context=f"deployment source {os.fspath(source)!r}",
        error_type=DeploymentPlanError,
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
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        for character in normalized
    ):
        raise error_type(f"Control and format characters are unsupported in {context}.")
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


def _has_exclusion_at_or_below(
    destination_parts: tuple[str, ...], exclusions: _ExclusionIndex
) -> bool:
    """Return whether a literal exclusion is this directory or a descendant."""
    return exclusions.has_at_or_below(destination_parts)


def _reserved_kind(destination_parts: tuple[str, ...]) -> str | None:
    """Classify paths at or beneath non-overridable portable prefixes."""
    portable_parts = tuple(part.casefold() for part in destination_parts)
    root_name = portable_parts[0]
    if root_name == POLICY_FILENAME:
        return "policy"
    if any(part in _VCS_METADATA_NAMES for part in portable_parts):
        return "vcs"
    if root_name == "config.txt":
        return "configuration"
    if any(
        part == ".slugignore" or part.endswith(".dockerignore")
        for part in portable_parts
    ):
        return "backend-ignore"
    return None


def _require_posix_support(error_type: type[_ErrorType]) -> None:
    """Fail closed on non-POSIX platforms for this prototype."""
    if os.name != "posix":
        raise error_type(
            "Deployment planning currently requires a POSIX filesystem; "
            "Windows/reparse-point sources are not supported by this prototype."
        )


def _assert_no_symlink_components(
    path: Path,
    error_type: type[_ErrorType],
) -> None:
    """Reject absolute paths that traverse a symbolic-link component."""
    if not path.is_absolute():
        raise error_type(f"Deployment paths must be absolute: {path}.")

    accumulated = Path(path.anchor)
    for component in path.parts[1:]:
        accumulated /= component
        try:
            if accumulated.is_symlink():
                raise error_type(
                    f"Cannot open deployment path through symbolic link {accumulated}."
                )
        except OSError as error:
            raise error_type(
                f"Cannot inspect deployment path component {accumulated}: {error}"
            ) from error


def _assert_source_under_root(root: Path, source: Path) -> None:
    """Require a planned source path to remain inside its plan root."""
    try:
        relative_source = source.relative_to(root)
    except ValueError as error:
        raise DeploymentPlanError(
            f"Deployment source is outside its plan root: {source}."
        ) from error
    if not relative_source.parts or ".." in relative_source.parts:
        raise DeploymentPlanError(
            f"Deployment source is not a safe root-relative path: {source}."
        )


def _read_policy_snapshot(source: Path) -> _PolicySnapshot:
    """Parse and hash a policy file without following a final-component symlink."""
    try:
        source_stat = source.lstat()
    except OSError as error:
        raise DeploymentPolicyError(
            f"Cannot inspect deployment policy {source}: {error}"
        ) from error

    if stat.S_ISLNK(source_stat.st_mode):
        raise DeploymentPolicyError(
            f"Deployment policy {source} must not be a symbolic link."
        )
    if not stat.S_ISREG(source_stat.st_mode):
        raise DeploymentPolicyError(
            f"Deployment policy {source} must be a regular file."
        )

    try:
        content = source.read_bytes()
    except OSError as error:
        raise DeploymentPolicyError(
            f"Cannot read deployment policy {source}: {error}"
        ) from error

    content_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    try:
        policy_text = content.decode("utf-8")
        raw_policy = tomllib.loads(policy_text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DeploymentPolicyError(
            f"Invalid TOML in deployment policy {source}: {error}"
        ) from error
    return _PolicySnapshot(
        policy=_parse_policy(raw_policy),
        size=source_stat.st_size,
        mode=stat.S_IMODE(source_stat.st_mode),
        content_digest=content_digest,
    )


def _hash_regular_file(source: Path) -> str:
    """Hash a regular file's contents."""
    digest = hashlib.sha256()
    try:
        with source.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    except OSError as error:
        raise DeploymentPlanError(
            f"Cannot hash deployment source {source}: {error}"
        ) from error
    return f"sha256:{digest.hexdigest()}"


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
