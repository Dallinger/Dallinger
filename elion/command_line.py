#!/usr/bin/python
# -*- coding: utf-8 -*-

"""The Elion command-line utility."""

import click
from elion.version import __version__
import time
import yaml

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


def print_header():
    """Print a fancy-looking header."""
    log("""
     __
    |_  |  o  _ __
    |__ |  | (_)| |
    """, 0.5, False)


def log(msg, delay=0.5, chevrons=True, verbose=True):
    """Log a message to stdout."""
    if verbose:
        if chevrons:
            click.echo("\n❯❯ " + msg)
        else:
            click.echo(msg)
        time.sleep(delay)


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, '--version', '-v', message='%(version)s')
def elion():
    """Set up Elion as a name space."""
    pass


@elion.command()
def run():
    """Run Elion."""
    print_header()
    log("Running...")

    config_filename = "elion.yml"

    try:
        with open(config_filename, 'rb') as f:
            yml = yaml.load(f.read())
            print(yml)
    except Exception as e:
        print(e)

    # subprocess.call("dallinger sandbox", shell=True)
    # print(os.getcwd())
