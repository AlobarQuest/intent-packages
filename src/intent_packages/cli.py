"""CLI: validate / hash / transition / approve / revise / supersede / verify-approval."""

import argparse
import subprocess
import sys
from datetime import UTC, datetime
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
    p_transition = sub.add_parser("transition", help="transition a package to a new state")
    p_transition.add_argument("path")
    p_transition.add_argument("--to", required=True, dest="to_state", help="target state")
    p_approve = sub.add_parser("approve", help="approve a package (ready_for_review -> approved)")
    p_approve.add_argument("path")
    p_approve.add_argument("--approver", default="devon", help="approver identity (default: devon)")
    p_revise = sub.add_parser("revise", help="revise a package to a new, unapproved revision")
    p_revise.add_argument("path")
    p_supersede = sub.add_parser("supersede", help="mark a package superseded by another package")
    p_supersede.add_argument("path")
    p_supersede.add_argument(
        "--by", required=True, dest="new_package_id", help="the superseding package_id"
    )
    args = parser.parse_args(argv)
    if args.cmd == "hash":
        from intent_packages.canonical import package_hash
        from intent_packages.loader import load_package

        print(package_hash(load_package(args.path)))
        return 0
    if args.cmd == "validate":
        return _run_validate(parser, args)
    if args.cmd == "transition":
        return _run_transition(args)
    if args.cmd == "approve":
        return _run_approve(args)
    if args.cmd == "revise":
        return _run_revise(args)
    if args.cmd == "supersede":
        return _run_supersede(args)
    return 0


def _git_head_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _run_transition(args) -> int:
    from intent_packages.emitter import EmitError, FactoryEventsEmitter
    from intent_packages.operations import OperationError, do_transition

    now = datetime.now(UTC).isoformat()
    try:
        do_transition(
            args.path, args.to_state, emitter=FactoryEventsEmitter(), now=now
        )
    except (OperationError, EmitError) as exc:
        print(f"transition failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.path}: transitioned to {args.to_state}")
    return 0


def _run_approve(args) -> int:
    from intent_packages.emitter import EmitError, FactoryEventsEmitter
    from intent_packages.operations import OperationError, do_approve

    now = datetime.now(UTC).isoformat()
    try:
        commit = _git_head_commit()
        do_approve(
            args.path,
            emitter=FactoryEventsEmitter(),
            approver=args.approver,
            commit=commit,
            now=now,
        )
    except (OperationError, EmitError, subprocess.CalledProcessError) as exc:
        print(f"approve failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.path}: approved by {args.approver}")
    return 0


def _run_revise(args) -> int:
    from intent_packages.emitter import EmitError, FactoryEventsEmitter
    from intent_packages.operations import OperationError, do_revise

    now = datetime.now(UTC).isoformat()
    try:
        do_revise(args.path, emitter=FactoryEventsEmitter(), now=now)
    except (OperationError, EmitError) as exc:
        print(f"revise failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.path}: revised")
    return 0


def _run_supersede(args) -> int:
    from intent_packages.emitter import EmitError, FactoryEventsEmitter
    from intent_packages.operations import OperationError, do_supersede

    now = datetime.now(UTC).isoformat()
    try:
        do_supersede(
            args.path, args.new_package_id, emitter=FactoryEventsEmitter(), now=now
        )
    except (OperationError, EmitError) as exc:
        print(f"supersede failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.path}: superseded by {args.new_package_id}")
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
