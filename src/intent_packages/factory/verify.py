"""`factory verify` -- the WS-5.1 verifier flow (remediation 6.2, task 9).

Two calls, in order: `POST .../verifier-evidence/named-check`, then `POST
.../verify`. Every field on the named-check body is derived from a prior read
-- never guessed -- and a missing source is a named refusal (exit 1), never a
substitution. Several of those refusals exist so the CLI can catch locally
what the server would otherwise reject anyway (fix round 1/5): a stale unit
state, a diverged head, or an empty/oversized/duplicate `--assert` list each
used to cost a wasted round trip and a network POST before failing.

**task-9-brief.md's own field-derivation table is wrong** and is not what this
module implements. The brief said `repository` comes from
`evidence_pack(unit_id)["authority"]["constraints"]["target_repository"]` --
but `EvidencePackResponse` exposes no `constraints` field at all, and the
brief's own test fixtures invented that shape rather than reading it off a
real response. The corrected derivation, confirmed against
`services/dispatch.py` and `services/verifier_named_check.py` in the
orchestrator's own tree:

| field | source |
|---|---|
| `dispatch_id`, `repository` | latest `dispatch.dispatched` event payload (1) |
| `pr_number`, `head_sha`, `expected_version`, `work_package_revision_id` | `in-flight-units` (2) |
| `pr_url` | composed: `https://github.com/{repository}/pull/{pr_number}` |
| `ac_id` | `--ac`, the human string (e.g. `AC-001`), never the criterion UUID |
| `check_name`, `conclusion`, `run_id`, `run_url`, `assertions` | CLI flags |

(1) `execution.latest_dispatched_payload`, reading `dispatch_record_id` and
`target_repository` off the event's `payload`.
(2) `GET /api/v1/in-flight-units` (`InFlightUnitModel`) -- a SUBMITTED or
VERIFYING unit is in flight.

There is no `--repository` override: the ingestion guard
(`validate_named_check_bindings`) requires the payload's `repository` to equal
BOTH the unit's authority `target_repository` and the dispatch record's, so
the derived value is the only one that can ever pass -- an override is a
guaranteed mismatch, and it would not even help the missing-`target_repository`
refusal, which fires first.

Three reads happen, not two: `resolve_unit_id` (via `units_for`) reads
`traceability`, then `history`, then `in-flight-units`. `traceability`'s `pr`
hop is deliberately unused -- `pr_number`/`head_sha` come from `in-flight-units`
instead -- and there is no `evidence_pack` call at all.

**Which `head_sha` field, and why:** `InFlightUnitModel` carries both
`head_sha` (mutable, worker-written -- a rebase mid-flight is normal) and
`verification_read_head_sha` (frozen at SUBMIT -- see `services/pr_bindings.py`'s
own docstring: "the head that verification effectively acts on ... is the head
the worker submitted its evidence at"). This sends `verification_read_head_sha`
because that is its *meaning*: the head verification actually acts on.
`services/verifier_named_check.py::validate_named_check_bindings` requires the
payload's `head_sha` to equal BOTH `binding.head_sha` AND
`binding.verification_read_head_sha` -- so this value is only ever acceptable
when the two already agree, and when they don't, no CLI-side choice can fix
it: `verify` refuses locally instead of spending a round trip on a guaranteed
`named_check_binding_mismatch`.
"""

from __future__ import annotations

import sys
import uuid
from typing import Protocol

from intent_packages.factory.api import ApiError, OrchestratorApi
from intent_packages.factory.execution import (
    ExecutionApi,
    in_flight_snapshot,
    latest_dispatched_payload,
    resolve_unit_id,
)
from intent_packages.factory.journey import RevisionRequired, resolve_revision

