"""Build deterministic deployment manifests from an experiment directory.

This module turns a literal ``deploy.toml`` policy into an ordered plan of
regular experiment-root files. The ``[exclude]`` table has ``paths``
(root-relative prefixes), ``names`` (basenames in every directory), and
``suffixes`` (``.db``-style endings in every directory).
Generated outputs, framework providers, and backend materialization live
outside this module.

Traversal uses ordinary ``lstat`` / ``scandir`` checks (no symlink following).
Selected symlinks and special files are rejected. The working tree is trusted
between planning and materialization.
"""

from __future__ import annotations

import bisect
import os
import shutil
import stat
import tomllib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet, TypeVar

POLICY_FILENAME = "deploy.toml"
SCHEMA_VERSION = 1

_POLICY_KEYS = frozenset({"version", "exclude"})
_EXCLUDE_KEYS = frozenset({"paths", "names", "suffixes"})
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

_ErrorType = TypeVar("_ErrorType", bound=ValueError)


class DeploymentPolicyError(ValueError):
    """Raised when ``deploy.toml`` is missing, unsafe, or invalid."""


class DeploymentPlanError(ValueError):
    """Raised when an experiment tree cannot produce a safe deployment plan."""


@dataclass(frozen=True)
class DeploymentPolicy:
    """The validated, normalized contents of a version 1 ``deploy.toml``."""

    version: int
    exclude_paths: tuple[str, ...]
    exclude_names: tuple[str, ...]
    exclude_suffixes: tuple[str, ...]


@dataclass(frozen=True)
class DeploymentPlanEntry:
    """One regular experiment file selected for deployment."""

    source: Path
    destination: str
    size: int
    mode: int
    executable: bool


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
    """An immutable, deterministically ordered experiment-root plan."""

    root: Path
    policy: DeploymentPolicy
    entries: tuple[DeploymentPlanEntry, ...]
    destinations: frozenset[str]
    total_size: int
    directory_link_candidates: tuple[DeploymentDirectoryLinkCandidate, ...]

    def __contains__(self, destination: object) -> bool:
        """Return whether a normalized destination is present in the plan."""
        return isinstance(destination, str) and destination in self.destinations


@dataclass(frozen=True)
class _PolicySnapshot:
    policy: DeploymentPolicy
    size: int
    mode: int


