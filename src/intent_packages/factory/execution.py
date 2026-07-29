"""The lifecycle-writing verbs: `ready` and `dispatch`.

Split out from `journey.py` (which stays the read/report surface -- `submit`,
`status`, `evidence`) because these two verbs carry version and dispatch-
ordinal hazards `journey.py`'s verbs do not: a wrong `expected_version` is a
clean `version_conflict`, but a wrong `runner_attempt` is a SILENT NO-OP --
the orchestrator returns the pre-existing `DispatchRecord` with HTTP 200 and
`status: "dispatched"`, having triggered no `workflow_dispatch` at all. Only a
NEW record id proves a dispatch happened; the `status` field says the same
thing either way.

Where `version` and `attempt_count` come from is verb-specific, not brief-
uniform:

- `ready` acts on a DRAFT unit, which is absent from `GET /in-flight-units`
  (the only read surface carrying either field) -- `DRAFT` is not one of
  `orchestrator.services.in_flight.IN_FLIGHT_STATES`. So `ready` uses the
  documented probe instead: `api.resolve_version` POSTs an otherwise-valid
  body with `expected_version: 0` and reads `current_version` off the
  resulting `version_conflict`.
- `dispatch` acts on a READY unit, which IS in flight -- so it reads both
  `version` and `attempt_count` straight off `GET /in-flight-units`. No probe.

No code moved from `journey.py`; this module imports `resolve_revision`,
`RevisionRequired`, and `units_for` from it.
"""

from __future__ import annotations

import sys
import uuid
from typing import Protocol

from intent_packages.factory.api import ApiError, OrchestratorApi
from intent_packages.factory.journey import (
    RevisionApi,
    RevisionRequired,
    resolve_revision,
    units_for,
)


class ExecutionApi(RevisionApi, Protocol):
    """`RevisionApi` (needed by `units_for`, to resolve `--unit-key`) plus the
    four write/version-read methods `ready` and `dispatch` use.

    A structural `Protocol`, same reasoning as `RevisionApi` and `IntakeClient`
    in `journey.py`: a test double only has to implement these methods, not
    *be* an `OrchestratorApi`. Extending `RevisionApi` rather than repeating
    its seven methods here keeps this to one Protocol family, not a third
    parallel one.
    """

    def resolve_version(self, unit_id: str, *, probe: dict, command: str = "ready") -> int: ...
    def command(self, unit_id: str, command: str, payload: dict, /) -> dict: ...
    def in_flight_units(self) -> dict: ...
    def dispatch(self, unit_id: str, payload: dict, /) -> dict: ...


def _unit_id_for_key(units: list[dict], unit_key: str) -> str | None:
    for unit in units:
        if unit["unit_key"] == unit_key:
            return unit["id"]
    return None


def _resolve_unit_id(
    api: ExecutionApi, revision_id: str, unit_key: str, *, verb: str
) -> str | None:
    """Resolve `--unit-key` to a unit id, printing the real keys on a miss."""
    units = units_for(api, revision_id)
    unit_id = _unit_id_for_key(units, unit_key)
    if unit_id is None:
        keys = ", ".join(sorted(u["unit_key"] for u in units)) or "(none)"
        print(
            f"{verb} failed: unknown --unit-key {unit_key!r}; known keys: {keys}", file=sys.stderr
        )
    return unit_id


def _in_flight_snapshot(api: ExecutionApi, unit_id: str) -> dict | None:
    """This unit's `version` + `attempt_count`, or `None` if it is not in flight
    (DRAFT, FAILED, COMPLETED, CANCELLED -- `dispatch` only ever acts on READY,
    which is in flight)."""
    for entry in api.in_flight_units().get("units", []):
        if str(entry.get("work_unit_id")) == unit_id:
            return entry
    return None


def _dispatch_history_facts(api: ExecutionApi, unit_id: str) -> tuple[int, str | None]:
    """The highest recorded dispatch ordinal, and that attempt's dispatch record id.

    Scans `history` for `dispatch.dispatched` events. Two field names matter
    and neither is what a first draft might guess: the event's KIND lives
    under `action` (`orchestrator.api.schemas.EventResponse.action`), not
    `type`; the dispatch record's id lives in the event's `payload` under
    `dispatch_record_id` (`orchestrator.services.dispatch._record_dispatch`),
    not `dispatch_id`. Getting either wrong makes this function silently
    return `(0, None)` forever -- exactly the failure mode this module exists
    to prevent -- so both were checked against the orchestrator's own
    `schemas.py`/`services/dispatch.py` before being written here.
    """
    latest = 0
    prior_id: str | None = None
    for event in api.history(unit_id).get("events", []):
        if event.get("action") != "dispatch.dispatched":
            continue
        payload = event.get("payload") or {}
        attempt = int(payload.get("runner_attempt", 0))
        if attempt >= latest:
            latest = attempt
            prior_id = payload.get("dispatch_record_id")
    return latest, prior_id


