"""The lifecycle-writing verbs: `ready` and `dispatch`.

Split out from `journey.py` (which stays the read/report surface -- `submit`,
`status`, `evidence`) because these two verbs carry version and dispatch-
ordinal hazards `journey.py`'s verbs do not: a wrong `expected_version` is a
clean `version_conflict`, but a wrong `runner_attempt` can be a SILENT NO-OP
-- the orchestrator returns a PRE-EXISTING `DispatchRecord` with HTTP 200,
having triggered no `workflow_dispatch` at all.

Proving a real dispatch happened takes THREE checks, not one -- fix round
1/5 found the first draft only had the third, and had it wrong:

1. The returned record id must not already appear anywhere in this unit's
   dispatch history (`dispatch.*` events, ALL FOUR outcomes -- dispatched,
   skipped, blocked, failed -- share one `runner_attempt` under the same
   `UniqueConstraint("work_unit_id", "runner_attempt")`, so any of them can
   be the record the orchestrator hands back on a reused ordinal). This is a
   SET-MEMBERSHIP check, not equality against "the latest one" -- the
   orchestrator returns the record at the OFFERED ordinal, which is never
   the highest existing one when the ordinal math is right, so comparing
   against only the highest-ordinal id made the check unsatisfiable.
2. The ordinal scan itself must count all four `dispatch.*` outcomes, not
   just `dispatch.dispatched` -- a skipped or blocked decision still
   consumes a `runner_attempt` row.
3. Even a genuinely NEW record proves nothing if `status != "dispatched"`
   -- the bounded window being closed (the orchestrator's normal resting
   state) mints a brand-new record with `status="skipped"`,
   `reason_code="dispatch_disabled"`, and no workflow fired. No id check
   can catch this, because the record really is new.

Where `version` and `attempt_count` come from is verb-specific:

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

# All four dispatch decisions share one `runner_attempt` under the same
# `UniqueConstraint("work_unit_id", "runner_attempt")` -- a skipped or
# blocked decision consumes an ordinal exactly as a dispatched one does.
_DISPATCH_ACTION_PREFIX = "dispatch."


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


def _dispatch_event_payloads(api: ExecutionApi, unit_id: str) -> list[tuple[str, dict]]:
    """One `history` read, pre-filtered to `dispatch.*` events, as `(status,
    payload)` pairs in event order -- `status` is the action suffix
    (`dispatched`, `skipped`, `blocked`, `failed`).

    This is the ONE place that knows how a dispatch event is shaped on the
    wire: the event's KIND lives under `action`
    (`orchestrator.api.schemas.EventResponse.action`), not `type`; the
    dispatch record's id lives in the event's `payload` under
    `dispatch_record_id` (`orchestrator.services.dispatch._record_dispatch`),
    not `dispatch_id`. `history()` itself returns a bare JSON array (fixed in
    fix round 1/5 -- it used to be typed `-> dict` over a route that was never
    one), so this iterates the list directly.

    Both `_scan_dispatch_events` (dispatch()'s ordinal + no-op-guard id set,
    which must count all FOUR outcomes -- `DISPATCH_RECORD_STATUSES` is
    `(dispatched, skipped, blocked, failed)`, all sharing one `runner_attempt`
    under the same unique constraint) and `latest_dispatched_payload`
    (verify()'s canonical-dispatch lookup, task 9, which only a `dispatched`
    outcome can ever satisfy) consume this single scan -- neither re-walks
    `history` with its own action-matching predicate.
    """
    events: list[tuple[str, dict]] = []
    for event in api.history(unit_id):
        action = event.get("action", "")
        if not action.startswith(_DISPATCH_ACTION_PREFIX):
            continue
        events.append((action[len(_DISPATCH_ACTION_PREFIX) :], event.get("payload") or {}))
    return events


def _scan_dispatch_events(api: ExecutionApi, unit_id: str) -> tuple[int, frozenset[str]]:
    """The highest consumed dispatch ordinal, and EVERY `DispatchRecord` id
    already recorded for this unit -- not just the one at the highest
    ordinal. Filtering to only `dispatched` would under-read the highest
    consumed ordinal (fix round 1/5, Critical 2) -- e.g. a dispatch skipped by
    a closed window still occupies its ordinal.

    Called exactly ONCE per `dispatch()` invocation -- one `api.history()`
    request, not two (fix round 2/5). `dispatch()` feeds the returned
    `latest` into `next_runner_attempt` and the returned record-id set
    straight into the no-op guard, rather than re-deriving either
    separately.
    """
    latest = 0
    record_ids: set[str] = set()
    for _status, payload in _dispatch_event_payloads(api, unit_id):
        record_id = payload.get("dispatch_record_id")
        if record_id:
            record_ids.add(record_id)
        attempt = int(payload.get("runner_attempt", 0))
        if attempt > latest:
            latest = attempt
    return latest, frozenset(record_ids)


def latest_dispatched_payload(api: ExecutionApi, unit_id: str) -> dict | None:
    """The payload of the highest-`runner_attempt` `dispatch.dispatched`
    event -- the canonical dispatch a named-check attests to (`verify`, task
    9's `dispatch_id`/`repository` source).

    Narrower than `_scan_dispatch_events` on purpose: a named-check can only
    ever validate against a dispatch whose `DispatchRecord.status ==
    "dispatched"` (`services/verifier_named_check.py::validate_named_check_bindings`
    checks `dispatch.status != "dispatched"`), so a skipped/blocked/failed
    ordinal -- even if it is the highest one -- is never a candidate here,
    unlike the ordinal scan dispatch() itself needs.
    """
    latest_attempt = -1
    latest_payload: dict | None = None
    for status, payload in _dispatch_event_payloads(api, unit_id):
        if status != "dispatched":
            continue
        attempt = int(payload.get("runner_attempt", 0))
        if attempt > latest_attempt:
            latest_attempt = attempt
            latest_payload = payload
    return latest_payload


def next_runner_attempt(attempt_count: int, latest_runner_attempt: int) -> int:
    """The next dispatch ordinal, given facts already scanned from `history`.

    Dispatch and claim ordinals are INDEPENDENT: `DispatchRecord.runner_attempt`
    counts dispatch decisions including skipped ones, while `attempt_count`
    counts worker claims. They drift apart the moment a dispatch is skipped or
    a claim is reclaimed, so `attempt_count + 1` is not a safe substitute for
    either.

    Fix round 2/5: this used to take `(api, unit_id, attempt_count)` and do
    its own `_scan_dispatch_events` call -- so `dispatch()`, which also needs
    the record-id set from that same scan, called it twice (once here, once
    via a second helper), issuing two `api.history()` requests for what
    should be one atomic read. The fix for Important 2 (fix round 1/5) was
    never "this function must do its own I/O" -- only that `dispatch()` must
    call the SAME tested arithmetic it is measured by, not a parallel inline
    copy. Making this a pure function over the scan's own outputs satisfies
    that while collapsing the read to one: `dispatch()` (and only
    `dispatch()`) calls `_scan_dispatch_events`, once, and feeds both
    resulting facts onward -- `latest_runner_attempt` here, the record-id set
    into the no-op guard. Two sequential reads could also disagree if a
    concurrent dispatch landed in between; one read cannot.
    """
    return max(attempt_count, latest_runner_attempt) + 1


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
    off `GET /in-flight-units` -- no probe. `history` is read exactly ONCE
    (fix round 2/5: it used to be read twice -- once to derive the ordinal,
    once more to derive the no-op guard's record-id set -- which was both a
    wasted round trip and a real TOCTOU window, since a concurrent dispatch
    landing between the two reads could make them disagree). `runner_attempt`
    is computed by `next_runner_attempt`, the one function both this call and
    its own tests exercise for the arithmetic (fix round 1/5, Important 2).

    A response is only accepted as a real dispatch when ALL of: (1) its
    record id is not one already recorded for this unit at any earlier
    ordinal (any of the four `dispatch.*` outcomes), and (2) `status ==
    "dispatched"` -- a brand-new record with `status="skipped"` (e.g. the
    bounded window is closed) proves nothing was dispatched either, and no
    id check can catch that case because the record really is new.
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
        latest_runner_attempt, prior_dispatch_ids = _scan_dispatch_events(api, unit_id)
        runner_attempt = next_runner_attempt(snapshot["attempt_count"], latest_runner_attempt)
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
    if new_id is not None and new_id in prior_dispatch_ids:
        print(
            f"dispatch was a silent no-op: the returned record ({new_id}) was ALREADY in this "
            "unit's dispatch history -- no new workflow_dispatch fired for this call. The "
            "response's status field says 'dispatched' either way and is never proof by itself.",
            file=sys.stderr,
        )
        return 1

    status = response.get("status")
    if status != "dispatched":
        print(
            f"dispatch failed: record {new_id} was recorded with status={status!r}, "
            f"reason_code={response.get('reason_code')!r} -- no workflow_dispatch fired",
            file=sys.stderr,
        )
        return 1

    print(f"dispatched: record {new_id} (runner_attempt {runner_attempt}), status={status}")
    run_url = response.get("github_run_url")
    if run_url:
        print(f"Actions run: {run_url}")
    print(
        "Reminder: closing the bounded dispatch window restarts the orchestrator -- wait for "
        "terminal (the Actions run concluded, the unit left EXECUTING, and cost-actuals exist) "
        "before closing it."
    )
    return 0
