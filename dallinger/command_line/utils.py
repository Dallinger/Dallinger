from functools import wraps

import click


def log(msg, chevrons=True, verbose=True, **kw):
    """Log a message to stdout."""
    if verbose:
        if chevrons:
            click.echo("\n❯❯ " + msg, **kw)
        else:
            click.echo(msg, **kw)


def error(msg, chevrons=True, verbose=True):
    """Log a message to stdout."""
    if verbose:
        if chevrons:
            click.secho("\n❯❯ " + msg, err=True, fg="red")
        else:
            click.secho(msg, err=True, fg="red")


class Output(object):
    """Utility Output class used by click CLI commands"""

    def __init__(self, log=log, error=error, blather=None):
        self.log = log
        self.error = error
        if blather is None:
            blather = sys.stdout.write
        self.blather = blather


def require_exp_directory(f):
    """Decorator to verify that a command is run inside a valid Dallinger
    experiment directory.
    """
    error_one = "The current directory is not a valid Dallinger experiment."
    error_two = "There are problems with the current experiment. Please check with dallinger verify."

    @wraps(f)
    def wrapper(**kwargs):
        try:
            if not verify_package(kwargs.get("verbose")):
                raise click.UsageError(error_one)
        except ValueError:
            raise click.UsageError(error_two)
        return f(**kwargs)

    return wrapper
