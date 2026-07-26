"""Inspection commands for the proposed deployment-file policy migration."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from dallinger.deployment_plan import (
    POLICY_FILENAME,
    DeploymentCompatibilityError,
    DeploymentMembership,
    DeploymentPlan,
    DeploymentPlanError,
    DeploymentPolicyError,
    LegacyDeploymentComparison,
    LegacySelectionError,
    acknowledge_legacy_deployment_comparison,
    build_deployment_plan,
    compare_legacy_deployment_selection,
)

_STARTER_EXCLUSIONS = (
    ".deploy",
    ".env",
    ".venv",
    "__pycache__",
    "data",
    "deploy_logs",
    "develop",
    "local_only",
    "node_modules",
    "server.log",
    "snapshots",
)

_STARTER_POLICY = """\
# Review this policy before deployment. Paths are literal, root-relative
# prefixes; Git globs and negation rules are not supported.
version = 1

# The migration checker adds legacy_diff_acknowledgement after path review.
exclude = [
{exclusions}
]
"""


@click.group("deployment-files")
def deployment_files():
    """Inspect and initialize deployment-file selection."""


@deployment_files.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
def list_deployment_files(json_output: bool) -> None:
    """List the deterministic target deployment plan."""
    plan = _build_plan_or_fail(Path.cwd())
    destinations = [entry.destination for entry in plan.entries]
    if json_output:
        click.echo(
            json.dumps(
                {
                    "destinations": destinations,
                    "file_count": len(plan.entries),
                    "manifest_digest": plan.manifest_digest,
                    "total_size": plan.total_size,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    for destination in destinations:
        click.echo(destination)
    click.echo(
        f"Summary: {_file_count(len(plan.entries))}, "
        f"{plan.total_size} bytes, manifest {plan.manifest_digest}"
    )


@deployment_files.command("check")
@click.option(
    "--acknowledge",
    is_flag=True,
    help="Record the reviewed newly-included membership digest in deploy.toml.",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
def check_deployment_files(acknowledge: bool, json_output: bool) -> None:
    """Compare target deployment files with legacy Git-based selection."""
    root = Path.cwd()
    plan = _build_plan_or_fail(root)
    try:
        comparison = compare_legacy_deployment_selection(plan)
    except LegacySelectionError as error:
        raise click.ClickException(str(error)) from error

    if json_output:
        payload = _comparison_payload(comparison)
        payload["acknowledgement_updated"] = acknowledge
        if acknowledge:
            _acknowledge_or_fail(comparison)
            payload["acknowledgement"]["configured"] = comparison.newly_included_digest
            payload["acknowledgement"]["matches"] = True
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _display_comparison(comparison)
        if acknowledge:
            _acknowledge_or_fail(comparison)
            click.echo(
                "Updated legacy_diff_acknowledgement in "
                f"{POLICY_FILENAME} to {comparison.newly_included_digest}."
            )

    if not acknowledge and not comparison.is_compatible:
        raise click.exceptions.Exit(1)


@deployment_files.command("init")
def init_deployment_files() -> None:
    """Create a review-required deploy.toml without translating legacy rules."""
    root = Path.cwd()
    policy_path = root / POLICY_FILENAME
    if os.path.lexists(policy_path):
        raise click.ClickException(
            f"Refusing to overwrite existing deployment policy {policy_path}."
        )

    exclusions = "\n".join(f'    "{value}",' for value in _STARTER_EXCLUSIONS)
    try:
        with policy_path.open("x", encoding="utf-8", newline="\n") as policy_file:
            policy_file.write(_STARTER_POLICY.format(exclusions=exclusions))
    except OSError as error:
        raise click.ClickException(
            f"Cannot create deployment policy {policy_path}: {error}"
        ) from error

    click.echo(f"Created review-required starter {POLICY_FILENAME}.")
    click.echo(
        "Git ignore patterns were not translated, including repository and "
        "user-global rules."
    )
    click.echo(
        "Legacy recursive basename rules were not translated, including *.db, "
        "*.dmg, data, node_modules, snapshots, server.log, and __pycache__; "
        "similarly named starter exclusions are root literals only."
    )
    click.echo(
        "Review all ignored/local files, reorganize non-literal rules into "
        "excluded directories where needed, edit deploy.toml, then run "
        "`dallinger deployment-files check`."
    )


def _build_plan_or_fail(root: Path) -> DeploymentPlan:
    """Build a target plan and convert planner errors to Click errors."""
    try:
        return build_deployment_plan(root)
    except (DeploymentPolicyError, DeploymentPlanError) as error:
        raise click.ClickException(str(error)) from error


def _acknowledge_or_fail(comparison: LegacyDeploymentComparison) -> None:
    """Write the comparison digest and convert policy errors to Click errors."""
    try:
        acknowledge_legacy_deployment_comparison(comparison)
    except (DeploymentPolicyError, DeploymentCompatibilityError) as error:
        raise click.ClickException(str(error)) from error


def _display_comparison(comparison: LegacyDeploymentComparison) -> None:
    """Display a content-free human-readable migration comparison."""
    _display_memberships("Newly included by target policy", comparison.newly_included)
    _display_memberships("Newly excluded by target policy", comparison.newly_excluded)
    if comparison.has_unresolved_backend_filters:
        click.echo(
            "Backend filter status: unsafe/unresolved. Source backend ignore "
            "controls are not compared:"
        )
        for path in comparison.unresolved_backend_ignore_controls:
            click.echo(f"  {path}")
        click.echo(
            "Migrate their filtering into deploy.toml and remove these files "
            "before acknowledging."
        )
    else:
        click.echo("Backend filter status: resolved")
    click.echo(f"Newly included digest: {comparison.newly_included_digest}")
    if comparison.has_unresolved_backend_filters:
        status = "blocked by unresolved backend filters"
    elif not comparison.requires_acknowledgement:
        status = "not required (no newly included files)"
    elif comparison.acknowledgement_matches:
        status = "matches"
    elif comparison.configured_acknowledgement is None:
        status = "missing"
    else:
        status = "mismatch"
    click.echo(f"Acknowledgement: {status}")
    if comparison.requires_acknowledgement:
        click.echo(
            "WARNING: The target policy includes paths omitted by legacy selection. "
            "Review these paths; file contents are not shown."
        )


def _display_memberships(
    heading: str, memberships: tuple[DeploymentMembership, ...]
) -> None:
    """Display sorted path/type memberships."""
    click.echo(f"{heading} ({len(memberships)}):")
    for membership in memberships:
        click.echo(f"  {membership.destination} [{membership.file_type}]")


def _comparison_payload(comparison: LegacyDeploymentComparison) -> dict:
    """Serialize a migration comparison for JSON output."""
    return {
        "acknowledgement": {
            "configured": comparison.configured_acknowledgement,
            "matches": comparison.acknowledgement_matches,
            "required": comparison.requires_acknowledgement,
        },
        "backend_filters": {
            "paths": list(comparison.unresolved_backend_ignore_controls),
            "status": (
                "unsafe/unresolved"
                if comparison.has_unresolved_backend_filters
                else "resolved"
            ),
        },
        "legacy_count": len(comparison.legacy),
        "newly_excluded": [
            _membership_payload(membership) for membership in comparison.newly_excluded
        ],
        "newly_included": [
            _membership_payload(membership) for membership in comparison.newly_included
        ],
        "newly_included_digest": comparison.newly_included_digest,
        "target_count": len(comparison.target),
    }


def _membership_payload(membership: DeploymentMembership) -> dict[str, str]:
    """Serialize one path/type membership."""
    return {
        "path": membership.destination,
        "type": membership.file_type,
    }


def _file_count(count: int) -> str:
    """Pluralize a file count for CLI output."""
    return f"{count} file" if count == 1 else f"{count} files"
