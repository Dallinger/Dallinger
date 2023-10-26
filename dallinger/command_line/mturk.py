import click

hit_id = click.argument(
    "hit_id",
    required=True,
    type=str,
)


@click.group()
@click.pass_context
def mturk(ctx):
    """Utility commands to interact with Mechanical Turk."""
    pass


@mturk.command("compensate")
def mturk__compensate():
    """Compensate participants on Mechanical Turk."""
    # TODO: this is a stub
    pass


@mturk.command("copy-qualifications")
def mturk__copy_qualifications():
    """Copy qualifications from a mturk HIT."""
    # TODO: this is a stub
    pass


@mturk.command("expire")
def mturk__expire():
    """Expire a HIT."""
    # TODO: this is a stub
    pass


@mturk.command("extend")
def mturk__extend():
    """Extend a HIT."""
    # TODO: this is a stub
    pass


@mturk.command("details")
def mturk__details():
    """Get details of a HIT."""
    # TODO: this is a stub
    pass


@mturk.command("studies")
@click.option("--running", is_flag=True, help="Only show running studies")
def mturk__studies():
    """List studies on Mechanical Turk."""
    # TODO: this is a stub
    pass


@mturk.command("qualify")
def mturk__qualify():
    """Qualify participants on Mechanical Turk."""
    # TODO: this is a stub
    pass


@mturk.command("revoke")
def mturk__revoke():
    """Revoke a qualification from a participant."""
    # TODO: this is a stub
    pass


@mturk.command("cost")
@hit_id
def mturk__cost(hit_id):
    """Get the cost of a HIT."""
    # TODO: This must be implemented in the service.
    pass
