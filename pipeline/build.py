"""Pipeline entry point: python -m pipeline.build [--mock]

Loads inputs, computes popularity, market value and verdicts, validates,
and writes site/data/games.json. Implemented in milestone 3.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.build", description=__doc__)
    parser.add_argument("--mock", action="store_true", help="read placeholder inputs from data/mock/ instead of data/raw/")
    parser.parse_args(argv)
    print("pipeline.build is not implemented yet (milestone 3).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
