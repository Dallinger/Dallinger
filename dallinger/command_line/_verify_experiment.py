"""Isolated entry point for staged experiment verification."""

import argparse

from dallinger.command_line.utils import _verify_experiment_module


def main():
    """Verify one staged experiment and return a process exit code."""
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_directory")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    valid = _verify_experiment_module(
        verbose=not args.quiet,
        experiment_directory=args.experiment_directory,
    )
    return 0 if valid else 3


if __name__ == "__main__":
    raise SystemExit(main())
