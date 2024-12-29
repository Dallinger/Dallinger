import logging

import click
from tabulate import tabulate

logger = logging.getLogger(__name__)


# Prolific-specific commands
@click.group("prolific")
@click.pass_context
def prolific(ctx):
    """Sub-commands for Prolific"""
    pass


@prolific.group("list")
@click.pass_context
def list(ctx):
    """Sub-commands for listing Prolific entities"""
    pass


@list.command("workspaces")
@click.option(
    "--show-all-columns",
    is_flag=True,
    flag_value=True,
    help="Display all workspace columns returned from the Prolific API",
)
@click.pass_context
def list_workspaces(ctx, show_all_columns):
    """List Prolific workspaces"""
    from dallinger.prolific import prolific_service_from_config

    logger.info("Getting workspaces...")
    columns_to_exclude = []
    if not show_all_columns:
        columns_to_exclude = [
            "cloud_marketplace_account",
            "naivety_distribution_rate",
            "users",
        ]
    filtered_workspaces_data = [
        {k: v for k, v in row.items() if k not in columns_to_exclude}
        for row in prolific_service_from_config().get_workspaces()
    ]

    print(tabulate(filtered_workspaces_data, headers="keys", tablefmt="github"))
