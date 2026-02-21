import logging
import time
from datetime import datetime

import click
from rich.text import Text

from dallinger.command_line.utils import render_rich_table

logger = logging.getLogger(__name__)


# Prolific-specific commands
@click.group("prolific")
@click.pass_context
def prolific(ctx):
    """Sub-commands for Prolific"""
    pass


@prolific.command("delete-drafts")
@click.pass_context
def delete_drafts(ctx):
    """Delete all draft studies"""
    from dallinger.prolific import prolific_service_from_config

    logger.info("Deleting all draft studies...")
    prolific_service = prolific_service_from_config()
    studies = prolific_service.get_studies()
    studies_to_delete = [study for study in studies if study["status"] == "UNPUBLISHED"]

    if not click.confirm(
        f"Are you sure you want to remove {len(studies_to_delete)} draft studies? Y/n"
    ):
        logger.info("Operation cancelled by the user.")
        return
    for study in studies_to_delete:
        prolific_service.delete_study(study["id"])
        logger.info(f"Deleted study {study['id']} ({study['internal_name']})")


@prolific.group("list")
@click.pass_context
def list_commands(ctx):
    """Sub-commands for listing Prolific entities"""
    pass


@list_commands.command("workspaces")
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

    headers = (
        [key for key in filtered_workspaces_data[0].keys()]
        if filtered_workspaces_data
        else []
    )
    rows = [
        [row.get(header, "") for header in headers] for row in filtered_workspaces_data
    ]
    print(render_rich_table(rows, headers=headers))


sort_by_choices = ["date_created", "total_cost"]


@list_commands.command("studies")
@click.option(
    "--sort_by",
    default=None,
    help=f"Sort by this column. Select from {sort_by_choices}",
)
@click.option("--published", is_flag=True, help="Only include published studies")
@click.pass_context
def list_studies(ctx, sort_by, published):
    """List Prolific studies"""
    from dallinger.prolific import prolific_service_from_config

    logger.info("Getting studies...")
    if sort_by is not None:
        assert sort_by in sort_by_choices
    studies = prolific_service_from_config().get_studies()
    msg = f"Found {len(studies)} studies"
    if sort_by is not None:
        msg += f" sorted by {sort_by}"
    logger.info(msg)
    filtered_studies = []
    for study in studies:
        if published and study["number_of_submissions"] == 0:
            continue
        date = study["date_created"]
        date = date.split(".")[0]
        if date.endswith("Z"):
            date = date[:-1]
        study["date_created"] = time.mktime(time.strptime(date, "%Y-%m-%dT%H:%M:%S"))
        pct = study["number_of_submissions"] / study["total_available_places"]
        study["cost"] = study["total_cost"] * pct
        filtered_studies.append(study)

    if sort_by is not None:
        filtered_studies.sort(key=lambda x: x[sort_by], reverse=True)

    def format_cost(cost):
        return f"£{cost / 100:.2f}"

    formatted_studies = []
    for study in filtered_studies:
        cost_cell = Text(format_cost(study["cost"]))
        if study["is_underpaying"]:
            cost_cell.append(" (underpaying)", style="bold red")
        submission_string = (
            f"{study['number_of_submissions']} / {study['total_available_places']}"
        )
        formatted_study = {
            "id": study["id"],
            "internal_name": study["internal_name"],
            "status": study["status"],
            "date": datetime.fromtimestamp(study["date_created"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "submissions": submission_string,
            "cost": cost_cell,
        }
        formatted_studies.append(formatted_study)

    formatted_studies.append(
        {
            "cost": Text(
                format_cost(sum(study["cost"] for study in filtered_studies)),
                style="bold",
            ),
        }
    )

    headers = [key for key in formatted_studies[0].keys()] if formatted_studies else []
    rows = [[row.get(header, "") for header in headers] for row in formatted_studies]
    print(render_rich_table(rows, headers=headers))
