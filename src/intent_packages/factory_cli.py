"""`factory` CLI front door (WS-P2.9). Subcommands: decompose, route.

Mirrors intent_packages.cli: main(argv) -> int, argparse subparsers, lazy
per-subcommand imports. Future journey verbs (create/validate/submit/status/
evidence/retry/cancel) join as sibling subparsers.
"""

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description=__doc__)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "decompose":
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
        )
    if args.cmd == "route":
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
    return 0
