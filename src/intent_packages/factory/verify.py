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

(1) `reads.latest_dispatched_payload`, reading `dispatch_record_id` and
`target_repository` off the event's `payload`.
(2) `GET /api/v1/in-flight-units` (`InFlightUnitModel`) -- a SUBMITTED or
VERIFYING unit is in flight.

There is no `--repository` override: the ingestion guard
(`validate_named_check_bindings`) requires the payload's `repository` to equal
BOTH the unit's authority `target_repository` and the dispatch record's, so
the derived value is the only one that can ever pass -- an override is a
guaranteed mismatch, and it would not even help the missing-`target_repository`
refusal, which fires first.

FOUR reads happen: `get_intake` (to pre-check `--ac`'s `evidence_type`),
`traceability` (via `resolve_unit_id`), `history`, and `in-flight-units`.
`traceability`'s `pr` hop is deliberately unused -- `pr_number`/`head_sha` come
from `in-flight-units` instead -- and there is no `evidence_pack` call at all.
The `--ac` pre-check narrows but does not close the refusal set; see
`_ac_evidence_type_refusal` for exactly what it cannot see.

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

from intent_packages.factory import links, reads
from intent_packages.factory.api import ApiError, OrchestratorApi, base_url_from_env
from intent_packages.factory.reads import (
    InFlightApi,
    RevisionApi,
    RevisionRequired,
    resolve_revision,
)

MAX_ASSERTIONS = 32

# The ONLY `evidence_type` for which `evaluate_criterion` routes to the
# named-check evaluator (`services/verifier_evaluators.py`). Every other type,
# including the deceptively-named `automated_test`, resolves to
# `judgment_required` regardless of the evidence.
NAMED_CHECK_EVIDENCE_TYPE = "automated_check"

# `VerificationResult` (`services/verifier_types.py`) is
# `Literal["completed", "revision_required", "awaiting_review", "failed"]` --
# NOT `passed`/`judgment_required`/`failed`. `EvaluationStatus` is the separate
# per-AC vocabulary `passed`/`failed`/`failed_closed`/`judgment_required`.
_RESULT_COMPLETED = "completed"
_RESULT_AWAITING_REVIEW = "awaiting_review"
_STATUS_JUDGMENT_REQUIRED = "judgment_required"
# `services/verifier_named_check.py::validate_named_check_bindings` only accepts
# named-check evidence while the unit is SUBMITTED or VERIFYING; every other
# in-flight state (e.g. EXECUTING, on the REVISION_REQUIRED -> READY -> EXECUTING
# loop) still carries a stale `pr_number`/armed head from a prior cycle, so
# their mere presence cannot be the check -- the state itself must be.
_VERIFIABLE_STATES = frozenset({"submitted", "verifying"})


class VerifyApi(RevisionApi, InFlightApi, Protocol):
    """The derived reads `verify` runs on (`resolve_unit_id`, `history`,
    `in_flight_units`, `get_intake`) plus the two VERIFIER-role writes it makes.

    It extends `RevisionApi`/`InFlightApi` rather than `ExecutionApi`: `verify`
    makes none of `ready`/`dispatch`'s writes (`command`, `dispatch`,
    `resolve_version`), and demanding them of a double would be a Protocol
    asserting a dependency this verb does not have.
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
    dispatch_payload = reads.latest_dispatched_payload(api, unit_id)
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

    snapshot = reads.in_flight_snapshot(api, unit_id)
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

    **Exit code reflects the verification RESULT** (Devon's decision, 2026-07-29),
    because this is the command a factory script gates on -- see
    `_report_verification`. `awaiting_review` exits 0 with an unmissable line
    saying it is not a pass.
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
        refusal = _ac_evidence_type_refusal(api, revision_id, ac_id)
        if refusal is not None:
            print(f"verify failed: {refusal}", file=sys.stderr)
            return 1

        unit_id = reads.resolve_unit_id(api, revision_id, unit_key, verb="verify")
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

    return _report_verification(unit_id, verify_response)


def _criteria_evidence_types(intake: dict) -> dict[str, str | None]:
    """`{ac_id: evidence_type}` for every criterion on the revision.

    `PackageAcceptanceCriterionResponse` types both fields as required strings,
    but this reads a decoded JSON body: a non-`str` `evidence_type` is mapped to
    `None` so the caller's inequality against `automated_check` still refuses it
    rather than crashing on an unexpected shape.
    """
    types: dict[str, str | None] = {}
    for item in intake.get("acceptance_criteria") or []:
        if not isinstance(item, dict):
            continue
        ac_id = item.get("ac_id")
        if not isinstance(ac_id, str) or not ac_id:
            continue
        evidence_type = item.get("evidence_type")
        types[ac_id] = evidence_type if isinstance(evidence_type, str) else None
    return types


def _ac_evidence_type_refusal(api: VerifyApi, revision_id: str, ac_id: str) -> str | None:
    """Refuse locally when `--ac` cannot possibly accept named-check evidence.

    `evaluate_criterion` (`services/verifier_evaluators.py`) routes a criterion to
    the named-check evaluator ONLY when its `evidence_type` is exactly
    `automated_check`. Anything else -- and `automated_test` in particular, which
    is a *named* member of `JUDGMENT_TYPES` and therefore resolves to
    `judgment_required` for every automated AC however good the evidence -- makes
    the named-check POST pointless work. That trap is the refusal an operator is
    most likely to hit blind, so it is caught here from
    `get_intake(revision_id)["acceptance_criteria"]`, which carries `ac_id` and
    `evidence_type` for every criterion on the revision.

    **What this CANNOT catch.** The server resolves `--ac` through the
    unit<->criterion mapping (`services/verifier_criteria.py`, filtering
    `DecompositionProposalAcMapping.unit_key`), and `get_intake` cannot see that
    mapping at all: it lists every criterion on the REVISION, not the ones mapped
    to THIS unit. So a criterion that exists on the revision, has
    `evidence_type: automated_check`, and is simply not mapped to `--unit-key`
    will still pass this check, round-trip, and come back
    `evidence_subject_invalid`. This narrows the failure set; it does not close
    it, and no read available to this client can.

    Returns the refusal text, or `None` to proceed.
    """
    by_ac_id = _criteria_evidence_types(api.get_intake(revision_id))
    if ac_id not in by_ac_id:
        known = ", ".join(sorted(by_ac_id)) or "(none)"
        return (
            f"unknown --ac {ac_id!r} on revision {revision_id}; criteria on this revision: "
            f"{known}. --ac takes the HUMAN string (e.g. AC-001), never the criterion UUID"
        )
    evidence_type = by_ac_id[ac_id]
    if evidence_type != NAMED_CHECK_EVIDENCE_TYPE:
        return (
            f"--ac {ac_id} declares evidence_type {evidence_type!r}, but named-check evidence is "
            f"only evaluated for {NAMED_CHECK_EVIDENCE_TYPE!r} -- every other type (notably "
            "'automated_test', which is a named judgment type) resolves to judgment_required "
            "however good the evidence, so this POST would not change the outcome. Fix the "
            "package's evidence_type, or adjudicate this criterion in /review instead. NOTE: "
            "this check reads the criteria of the REVISION and cannot see the unit<->criterion "
            "mapping, so an --ac that is valid here may still be rejected as "
            "evidence_subject_invalid if it is not mapped to this unit_key"
        )
    return None


def _report_verification(unit_id: str, verify_response: dict) -> int:
    """Print the result and per-AC outcomes, and return the exit code.

    **The `result` vocabulary is not `passed`/`judgment_required`/`failed`.**
    `VerificationResult` (`services/verifier_types.py`) is
    `Literal["completed", "revision_required", "awaiting_review", "failed"]`, and
    `_result_for_state` derives it from the state the verification transitioned
    to. The per-AC `status` is the `passed`/`failed`/`failed_closed`/
    `judgment_required` vocabulary (`EvaluationStatus`); `outcome` is
    `passed`/`failed`/`waived`/`not_applicable`/None.

    Devon's decision, mapped onto that real vocabulary:

    - `completed` -> exit 0. Every required criterion passed; this is the pass.
    - `awaiting_review` -> exit 0, but with an unmissable line stating it is NOT
      a pass and awaits human adjudication. At least one criterion came back
      `judgment_required`, which is a legitimate outcome needing a human, not a
      failure -- but a script that treated a silent 0 as "verified" would be
      wrong, so the line names the criteria and the /review page.
    - `revision_required`, `failed`, or anything else -> non-zero. A failure, or
      a result this client does not recognise; either way not a pass.
    """
    print(
        f"unit {unit_id} -> {verify_response.get('state')} "
        f"(version {verify_response.get('version')}), result: {verify_response.get('result')}"
    )
    evaluations = verify_response.get("evaluations", [])
    for evaluation in evaluations:
        print(
            f"  {evaluation.get('ac_id')}: {evaluation.get('status')} "
            f"({evaluation.get('outcome')}) -- {evaluation.get('reason')}"
        )

    result = verify_response.get("result")
    if result == _RESULT_COMPLETED:
        print("verified: every required acceptance criterion passed.")
        return 0
    if result == _RESULT_AWAITING_REVIEW:
        pending = ", ".join(
            str(item.get("ac_id"))
            for item in evaluations
            if item.get("status") == _STATUS_JUDGMENT_REQUIRED
        )
        print(
            "*** NOT A PASS: this unit is AWAITING HUMAN REVIEW. ***\n"
            f"*** {pending or 'at least one criterion'} came back judgment_required, which no "
            "amount of evidence can turn into a pass -- a human must adjudicate it in /review "
            f"({links.unit(base_url_from_env(), unit_id)}).\n"
            "*** This command exits 0 because the verification itself succeeded; do NOT read "
            "that as verified."
        )
        return 0
    print(
        f"verify: result {result!r} is not a pass -- this unit did not verify",
        file=sys.stderr,
    )
    return 1
