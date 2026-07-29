"""`factory verify` -- the WS-5.1 verifier flow (remediation 6.2, task 9).

Two calls, in order: `POST .../verifier-evidence/named-check`, then `POST
.../verify`. Every field on the named-check body is derived from a prior read
-- never guessed -- and a missing source is a named refusal (exit 1), never a
substitution.

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

So this needs exactly two reads -- `history` and `in-flight-units` -- and no
`traceability` or `evidence_pack` call at all.

**Which `head_sha` field, and why:** `InFlightUnitModel` carries both
`head_sha` (mutable, worker-written -- a rebase mid-flight is normal and must
never raise a false alarm) and `verification_read_head_sha` (the alarm-arming
field, frozen at SUBMIT -- see `services/pr_bindings.py`'s own docstring: "the
head that verification effectively acts on ... is the head the worker
submitted its evidence at"). `services/verifier_named_check.py::validate_named_check_bindings`
checks the payload's `head_sha` against BOTH `binding.head_sha` and
`binding.verification_read_head_sha` -- so this sends
`verification_read_head_sha`: it is the field verification is actually
adjudicating, and it is the field the whole attestation hangs on. If the two
have diverged (a push landed after submit), no single payload value can
satisfy both checks and the named-check fails closed regardless of which one
is sent -- so this is not a hedge against that case, it is the semantically
correct choice for the (overwhelmingly common) case where they still agree.
"""

from __future__ import annotations

import sys
import uuid
from typing import Protocol

from intent_packages.factory.api import ApiError, OrchestratorApi
from intent_packages.factory.execution import (
    ExecutionApi,
    _resolve_unit_id,
    latest_dispatched_payload,
)
from intent_packages.factory.journey import RevisionRequired, resolve_revision

MAX_ASSERTIONS = 32


class VerifyApi(ExecutionApi, Protocol):
    """`ExecutionApi` (needed by `_resolve_unit_id`, `history`, and
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
    """Parse every `--assert` value, refusing more than the schema's `maxItems` (32)."""
    if len(values) > MAX_ASSERTIONS:
        raise ValueError(f"at most {MAX_ASSERTIONS} assertions, got {len(values)}")
    return [parse_assertion(value) for value in values]


def _in_flight_snapshot(api: VerifyApi, unit_id: str) -> dict | None:
    """This unit's in-flight row (`version`, `pr_number`, `head_sha`,
    `verification_read_head_sha`, `work_package_revision_id`), or `None` if
    it is not in flight at all."""
    for entry in api.in_flight_units().get("units", []):
        if str(entry.get("work_unit_id")) == unit_id:
            return entry
    return None


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
    repository: str = "",
    api: VerifyApi | None = None,
) -> int:
    """VERIFIER: post named-check evidence, then evaluate the unit's ACs.

    `--repository` overrides the derived value; every other field is either a
    flag or read straight off `history`/`in-flight-units`. A missing source
    is a named refusal, never a guess or a substitution.
    """
    api = api or OrchestratorApi()
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
        unit_id = _resolve_unit_id(api, revision_id, unit_key, verb="verify")
        if unit_id is None:
            return 1

        dispatch_payload = latest_dispatched_payload(api, unit_id)
        if dispatch_payload is None:
            print(
                f"verify failed: unit {unit_id} has no dispatch.dispatched event in its "
                "history -- it was never actually dispatched",
                file=sys.stderr,
            )
            return 1
        dispatch_id = dispatch_payload.get("dispatch_record_id")
        derived_repository = dispatch_payload.get("target_repository")
        if not dispatch_id or not derived_repository:
            print(
                f"verify failed: unit {unit_id}'s dispatch.dispatched event is missing "
                "dispatch_record_id or target_repository",
                file=sys.stderr,
            )
            return 1
        resolved_repository = repository or derived_repository

        snapshot = _in_flight_snapshot(api, unit_id)
        if snapshot is None:
            print(
                f"verify failed: unit {unit_id} is not in flight (state must be SUBMITTED "
                f"or VERIFYING) -- run: factory status --revision {revision_id}",
                file=sys.stderr,
            )
            return 1
        pr_number = snapshot.get("pr_number")
        head_sha = snapshot.get("verification_read_head_sha")
        version = snapshot.get("version")
        work_package_revision_id = snapshot.get("work_package_revision_id")
        if pr_number is None or not head_sha:
            print(
                f"verify failed: unit {unit_id} has no PR binding armed for verification "
                "(pr_number or verification_read_head_sha absent) -- the worker must submit "
                "before this unit can be verified",
                file=sys.stderr,
            )
            return 1

        named_check_payload = {
            "idempotency_key": f"factory-verify-{uuid.uuid4()}",
            "expected_version": version,
            "work_package_revision_id": work_package_revision_id,
            "ac_id": ac_id,
            "dispatch_id": dispatch_id,
            "repository": resolved_repository,
            "pr_number": pr_number,
            "pr_url": f"https://github.com/{resolved_repository}/pull/{pr_number}",
            "head_sha": head_sha,
            "check_name": check_name,
            "conclusion": conclusion,
            "run_id": run_id,
            "run_url": run_url,
            "assertions": parsed_assertions,
        }
        api.named_check(unit_id, named_check_payload)
        verify_response = api.verify(
            unit_id,
            {
                "idempotency_key": f"factory-verify-{uuid.uuid4()}",
                "expected_version": version,
            },
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
