import inspect
import os
import re
import sys
import tempfile
from functools import wraps

import click

from dallinger.config import get_config, initialize_experiment_package
from dallinger.utils import ExperimentFileSource
from dallinger.version import __version__

header = r"""
    ____        ____
   / __ \____ _/ / (_)___  ____ ____  _____
  / / / / __ `/ / / / __ \/ __ `/ _ \/ ___/
 / /_/ / /_/ / / / / / / / /_/ /  __/ /
/_____/\__,_/_/_/_/_/ /_/\__, /\___/_/
                        /____/
                                 {:>8}

                Laboratory automation for
       the behavioral and social sciences.
""".format(
    "v" + __version__
)


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
    def wrapper(*args, **kwargs):
        try:
            if not verify_package(kwargs.get("verbose")):
                raise click.UsageError(error_one)
        except ValueError:
            raise click.UsageError(error_two)
        return f(*args, **kwargs)

    return wrapper


def verify_package(verbose=True):
    """Perform a series of checks on the current directory to verify that
    it's a valid Dallinger experiment.
    """
    results = (
        verify_directory(verbose),
        verify_experiment_module(verbose),
        verify_config(verbose),
        verify_no_conflicts(verbose),
    )

    ok = all(results)

    return ok


def verify_directory(verbose=True, max_size_mb=50):
    """Ensure that the current directory looks like a Dallinger experiment, and
    does not appear to have unintended contents that will be copied on
    deployment.
    """
    # Check required files
    ok = True
    mb_to_bytes = 1000 * 1000
    expected_files = ["config.txt", "experiment.py"]

    for f in expected_files:
        if os.path.exists(f):
            log("✓ {} is PRESENT".format(f), chevrons=False, verbose=verbose)
        else:
            log("✗ {} is MISSING".format(f), chevrons=False, verbose=verbose)
            ok = False

    # Check size
    max_size = max_size_mb * mb_to_bytes
    file_source = ExperimentFileSource(os.getcwd())
    size = file_source.size
    size_in_mb = round(size / mb_to_bytes)
    if size <= max_size:
        log(
            "✓ Size OK at {}MB (max is {}MB)".format(size_in_mb, max_size_mb),
            chevrons=False,
            verbose=verbose,
        )
    else:
        log(
            "✗ {}MB is TOO BIG (greater than {}MB)\n\tIncluded files:\n\t{}".format(
                size_in_mb, max_size_mb, "\n\t".join(file_source.files)
            ),
            chevrons=False,
            verbose=verbose,
        )
        ok = False

    return ok


def verify_experiment_module(verbose):
    """Perform basic sanity checks on experiment.py."""
    ok = True
    if not os.path.exists("experiment.py"):
        return False

    # Bootstrap a package in a temp directory and make it importable:
    temp_package_name = "TEMP_VERIFICATION_PACKAGE"
    tmp = tempfile.mkdtemp()
    clone_dir = os.path.join(tmp, temp_package_name)
    ExperimentFileSource(os.getcwd()).apply_to(clone_dir)
    initialize_experiment_package(clone_dir)
    from dallinger_experiment import experiment

    if clone_dir not in experiment.__file__:
        raise ImportError("Checking the wrong experiment.py... aborting.")
    classes = inspect.getmembers(experiment, inspect.isclass)
    exps = [c for c in classes if (c[1].__bases__[0].__name__ in "Experiment")]

    # Clean up:
    for entry in [k for k in sys.modules if temp_package_name in k]:
        del sys.modules[entry]

    # Run checks:
    if len(exps) == 0:
        log(
            "✗ experiment.py does not define an experiment class.",
            chevrons=False,
            verbose=verbose,
        )
        ok = False
    elif len(exps) == 1:
        log(
            "✓ experiment.py defines 1 experiment",
            chevrons=False,
            verbose=verbose,
        )
    else:
        log(
            "✗ experiment.py defines more than one experiment class.",
            chevrons=False,
            verbose=verbose,
        )
        ok = False

    # Check for overrides of methods with name changes:
    api_breakages = {
        # "old name": "new name"
        "on_assignment_submitted_to_recruiter": "on_recruiter_submission_complete",
    }
    try:
        exp_class = exps[0][1]
    except IndexError:
        pass
    else:
        for old, new in api_breakages.items():
            if hasattr(exp_class, old):
                log(
                    "✗ experiment.py overrides a method that has been renamed!\n"
                    "\tOld name: {}\n\tNew name: {}\n"
                    "Please rename your method accordingly.".format(old, new),
                    chevrons=False,
                    verbose=verbose,
                )
                ok = False

    return ok


