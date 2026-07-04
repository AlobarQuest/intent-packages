"""CLI: validate / hash / transition / approve / revise / supersede / verify-approval."""

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="intent_packages", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_hash = sub.add_parser("hash", help="print sha256(JCS(intent_core)) of a package")
    p_hash.add_argument("path")
    p_validate = sub.add_parser("validate", help="validate a package (or every packages/*/)")
    p_validate.add_argument("path", nargs="?", help="path to a package directory")
    p_validate.add_argument(
        "--all", action="store_true", help="validate every packages/*/ directory"
    )
    args = parser.parse_args(argv)
    if args.cmd == "hash":
        from intent_packages.canonical import package_hash
        from intent_packages.loader import load_package

        print(package_hash(load_package(args.path)))
        return 0
    if args.cmd == "validate":
        return _run_validate(parser, args)
    return 0


def _run_validate(parser: argparse.ArgumentParser, args) -> int:
    from intent_packages.validate import validate_package, validate_warnings

    if args.all:
        base = Path("packages")
        pkg_dirs = sorted(p for p in base.glob("*") if p.is_dir()) if base.is_dir() else []
        if not pkg_dirs:
            print("no packages found under packages/")
            return 0
        any_errors = False
        for pkg_dir in pkg_dirs:
            for warning in validate_warnings(pkg_dir):
                print(f"{pkg_dir}: {warning}", file=sys.stderr)
            errors = validate_package(pkg_dir)
            if errors:
                any_errors = True
                print(f"{pkg_dir}:")
                for error in errors:
                    print(f"  {error}")
            else:
                print(f"{pkg_dir}: OK")
        return 1 if any_errors else 0

    if not args.path:
        parser.error("validate requires a path, or --all")

    for warning in validate_warnings(args.path):
        print(warning, file=sys.stderr)
    errors = validate_package(args.path)
    for error in errors:
        print(error)
    return 1 if errors else 0
