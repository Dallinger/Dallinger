import logging

import click

from dallinger.command_line.utils import Output

logger = logging.getLogger(__file__)

study_id = click.argument(
    "study_id",
    required=True,
    type=str,
)

response_id = click.option(
    "--response_id",
    help="Response ID of the participant",
    required=True,
    type=str,
)


@click.group()
@click.pass_context
def prolific(ctx):
    """Utility commands to interact with Prolific."""
    pass


@prolific.command("compensate")
@study_id
@response_id
def prolific__compensate(study_id, response_id):
    """Compensate participants on Prolific."""
    # TODO: this is a stub
    pass


@prolific.command("copy-qualifications")
@study_id
def prolific__copy_qualifications():
    """Copy qualifications from a Prolific study."""
    # TODO: this is a stub
    pass


@prolific.command("pause")
@study_id
def prolific__pause(study_id):
    """Pause a Prolific study."""
    # TODO: this is a stub
    pass


@prolific.command("resume")
@study_id
def prolific__resume(study_id):
    """Resume a Prolific study."""
    pass


@prolific.command("stop")
@study_id
def prolific__stop(study_id):
    """Stop a Prolific study."""
    out = Output()
    out.log("Stopping study {} on Prolific...".format(study_id))
    if not click.confirm("Are you sure you turned off auto-recruitment on your study?"):
        out.log("Aborting...")
        return
    # TODO: this is a stub
    pass


@prolific.command("details")
@study_id
def prolific__details(study_id):
    """Get details of a study."""
    # TODO: this is a stub
    pass


@prolific.command("studies")
@click.option("--running", is_flag=True, help="Only show running studies")
def prolific__studies(running):
    """List studies on prolific."""
    # TODO: this is a stub
    pass


@prolific.command("approve")
@study_id
@response_id
def prolific__approve(study_id, response_id):
    """Manually approve a participant. For example if someone timed out."""
    # TODO: this is a stub
    pass


@prolific.command("cost")
@study_id
def prolific__cost(hit_id):
    """Get the cost of a study."""
    # TODO: This must be implemented in the service.
    pass