MAX_ASSERTIONS = 32
# `services/verifier_named_check.py::validate_named_check_bindings` only accepts
# named-check evidence while the unit is SUBMITTED or VERIFYING; every other
# in-flight state (e.g. EXECUTING, on the REVISION_REQUIRED -> READY -> EXECUTING
# loop) still carries a stale `pr_number`/armed head from a prior cycle, so
# their mere presence cannot be the check -- the state itself must be.
_VERIFIABLE_STATES = frozenset({"submitted", "verifying"})


class VerifyApi(ExecutionApi, Protocol):
    """`ExecutionApi` (needed by `resolve_unit_id`, `history`, and
    `in_flight_units`) plus the two VERIFIER-role writes `verify` makes.

    A structural `Protocol`, same reasoning as `RevisionApi`/`ExecutionApi`: a
    test double only has to implement the methods actually exercised, not
    *be* an `OrchestratorApi`.
    """

    def named_check(self, unit_id: str, payload: dict, /) -> dict: ...
    def verify(self, unit_id: str, payload: dict, /) -> dict: ...


def parse_assertion(text: str) -> dict:
    """Parse `name=expected:observed` into a `NamedCheckAssertionModel` body."""
    name, separator, rest = text.partition("=")
    expected, colon, observed = rest.partition(":")
    if not (separator and colon and name and expected and observed):
        raise ValueError(f"assertion must be name=expected:observed, got {text!r}")
    return {"name": name, "expected": expected, "observed": observed}


def build_assertions(values: list[str]) -> list[dict]:
    """Parse every `--assert` value.

    Refuses fewer than 1 or more than 32 -- the schema's `minItems`/`maxItems`
    (`NamedCheckAssertionModel` list on `VerifierNamedCheckEvidenceCommandModel`).
    The documented minimum invocation is `--assert` at least once; omitting it
    entirely used to sail through this function, make all three reads, build a
    payload with an empty `assertions` list, and only then take a 422 from the
    server -- fixed here instead of at the network boundary. Also refuses a
    duplicate assertion name: the server's own evaluator rejects a repeated
    name too (`services/verifier_evaluators.py::_named_check_result`), so this
    is the same local-refusal-over-round-trip trade as the count checks.
    """
    if not values:
        raise ValueError("at least 1 assertion is required (got 0) -- pass --assert at least once")
    if len(values) > MAX_ASSERTIONS:
        raise ValueError(f"at most {MAX_ASSERTIONS} assertions, got {len(values)}")
    parsed = [parse_assertion(value) for value in values]
    names = [item["name"] for item in parsed]
    if len(set(names)) != len(names):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise ValueError(f"duplicate assertion name(s): {', '.join(duplicates)}")
    return parsed