@dataclass(frozen=True)
class _TraversedDirectoryCandidate:
    source: Path
    destination: str
    entry_count: int


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
    if not value or value.startswith("/"):
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
        _normalize_path_component(
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
        and normalized_parts[0] in _GENERATED_ROOT_DESTINATION_NAMES
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

    exclude_table = raw_policy["exclude"]
    if not isinstance(exclude_table, dict):
        raise DeploymentPolicyError(
            "Deployment policy exclude must be a table with paths, names, and suffixes."
        )
    unknown_exclude_keys = set(exclude_table) - _EXCLUDE_KEYS
    if unknown_exclude_keys:
        keys = ", ".join(sorted(unknown_exclude_keys))
        raise DeploymentPolicyError(f"Unknown exclude key(s): {keys}.")

    paths = _normalized_unique_strings(
        _optional_string_list(exclude_table, "paths"),
        validator=_validate_policy_path,
        duplicate_label="exclude.paths entry",
    )
    names = _normalized_unique_strings(
        _optional_string_list(exclude_table, "names"),
        validator=_validate_exclude_name,
        duplicate_label="exclude.names entry",
    )
    suffixes = _normalized_unique_strings(
        _optional_string_list(exclude_table, "suffixes"),
        validator=_validate_exclude_suffix,
        duplicate_label="exclude.suffixes entry",
    )

    return DeploymentPolicy(
        version=version,
        exclude_paths=tuple(sorted(paths)),
        exclude_names=tuple(sorted(names)),
        exclude_suffixes=tuple(sorted(suffixes)),
    )


def build_deployment_plan(
    experiment_root: str | os.PathLike[str],
) -> DeploymentPlan:
    """Build a deployment plan containing regular experiment-root files."""
    _require_posix_support(DeploymentPlanError)
    root = Path(os.path.abspath(os.fspath(experiment_root)))
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
    traversed_directory_candidates: list[_TraversedDirectoryCandidate] = []

    def register_destination(destination: str, source: Path) -> None:
        existing = normalized_sources.get(destination)
        if existing is not None and existing != source:
            raise DeploymentPlanError(
                "Source paths normalize to the same deployment destination "
                f"{destination!r}: {existing} and {source}."
            )
        normalized_sources[destination] = source

    def walk(
        directory: Path,
        destination_parts: tuple[str, ...],
    ) -> bool:
        """Traverse one directory and report whether all descendants are selected."""
        all_descendants_selected = not _has_exclusion_at_or_below(
            destination_parts, exclusions
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
                if _is_omitted_anywhere(name, anywhere_names, anywhere_suffixes):
                    all_descendants_selected = False
                    continue

                reserved_kind = _reserved_kind(child_destination_parts)
                if reserved_kind in {"backend-ignore", "policy", "configuration"}:
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
                    child_all_selected = walk(source, child_destination_parts)
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
                entries.append(
                    DeploymentPlanEntry(
                        source=source,
                        destination=destination,
                        size=source_stat.st_size,
                        mode=mode,
                        executable=bool(mode & 0o111),
                    )
                )
        return all_descendants_selected

    policy_snapshot = _read_policy_snapshot(root / POLICY_FILENAME)
    policy = policy_snapshot.policy
    exclusions = frozenset(policy.exclude_paths)
    anywhere_names = frozenset(policy.exclude_names)
    anywhere_suffixes = policy.exclude_suffixes
    policy_source = root / POLICY_FILENAME
    register_destination(POLICY_FILENAME, policy_source)
    entries.append(
        DeploymentPlanEntry(
            source=policy_source,
            destination=POLICY_FILENAME,
            size=policy_snapshot.size,
            mode=policy_snapshot.mode,
            executable=bool(policy_snapshot.mode & 0o111),
        )
    )
    walk(root, ())

    ordered_entries = tuple(sorted(entries, key=lambda entry: entry.destination))
    ordered_destinations = tuple(entry.destination for entry in ordered_entries)
    destinations = frozenset(ordered_destinations)
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
    return DeploymentPlan(
        root=root,
        policy=policy,
        entries=ordered_entries,
        destinations=destinations,
        total_size=total_size,
        directory_link_candidates=directory_link_candidates,
    )


def materialize_deployment_plan_entry(
    plan: DeploymentPlan,
    entry: DeploymentPlanEntry,
    destination: str | os.PathLike[str],
) -> None:
    """Copy one planned file into a trusted destination without overwriting."""
    target = Path(os.path.abspath(os.fspath(destination)))
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_source_under_root(plan.root, entry.source)
    if target.exists() or target.is_symlink():
        raise DeploymentPlanError(
            f"Cannot materialize deployment entry {entry.destination!r}: "
            f"destination already exists: {target}."
        )
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

    try:
        shutil.copyfile(entry.source, target, follow_symlinks=False)
        os.chmod(target, entry.mode)
    except OSError as error:
        target.unlink(missing_ok=True)
        raise DeploymentPlanError(
            f"Cannot materialize deployment entry {entry.destination!r}: {error}"
        ) from error


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


def _require_string_list(value: object, key: str) -> list[str]:
    """Require a TOML array of strings for one policy key."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DeploymentPolicyError(
            f"Deployment policy {key} must be an array of strings."
        )
    return value


def _optional_string_list(raw_policy: dict, key: str) -> list[str]:
    """Return one optional TOML string array, or an empty list if omitted."""
    if key not in raw_policy:
        return []
    return _require_string_list(raw_policy[key], key)


def _normalized_unique_strings(
    values: list[str],
    *,
    validator: Callable[[str], str],
    duplicate_label: str,
) -> list[str]:
    """Validate strings, reject normalized duplicates, and return them in order."""
    normalized_values: list[str] = []
    exact_entries: set[str] = set()
    for raw_value in values:
        normalized = validator(raw_value)
        if normalized in exact_entries:
            raise DeploymentPolicyError(
                f"Duplicate normalized {duplicate_label}: {normalized!r}."
            )
        exact_entries.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def _reject_unsupported_globs(
    value: str, *, where: str, reported: str | None = None
) -> None:
    """Reject Git-style glob characters in one policy field."""
    if any(character in _GLOB_CHARACTERS for character in value):
        raise DeploymentPolicyError(
            f"Glob syntax is unsupported in {where}: {(reported or value)!r}."
        )


def _validate_policy_path(value: str) -> str:
    """Validate and NFC-normalize one literal root-relative exclusion."""
    if not value:
        raise DeploymentPolicyError("Exclusion paths must not be empty.")
    if "\\" in value:
        raise DeploymentPolicyError(
            f"Exclusion paths must use POSIX separators: {value!r}."
        )
    if value.startswith("/"):
        raise DeploymentPolicyError(
            f"Exclusion paths must be relative to the experiment root: {value!r}."
        )
    if value.startswith("!"):
        raise DeploymentPolicyError(
            f"Negated exclusion paths are unsupported: {value!r}."
        )
    _reject_unsupported_globs(value, where="exclude.paths")

    components = value.split("/")
    if any(not component for component in components):
        raise DeploymentPolicyError(
            f"Exclusion paths must not contain empty components: {value!r}."
        )

    normalized_parts = tuple(
        _normalize_path_component(
            component,
            context=f"exclusion path {value!r}",
            error_type=DeploymentPolicyError,
        )
        for component in components
    )
    normalized = "/".join(normalized_parts)
    _reject_reserved_exclusion(normalized_parts)
    return normalized


def _validate_exclude_name(value: str) -> str:
    """Validate one basename omitted in every directory."""
    if not value:
        raise DeploymentPolicyError("exclude.names entries must not be empty.")
    if "/" in value or "\\" in value:
        raise DeploymentPolicyError(
            f"exclude.names entries must be a single path component: {value!r}."
        )
    if value.startswith("!"):
        raise DeploymentPolicyError(
            f"Negated exclude.names entries are unsupported: {value!r}."
        )
    _reject_unsupported_globs(value, where="exclude.names")
    normalized = _normalize_path_component(
        value,
        context=f"exclude.names entry {value!r}",
        error_type=DeploymentPolicyError,
    )
    _reject_reserved_exclusion((normalized,))
    return normalized


def _validate_exclude_suffix(value: str) -> str:
    """Validate one ``.db``-style suffix omitted in every directory."""
    if "/" in value or "\\" in value:
        raise DeploymentPolicyError(
            f"exclude.suffixes entries must be a single path component: {value!r}."
        )
    _reject_unsupported_globs(value, where="exclude.suffixes")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized.startswith(".")
        or normalized in {".", ".."}
        or len(normalized) < 2
    ):
        raise DeploymentPolicyError(
            f"exclude.suffixes entries must look like '.db': {value!r}."
        )
    _reject_reserved_exclusion((normalized,))
    return normalized


def _normalize_source_component(name: str, source: Path) -> str:
    """Normalize one filesystem name for use as a POSIX destination component."""
    return _normalize_path_component(
        name,
        context=f"deployment source {os.fspath(source)!r}",
        error_type=DeploymentPlanError,
    )


def _normalize_path_component(
    component: str,
    *,
    context: str,
    error_type: type[_ErrorType],
) -> str:
    """Validate and NFC-normalize one destination component."""
    normalized = unicodedata.normalize("NFC", component)
    if not normalized or normalized in {".", ".."}:
        raise error_type(f"Invalid path component in {context}: {component!r}.")
    return normalized


def _is_excluded(
    destination_parts: tuple[str, ...], exclusions: AbstractSet[str]
) -> bool:
    """Return whether any ancestor destination is excluded."""
    return any(
        "/".join(destination_parts[:depth]) in exclusions
        for depth in range(1, len(destination_parts) + 1)
    )


def _has_exclusion_at_or_below(
    destination_parts: tuple[str, ...], exclusions: AbstractSet[str]
) -> bool:
    """Return whether a literal exclusion is this directory or a descendant."""
    if not exclusions:
        return False
    if not destination_parts:
        return True
    destination = "/".join(destination_parts)
    if destination in exclusions:
        return True
    prefix = destination + "/"
    return any(item.startswith(prefix) for item in exclusions)


def _reject_reserved_exclusion(destination_parts: tuple[str, ...]) -> None:
    """Reject exclusions that target required or reserved destinations."""
    if _reserved_kind(destination_parts) is None:
        return
    raise DeploymentPolicyError(
        "Deployment policy cannot exclude required or reserved path "
        f"{'/'.join(destination_parts)!r}."
    )


def _is_omitted_anywhere(
    name: str,
    anywhere_names: AbstractSet[str],
    anywhere_suffixes: tuple[str, ...],
) -> bool:
    """Return whether a basename is omitted in every directory."""
    return name in anywhere_names or bool(
        anywhere_suffixes and name.endswith(anywhere_suffixes)
    )


def _reserved_kind(destination_parts: tuple[str, ...]) -> str | None:
    """Classify paths at or beneath non-overridable prefixes."""
    root_name = destination_parts[0]
    if root_name == POLICY_FILENAME:
        return "policy"
    if any(part in _VCS_METADATA_NAMES for part in destination_parts):
        return "vcs"
    if root_name == "config.txt":
        return "configuration"
    if root_name in _GENERATED_ROOT_DESTINATION_NAMES:
        return "generated"
    if any(
        part == ".slugignore" or part.endswith(".dockerignore")
        for part in destination_parts
    ):
        return "backend-ignore"
    return None


def _require_posix_support(error_type: type[_ErrorType]) -> None:
    """Fail closed on non-POSIX platforms for this prototype."""
    if os.name != "posix":
        raise error_type("Deployment planning currently requires a POSIX filesystem.")


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
    """Parse a policy file without following a final-component symlink."""
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
    )


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
