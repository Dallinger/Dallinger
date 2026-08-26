"""Inspection commands for deploy.toml experiment-file selection."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from dallinger.deployment_plan import (
    POLICY_FILENAME,
    DeploymentPlan,
    DeploymentPlanError,
    DeploymentPolicyError,
    build_deployment_plan,
)

_STARTER_EXCLUSIONS = (
    ".deploy",
    "data",
    "deploy_logs",
    "develop",
    "local_only",
    "snapshots",
)

_STARTER_EXCLUDE_ANYWHERE = (
    "*.db",
    "*.dmg",
    ".env",
    ".venv",
    "__pycache__",
    "node_modules",
    "server.log",
)

_STARTER_POLICY = """\
# exclude entries are literal, root-relative prefixes.
# exclude_anywhere entries are literal basenames or *.suffix patterns
# matched in every directory. Other Git globs and negation are not supported.
version = 1

exclude = [
{exclusions}
]

exclude_anywhere = [
{anywhere}
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
    click.echo(f"Summary: {_file_count(len(plan.entries))}, {plan.total_size} bytes")


@deployment_files.command("init")
def init_deployment_files() -> None:
    """Create a starter deploy.toml without translating legacy rules."""
    root = Path.cwd()
    policy_path = root / POLICY_FILENAME
    if os.path.lexists(policy_path):
        raise click.ClickException(
            f"Refusing to overwrite existing deployment policy {policy_path}."
        )

    exclusions = _format_starter_list(_STARTER_EXCLUSIONS)
    anywhere = _format_starter_list(_STARTER_EXCLUDE_ANYWHERE)
    try:
        with policy_path.open("x", encoding="utf-8", newline="\n") as policy_file:
            policy_file.write(
                _STARTER_POLICY.format(exclusions=exclusions, anywhere=anywhere)
            )
    except OSError as error:
        raise click.ClickException(
            f"Cannot create deployment policy {policy_path}: {error}."
        ) from error

    click.echo(
        f"Created {policy_path}. Review exclude and exclude_anywhere paths "
        "before deploying."
    )


def _build_plan_or_fail(root: Path) -> DeploymentPlan:
    try:
        return build_deployment_plan(root)
    except (DeploymentPolicyError, DeploymentPlanError) as error:
        raise click.ClickException(str(error)) from error


def _file_count(count: int) -> str:
    return "1 file" if count == 1 else f"{count} files"


def _format_starter_list(values: tuple[str, ...]) -> str:
    """Format starter names as indented TOML string array entries."""
    return "\n".join(f'    "{value}",' for value in values)