def _derive_named_check_payload(
    api: VerifyApi,
    unit_id: str,
    revision_id: str,
    *,
    ac_id: str,
    check_name: str,
    conclusion: str,
    run_id: str,
    run_url: str,
    parsed_assertions: list[dict],
) -> dict | None:
    """Derive the named-check body (minus `idempotency_key`), or print a named
    refusal and return `None`.

    Every refusal here is a LOCAL check on data this function already read --
    each one turns a network round trip plus a single
    `named_check_binding_mismatch` (one code covering several distinct causes)
    into a specific, actionable reason before any write is attempted.
    """
    dispatch_payload = latest_dispatched_payload(api, unit_id)
    if dispatch_payload is None:
        print(
            f"verify failed: unit {unit_id} has no dispatch.dispatched event in its "
            "history -- it was never actually dispatched",
            file=sys.stderr,
        )
        return None
    dispatch_id = dispatch_payload.get("dispatch_record_id")
    repository = dispatch_payload.get("target_repository")
    if not dispatch_id or not repository:
        print(
            f"verify failed: unit {unit_id}'s dispatch.dispatched event is missing "
            "dispatch_record_id or target_repository",
            file=sys.stderr,
        )
        return None

    snapshot = in_flight_snapshot(api, unit_id)
    if snapshot is None:
        print(
            f"verify failed: unit {unit_id} is not in flight (state must be SUBMITTED "
            f"or VERIFYING) -- run: factory status --revision {revision_id}",
            file=sys.stderr,
        )
        return None
    pr_number = snapshot.get("pr_number")
    current_head_sha = snapshot.get("head_sha")
    armed_head_sha = snapshot.get("verification_read_head_sha")
    if pr_number is None or not armed_head_sha:
        print(
            f"verify failed: unit {unit_id} has no PR binding armed for verification "
            "(pr_number or verification_read_head_sha absent) -- the worker must submit "
            "before this unit can be verified",
            file=sys.stderr,
        )
        return None
    state = snapshot.get("state")
    if state not in _VERIFIABLE_STATES:
        print(
            f"verify failed: unit {unit_id} is in state {state!r} -- only a SUBMITTED or "
            "VERIFYING unit accepts named-check evidence (a stale pr_number/armed head can "
            "survive a REVISION_REQUIRED -> READY -> EXECUTING loop, so being in-flight is "
            "not enough)",
            file=sys.stderr,
        )
        return None
    if current_head_sha != armed_head_sha:
        print(
            f"verify failed: head moved after submit: armed {armed_head_sha!r}, current "
            f"{current_head_sha!r} -- no named-check payload can validate against both; the "
            "worker must re-submit to re-arm",
            file=sys.stderr,
        )
        return None

    return {
        "work_package_revision_id": snapshot.get("work_package_revision_id"),
        "ac_id": ac_id,
        "dispatch_id": dispatch_id,
        "repository": repository,
        "pr_number": pr_number,
        "pr_url": f"https://github.com/{repository}/pull/{pr_number}",
        "head_sha": armed_head_sha,
        "check_name": check_name,
        "conclusion": conclusion,
        "run_id": run_id,
        "run_url": run_url,
        "assertions": parsed_assertions,
        "expected_version": snapshot.get("version"),
    }


def verify(
    revision_id: str,
    unit_key: str,
    *,
    ac_id: str,
    check_name: str,
    conclusion: str,
    run_id: str,
    run_url: str,
    assertions: list[str],
    api: VerifyApi | None = None,
    verbose: bool = False,
) -> int:
    """VERIFIER: post named-check evidence, then evaluate the unit's ACs.

    Every field is either a flag or read straight off `history`/
    `in-flight-units`. A missing or invalid source is a named refusal, never a
    guess or a substitution.
    """
    api = api or OrchestratorApi(verbose=verbose)
    try:
        revision_id = resolve_revision(revision_id)
    except RevisionRequired as error:
        print(f"verify failed: {error}", file=sys.stderr)
        return 2

    try:
        parsed_assertions = build_assertions(assertions)
    except ValueError as error:
        print(f"verify failed: {error}", file=sys.stderr)
        return 1

    try:
        unit_id = resolve_unit_id(api, revision_id, unit_key, verb="verify")
        if unit_id is None:
            return 1

        payload = _derive_named_check_payload(
            api,
            unit_id,
            revision_id,
            ac_id=ac_id,
            check_name=check_name,
            conclusion=conclusion,
            run_id=run_id,
            run_url=run_url,
            parsed_assertions=parsed_assertions,
        )
        if payload is None:
            return 1

        version = payload["expected_version"]
        api.named_check(unit_id, {**payload, "idempotency_key": f"factory-verify-{uuid.uuid4()}"})
        verify_response = api.verify(
            unit_id,
            {"idempotency_key": f"factory-verify-{uuid.uuid4()}", "expected_version": version},
        )
    except ApiError as error:
        print(f"verify failed: {error}", file=sys.stderr)
        return 1

    print(
        f"unit {unit_id} -> {verify_response.get('state')} "
        f"(version {verify_response.get('version')}), result: {verify_response.get('result')}"
    )
    for evaluation in verify_response.get("evaluations", []):
        print(
            f"  {evaluation.get('ac_id')}: {evaluation.get('status')} "
            f"({evaluation.get('outcome')}) -- {evaluation.get('reason')}"
        )
    return 0
