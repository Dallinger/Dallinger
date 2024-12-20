import logging

import click
from tabulate import tabulate

from dallinger.config import get_config
from dallinger.prolific import ProlificService
from dallinger.version import __version__

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
def list__workspaces(ctx, show_all_columns):
    """List Prolific workspaces"""
    logger.info("Getting workspaces...")
    workspaces_data = get_workspaces()["results"]

    columns_to_exclude = []
    if not show_all_columns:
        columns_to_exclude = [
            "cloud_marketplace_account",
            "naivety_distribution_rate",
            "users",
        ]
    filtered_workspaces_data = [
        {k: v for k, v in row.items() if k not in columns_to_exclude}
        for row in workspaces_data
    ]

    print(tabulate(filtered_workspaces_data, headers="keys", tablefmt="github"))


def get_workspaces():
    config = get_config()
    config.load()
    prolificservice = ProlificService(
        api_token=config.get("prolific_api_token"),
        api_version=config.get("prolific_api_version"),
        referer_header=f"https://github.com/Dallinger/Dallinger/v{__version__}",
    )
    workspaces = prolificservice._req(
        method="GET", endpoint="/workspaces/?limit=1000"
    )  # without the limit param the number workspaces returned would be limited to 20
    return workspaces
