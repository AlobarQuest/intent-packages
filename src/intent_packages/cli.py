"""CLI: validate / hash / transition / approve / revise / supersede / verify-approval."""

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="intent_packages", description=__doc__)
    parser.add_subparsers(dest="cmd", required=True)
    parser.parse_args(argv)
    return 0
