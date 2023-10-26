import click


@click.group("heroku")
@click.pass_context
def heroku():
    """Utility commands for Heroku."""
    pass


@heroku.command("hibernate")
def heroku__hibernate():
    """Put the Heroku app to sleep to pause an experiment and remove costly resources."""
    # TODO: this is a stub
    pass


@heroku.command("summary")
def heroku__summary():
    """Get a summary of all Heroku apps."""
    # TODO: this is a stub
    pass
