"""The quantic-agent command.

At milestone 1 it has no tasks to run. It exists so the project installs a
command, and the shape every later option fits into is in place.
"""

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the command and returns its exit status.

    argv defaults to the process's own arguments; tests pass their own. A
    usage mistake, --help and --version end the run from inside argparse by
    raising SystemExit (2 for a mistake, 0 for the others), which unwinds
    through every finally block on its way out.
    """
    parser = argparse.ArgumentParser(
        prog="quantic-agent",
        description="Drafts data-grounded content for Quantic with a local model.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('quantic-agent')}",
    )
    parser.parse_args(argv)

    print("quantic-agent: no tasks defined yet")
    return 0
