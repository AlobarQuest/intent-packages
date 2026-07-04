"""CLI: validate / hash / transition / approve / revise / supersede / verify-approval."""

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="intent_packages", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_hash = sub.add_parser("hash", help="print sha256(JCS(intent_core)) of a package")
    p_hash.add_argument("path")
    args = parser.parse_args(argv)
    if args.cmd == "hash":
        from intent_packages.canonical import package_hash
        from intent_packages.loader import load_package

        print(package_hash(load_package(args.path)))
        return 0
    return 0
