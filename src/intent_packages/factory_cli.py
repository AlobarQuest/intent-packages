"""`factory` CLI front door (WS-P2.9). First subcommand: decompose.

Mirrors intent_packages.cli: main(argv) -> int, argparse subparsers, lazy
per-subcommand imports. Future journey verbs (create/validate/submit/status/
evidence/retry/cancel) join as sibling subparsers.
"""

import argparse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("decompose", help="author + validate a dependency-update decomposition proposal")
    p.add_argument("--revision", required=True, help="intaken package revision id")
    p.add_argument("--ac", required=True, help="acceptance criterion human id, e.g. AC-002")
    p.add_argument("--target-repo", required=True, help="GitHub slug, e.g. AlobarQuest/brain")
    p.add_argument("--repo-path", default="", help="local checkout path (default: ~/Projects/<repo>)")
    p.add_argument("--tooling", required=True, choices=("pip", "uv", "npm"))
    p.add_argument("--package", required=True, help="dependency name")
    p.add_argument("--from", dest="from_version", required=True, help="current pinned version")
    p.add_argument("--to", dest="to_version", required=True, help="target version")
    p.add_argument("--unit-key", default="", help="proposed unit key (default: derived from --ac)")
    p.add_argument("--rationale", default="", help="retained-AC rationale (default: auto)")
    p.add_argument("--out", default="", help="write proposal JSON here (default: stdout)")
    p.add_argument("--submit", action="store_true", help="submit via orchestrator (default: dry only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "decompose":
        # Wired to factory.decompose.run in Task 7. For now echo the parsed request.
        print(
            f"decompose revision={args.revision} ac={args.ac} "
            f"target={args.target_repo} tooling={args.tooling} "
            f"package={args.package} {args.from_version}->{args.to_version}"
        )
        return 0
    return 0