def next_runner_attempt(api: ExecutionApi, unit_id: str, attempt_count: int) -> int:
    """The next dispatch ordinal.

    Dispatch and claim ordinals are INDEPENDENT: `DispatchRecord.runner_attempt`
    counts dispatch decisions including skipped ones, while `attempt_count`
    counts worker claims. They drift apart the moment a dispatch is skipped or
    a claim is reclaimed, so `attempt_count + 1` is not a safe substitute for
    either.
    """
    latest, _ = _dispatch_history_facts(api, unit_id)
    return max(attempt_count, latest) + 1


def ready(revision_id: str, unit_key: str, *, api: ExecutionApi | None = None) -> int:
    """SYSTEM: move a unit DRAFT -> READY.

    Authority approval alone never does this (it only sets
    `authority_approval_id`); `ready` is the separate SYSTEM `(DRAFT, READY)`
    edge. The unit's current version is unknown up front (DRAFT units carry
    no `version` on any read surface), so this resolves it via
    `api.resolve_version`'s documented probe before posting the real command.
    """
    api = api or OrchestratorApi()
    try:
        revision_id = resolve_revision(revision_id)
    except RevisionRequired as error:
        print(f"ready failed: {error}", file=sys.stderr)
        return 2

    idempotency_key = f"factory-ready-{uuid.uuid4()}"
    try:
        unit_id = _resolve_unit_id(api, revision_id, unit_key, verb="ready")
        if unit_id is None:
            return 1
        version = api.resolve_version(
            unit_id, probe={"idempotency_key": idempotency_key}, command="ready"
        )
        result = api.command(
            unit_id, "ready", {"idempotency_key": idempotency_key, "expected_version": version}
        )
    except ApiError as error:
        print(f"ready failed: {error}", file=sys.stderr)
        return 1

    print(f"unit {unit_id} -> {result.get('state')} (version {result.get('version')})")
    print(f"next: factory dispatch --revision {revision_id} --unit-key {unit_key}")
    return 0


def dispatch(revision_id: str, unit_key: str, *, api: ExecutionApi | None = None) -> int:
    """SYSTEM: dispatch a READY unit to the runner.

    The unit is in flight (READY), so `version`/`attempt_count` come straight
    off `GET /in-flight-units` -- no probe. The computed `runner_attempt` is
    then checked against the response: a reused ordinal makes the orchestrator
    return the pre-existing `DispatchRecord` (same `id`, HTTP 200,
    `status: "dispatched"`) instead of triggering a new `workflow_dispatch`,
    so only a NEW record id proves this call actually dispatched anything --
    the `status` field is identical either way and must never be trusted
    alone.
    """
    api = api or OrchestratorApi()
    try:
        revision_id = resolve_revision(revision_id)
    except RevisionRequired as error:
        print(f"dispatch failed: {error}", file=sys.stderr)
        return 2

    try:
        unit_id = _resolve_unit_id(api, revision_id, unit_key, verb="dispatch")
        if unit_id is None:
            return 1
        snapshot = _in_flight_snapshot(api, unit_id)
        if snapshot is None:
            print(
                f"dispatch failed: unit {unit_id} is not in flight (state must be READY) -- "
                f"run: factory status --revision {revision_id}",
                file=sys.stderr,
            )
            return 1
        latest_runner_attempt, prior_dispatch_id = _dispatch_history_facts(api, unit_id)
        runner_attempt = max(snapshot["attempt_count"], latest_runner_attempt) + 1
        idempotency_key = f"factory-dispatch-{uuid.uuid4()}"
        response = api.dispatch(
            unit_id,
            {
                "idempotency_key": idempotency_key,
                "runner_attempt": runner_attempt,
                "expected_version": snapshot["version"],
            },
        )
    except ApiError as error:
        print(f"dispatch failed: {error}", file=sys.stderr)
        return 1

    new_id = response.get("id")
    if new_id and new_id == prior_dispatch_id:
        print(
            "dispatch was a silent no-op: the orchestrator returned the EXISTING record "
            f"({prior_dispatch_id}) because runner_attempt {runner_attempt} was already used. "
            "No workflow_dispatch fired. The response's status field says 'dispatched' either "
            "way -- never treat it as proof of dispatch.",
            file=sys.stderr,
        )
        return 1

    print(
        f"dispatched: record {new_id} (runner_attempt {runner_attempt}), "
        f"status={response.get('status')}"
    )
    print(
        "Reminder: closing the bounded dispatch window restarts the orchestrator -- wait for "
        "terminal (the Actions run concluded, the unit left EXECUTING, and cost-actuals exist) "
        "before closing it."
    )
    return 0
