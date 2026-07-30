"""`factory` CLI front door (WS-P2.9). Subcommands: decompose, route, create,
validate, submit, status, evidence, ready, dispatch, verify.

Mirrors intent_packages.cli: main(argv) -> int, argparse subparsers, lazy
per-subcommand imports.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print method, path and status for every orchestrator API call (never a token)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser(
        "decompose", help="author + validate a dependency-update decomposition proposal"
    )
    p.add_argument("--revision", required=True, help="intaken package revision id")
    p.add_argument("--ac", required=True, help="acceptance criterion human id, e.g. AC-002")
    p.add_argument("--target-repo", required=True, help="GitHub slug, e.g. AlobarQuest/brain")
    p.add_argument(
        "--repo-path", default="", help="local checkout path (default: ~/Projects/<repo>)"
    )
    p.add_argument("--tooling", required=True, choices=("pip", "uv", "npm"))
    p.add_argument("--package", required=True, help="dependency name")
    p.add_argument("--from", dest="from_version", required=True, help="current pinned version")
    p.add_argument("--to", dest="to_version", required=True, help="target version")
    p.add_argument("--unit-key", default="", help="proposed unit key (default: derived from --ac)")
    p.add_argument("--rationale", default="", help="retained-AC rationale (default: auto)")
    p.add_argument("--out", default="", help="write proposal JSON here (default: stdout)")
    p.add_argument(
        "--submit", action="store_true", help="submit via orchestrator (default: dry only)"
    )
    r = sub.add_parser(
        "route", help="resolve a model from routing-policy.toml (the sole source of selection)"
    )
    selector = r.add_mutually_exclusive_group(required=True)
    selector.add_argument("--surface", default="", help="surface id, e.g. runner-implementation")
    selector.add_argument(
        "--change-class", dest="change_class", default="", help="change-class name"
    )
    r.add_argument("--policy", default="", help="policy file path (default: repo root)")

    c = sub.add_parser("create", help="scaffold an intent package from a registered profile")
    c.add_argument("--profile", required=True, help="registered delivery profile name")
    c.add_argument("--name", required=True, dest="package_id", help="package_id slug")
    c.add_argument("--out", default="packages", help="parent directory (default: packages)")
    c.add_argument("--owner", default="devon")
    c.add_argument("--title", default="", help="package title (default: derived from --name)")

    v = sub.add_parser("validate", help="validate an intent package")
    v.add_argument("path", help="path to a package directory or package.yaml")

    s = sub.add_parser("submit", help="stage an intake payload and hand off to /review")
    s.add_argument("--package", required=True, help="package directory or package.yaml")
    s.add_argument("--source-repository", required=True, dest="source_repository")
    s.add_argument("--open", action="store_true", dest="open_browser", help="open /review")

    st = sub.add_parser("status", help="one screen for a revision, with the next action")
    st.add_argument("--revision", default="", help="revision id (default: $FACTORY_REVISION)")
    st.add_argument("--wait", action="store_true", help="poll until a unit's state changes")

    ev = sub.add_parser("evidence", help="fetch the evidence pack")
    ev.add_argument("--revision", default="")
    ev.add_argument("--unit-key", dest="unit_key", default="")
    ev.add_argument("--markdown", action="store_true", help="the redacted PR-comment form")

    rd = sub.add_parser("ready", help="SYSTEM: move a unit DRAFT -> READY")
    rd.add_argument("--revision", default="", help="revision id (default: $FACTORY_REVISION)")
    rd.add_argument("--unit-key", dest="unit_key", required=True)

    dp = sub.add_parser("dispatch", help="SYSTEM: dispatch a READY unit to the runner")
    dp.add_argument("--revision", default="", help="revision id (default: $FACTORY_REVISION)")
    dp.add_argument("--unit-key", dest="unit_key", required=True)

    vf = sub.add_parser("verify", help="VERIFIER: post named-check evidence, then evaluate")
    vf.add_argument("--revision", default="", help="revision id (default: $FACTORY_REVISION)")
    vf.add_argument("--unit-key", dest="unit_key", required=True)
    vf.add_argument(
        "--ac",
        dest="ac_id",
        required=True,
        help=(
            "human AC id, e.g. AC-001 (never the criterion UUID). Must name a criterion whose "
            "evidence_type is automated_check -- any other type resolves to judgment_required "
            "however good the evidence, and verify refuses locally rather than POSTing"
        ),
    )
    vf.add_argument("--check-name", dest="check_name", required=True)
    vf.add_argument(
        "--conclusion",
        required=True,
        # Confirmed against the live openapi.json, not the brief's guess (which
        # listed an 8th value, "stale", that does not exist on
        # VerifierNamedCheckEvidenceCommandModel.conclusion):
        # `curl -s https://sds.alobar.net/openapi.json | python3 -c "...['conclusion']['enum']"`
        choices=(
            "success",
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
            "neutral",
            "skipped",
        ),
    )
    vf.add_argument("--run-id", dest="run_id", required=True)
    vf.add_argument("--run-url", dest="run_url", required=True)
    # No --repository override: the ingestion guard requires the payload's
    # repository to equal both the unit's authority target_repository and the
    # dispatch record's, so the derived value is the only one that can pass.
    vf.add_argument(
        "--assert",
        dest="assertions",
        action="append",
        default=[],
        metavar="NAME=EXPECTED:OBSERVED",
    )
    return parser


def _run_decompose(args: argparse.Namespace) -> int:
    from intent_packages.factory import decompose

    return decompose.run(
        revision=args.revision,
        ac=args.ac,
        target_repo=args.target_repo,
        repo_path=args.repo_path,
        tooling=args.tooling,
        package=args.package,
        from_version=args.from_version,
        to_version=args.to_version,
        unit_key=args.unit_key,
        rationale=args.rationale,
        out=args.out,
        submit=args.submit,
        verbose=args.verbose,
    )


def _run_route(args: argparse.Namespace) -> int:
    from intent_packages import routing

    try:
        policy = routing.load_policy(Path(args.policy) if args.policy else None)
        row = (
            routing.resolve_surface(policy, args.surface)
            if args.surface
            else routing.resolve_change_class(policy, args.change_class)
        )
    except routing.RoutingPolicyError as error:
        print(f"route failed: {error}", file=sys.stderr)
        return 1
    for slug, model_id in zip(row.models, row.model_ids, strict=True):
        print(f"{row.id}: {slug} ({model_id})")
    print(f"  decided {row.decided} — {row.rationale}")
    return 0


def _run_create(args: argparse.Namespace) -> int:
    from intent_packages.factory import scaffolds

    return scaffolds.create(
        args.profile, args.package_id, args.out, owner=args.owner, title=args.title
    )


def _run_validate(args: argparse.Namespace) -> int:
    from intent_packages.factory import scaffolds

    return scaffolds.validate(args.path)


def _run_submit(args: argparse.Namespace) -> int:
    from intent_packages.factory import journey

    return journey.submit(args.package, args.source_repository, open_browser=args.open_browser)


def _run_status(args: argparse.Namespace) -> int:
    from intent_packages.factory import journey

    return journey.status(args.revision, wait=args.wait, verbose=args.verbose)


def _run_evidence(args: argparse.Namespace) -> int:
    from intent_packages.factory import journey

    return journey.evidence(
        args.revision, unit_key=args.unit_key, markdown=args.markdown, verbose=args.verbose
    )


def _run_ready(args: argparse.Namespace) -> int:
    from intent_packages.factory import execution

    return execution.ready(args.revision, args.unit_key, verbose=args.verbose)


def _run_dispatch(args: argparse.Namespace) -> int:
    from intent_packages.factory import execution

    return execution.dispatch(args.revision, args.unit_key, verbose=args.verbose)


def _run_verify(args: argparse.Namespace) -> int:
    from intent_packages.factory import verify

    return verify.verify(
        args.revision,
        args.unit_key,
        ac_id=args.ac_id,
        check_name=args.check_name,
        conclusion=args.conclusion,
        run_id=args.run_id,
        run_url=args.run_url,
        assertions=args.assertions,
        verbose=args.verbose,
    )


# A dict dispatch table, not an `if args.cmd == ...` chain: the chain hit
# ruff's C901 complexity ceiling (10) the moment `ready`/`dispatch` joined
# `decompose`/`route`/`create`/`validate`/`submit`/`status`/`evidence`, and
# `verify` (task 9) would have pushed it over again. Each handler owns its
# own (small) complexity instead of adding a branch to `main`.
_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "decompose": _run_decompose,
    "route": _run_route,
    "create": _run_create,
    "validate": _run_validate,
    "submit": _run_submit,
    "status": _run_status,
    "evidence": _run_evidence,
    "ready": _run_ready,
    "dispatch": _run_dispatch,
    "verify": _run_verify,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handler = _HANDLERS.get(args.cmd)
    return handler(args) if handler else 0
