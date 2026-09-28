"""qdojo command line: `qdojo combat ...`.

The riddle game's commands (house, bot, train, riddle, payload, doc, prompts)
were removed on 2026-09-28; they live at tag riddle-v0-final.
"""
import argparse
import sys

from . import __version__, portable
from .combat import cli as combat_cli
from .combat.training import ReplayMismatch
from .combat.types import PlanError, StateError


def build_parser():
    p = argparse.ArgumentParser(prog="qdojo", description="QDOJO: AI fighters in a combat dojo on Qubic.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    combat_cli.add_parser(sub)
    return p


def main(argv=None):
    portable.tolerant_stdio()      # a redirected Windows stdout must not die on a tick mark
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except (RuntimeError, ReplayMismatch, PlanError, StateError) as e:
        sys.exit(f"qdojo: {e}")


if __name__ == "__main__":
    main()
