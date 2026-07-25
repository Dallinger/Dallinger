"""Isolated entry point for staged experiment verification."""

import argparse
import traceback

from dallinger.command_line.utils import _verify_experiment_module


def main():
    """Verify one staged experiment and return a process exit code."""
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_directory")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        valid = _verify_experiment_module(
            verbose=not args.quiet,
            experiment_directory=args.experiment_directory,
            experiment_is_staged=True,
        )
    except Exception:
        traceback.print_exc()
        return 4
    return 0 if valid else 3


if __name__ == "__main__":
    raise SystemExit(main())