def verify_config(verbose=True):
    """Check for common or costly errors in experiment configuration."""
    ok = True
    config = get_config()
    if not config.ready:
        try:
            config.load()
        except ValueError as e:
            config_key = getattr(e, "dallinger_config_key", None)
            if config_key is not None:
                message = "Configuration for {} is invalid: ".format(config_key)
            else:
                message = "Configuration is invalid: "
            log("✗ " + message + str(e), chevrons=False, verbose=verbose)

            config_value = getattr(e, "dallinger_config_value", None)
            if verbose and config_value:
                log("  Value supplied was " + config_value, chevrons=False)
            return False
    # Check base_payment is correct
    try:
        base_pay = config.get("base_payment")
    except KeyError:
        log("✗ No value for base_pay.", chevrons=False, verbose=verbose)
    else:
        dollarFormat = "{:.2f}".format(base_pay)

        if base_pay < 0:
            log(
                "✗ base_payment must be greater than or equal to zero in config.txt.",
                chevrons=False,
                verbose=verbose,
            )
            ok = False

        if float(dollarFormat) != float(base_pay):
            log(
                "✗ base_payment must be in [dollars].[cents] format in config.txt. Try changing "
                "{0} to {1}.".format(base_pay, dollarFormat),
                chevrons=False,
                verbose=verbose,
            )
            ok = False

    return ok


def verify_no_conflicts(verbose=True):
    """Warn if there are filenames which conflict with those deployed by
    Dallinger, but always returns True (meaning "OK").
    """
    conflicts = False

    reserved_files = [
        os.path.join("templates", "error.html"),
        os.path.join("templates", "error-complete.html"),
        os.path.join("templates", "exit_recruiter_mturk.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("static", "css", "dallinger.css"),
        os.path.join("static", "scripts", "dallinger2.js"),
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("static", "scripts", "store+json2.min.js"),
        os.path.join("static", "scripts", "tracker.js"),
        os.path.join("static", "robots.txt"),
    ]

    for f in reserved_files:
        if os.path.exists(f):
            log(
                "✗ {} OVERWRITES shared frontend files inserted at run-time".format(f),
                chevrons=False,
                verbose=verbose,
            )
            conflicts = True

    if not conflicts:
        log("✓ no file conflicts", chevrons=False, verbose=verbose)

    return True


def check_valid_subdomain(param_name, param_value):
    """Check if the subdomain is valid."""
    if not re.match(r"^[a-z0-9-]+$", param_value):
        raise click.BadParameter(
            f"The --{param_name} parameter contains invalid characters. The only characters allowed are: a-z, 0-9, and '-'."
        )


def verify_id(ctx, param, app):
    """Verify the experiment id."""
    if app is None:
        raise click.BadParameter("Select an experiment using the --app parameter.")
    elif app[0:5] == "dlgr-":
        raise click.BadParameter(
            "The --app parameter requires the full "
            "UUID beginning with {}-...".format(app[5:23])
        )
    check_valid_subdomain("app", app)
    return app


def run_pre_launch_checks(**kwargs):
    from dallinger.recruiters import by_name

    recruiter_name = kwargs["config"].get("recruiter", None)
    if recruiter_name is not None:
        log(f"Validating config for {recruiter_name} recruitment...")
        by_name(recruiter_name).validate_config(**kwargs)


# Ported from PsyNet
def user_confirms(question, default=False):
    """
    Like click.confirm but safe for using within our wrapped Docker commands.
    """
    print(question + " Enter 'y' for yes, 'n' for no.")
    return click.confirm("", default=default)
