"""The `factory decompose` flow: intake -> ac_mappings/retained_acs -> real-scan
conformance -> per-tooling envelope -> fail-closed validations -> emit/submit.

Human gates (intake, decomposition approval, authority approval, merge) are
out of scope. The only orchestrator write is the SYSTEM/M2M proposal submit.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from intent_packages import routing
from intent_packages.factory.orchestrator_cli import OrchestratorClient, OrchestratorCliError
from intent_packages.factory.validations import (
    ValidationError,
    assert_pin_sites_moved,
    assert_runner_honest,
    dry_run_mutation,
)
from intent_packages.profiles.dependency_update import PinSite, ProfileError, build_envelope


class DecomposeError(Exception):
    """Raised when a decomposition request is malformed or a criterion is unknown."""


def _criteria_uuid_map(intake: dict) -> dict[str, str]:
    criteria = intake.get("acceptance_criteria") or []
    return {c["ac_id"]: c["id"] for c in criteria}


def _repo_name(target_repo: str) -> str:
    return target_repo.split("/", 1)[-1]


def build_proposal(
    intake: dict,
    ac: str,
    unit_key: str,
    target_repo: str,
    tooling: str,
    package: str,
    old: str,
    new: str,
    conformance: dict,
    sites: list[PinSite],
    rationale: str,
) -> dict:
    uuids = _criteria_uuid_map(intake)
    if ac not in uuids:
        raise DecomposeError(f"acceptance criterion {ac} not found in revision")
    mapped_uuid = uuids[ac]
    envelope = build_envelope(target_repo, tooling, package, old, new, conformance, sites)
    retained = [
        {"ac_id": uuid, "rationale": rationale or f"not addressed by the {package} update ({ac})"}
        for human_id, uuid in uuids.items()
        if human_id != ac
    ]
    return {
        "idempotency_key": f"factory-decompose-{target_repo}-{package}-{new}".replace("/", "-"),
        "expected_version": 0,
        "rationale": f"Dependency update: {package} {old} -> {new} in {target_repo}.",
        "proposed_units": [
            {
                "unit_key": unit_key,
                "title": f"Update {package} to {new} in {target_repo}",
                "outcome": (
                    f"{target_repo} receives a PR that moves {package} {old} -> {new}; "
                    f"its named check passes on the PR head."
                ),
                "required_capability": "repo.edit",
                "authority": envelope,
                "max_attempts": 3,
            }
        ],
        "dependencies": [],
        "ac_mappings": [{"ac_id": mapped_uuid, "unit_key": unit_key}],
        "retained_acs": retained,
    }


def _resolve_repo_path(target_repo: str, repo_path: str) -> Path:
    if repo_path:
        return Path(repo_path).expanduser()
    return Path.home() / "Projects" / _repo_name(target_repo)


def run(
    *,
    revision: str,
    ac: str,
    target_repo: str,
    repo_path: str,
    tooling: str,
    package: str,
    from_version: str,
    to_version: str,
    unit_key: str,
    rationale: str,
    out: str,
    submit: bool,
    client: OrchestratorClient | None = None,
    policy_path: Path | None = None,
) -> int:
    client = client or OrchestratorClient()
    resolved_key = unit_key or f"{_repo_name(target_repo)}-{ac.lower()}"
    local_repo = _resolve_repo_path(target_repo, repo_path)
    try:
        if not local_repo.is_dir():
            raise DecomposeError(f"target checkout not found: {local_repo}")
        from intent_packages.profiles.dependency_update import TOOLING_PROFILES

        if tooling not in TOOLING_PROFILES:
            raise DecomposeError(f"unknown tooling: {tooling}")
        sites = TOOLING_PROFILES[tooling].discover_pin_sites(local_repo, package)
        if not sites:
            raise DecomposeError(f"no pin site for {package} in {local_repo} ({tooling})")

        intake = client.show_package_intake(revision)
        conformance = client.conformance_claim(str(local_repo))

        proposal = build_proposal(
            intake,
            ac,
            resolved_key,
            target_repo,
            tooling,
            package,
            from_version,
            to_version,
            conformance,
            sites,
            rationale,
        )
        change_class = proposal["proposed_units"][0]["authority"]["change_class"]
        policy = routing.load_policy(policy_path)
        row = routing.resolve_change_class(policy, change_class)
        proposal["rationale"] += (
            f" routing: {'/'.join(row.models)} per routing-policy v{policy.version}."
        )
        allowed = proposal["proposed_units"][0]["authority"]["constraints"]["allowed_commands"]

        assert_runner_honest(allowed)
        changed = dry_run_mutation(local_repo, allowed)
        assert_pin_sites_moved(changed, sites)

        body = json.dumps(proposal, indent=2, sort_keys=True)
        if out:
            Path(out).write_text(body + "\n", encoding="utf-8")
        else:
            print(body)

        if submit:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
                handle.write(body)
                proposal_path = handle.name
            try:
                result = client.propose_decomposition(revision, proposal_path)
            finally:
                os.unlink(proposal_path)
            print(f"submitted: {json.dumps(result, sort_keys=True)}", file=sys.stderr)
        return 0
    except (
        DecomposeError,
        ValidationError,
        OrchestratorCliError,
        ProfileError,
        routing.RoutingPolicyError,
    ) as error:
        print(f"decompose failed: {error}", file=sys.stderr)
        return 1
