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

Every derived read this module runs on -- `resolve_revision`, `resolve_unit_id`,
`in_flight_snapshot`, `scan_dispatch_events`, `latest_dispatched_payload` and the
read Protocol -- lives in `reads.py`, which `journey.py` and `verify.py` import
too. This module owns only the two writes and the ordinal arithmetic.
"""

from __future__ import annotations

import sys
import uuid
from typing import Protocol

from intent_packages.factory import reads
from intent_packages.factory.api import ApiError, OrchestratorApi
from intent_packages.factory.reads import (
    InFlightApi,
    RevisionApi,
    RevisionRequired,
    resolve_revision,
)

# A timeout or connection failure on the dispatch POST is INCONCLUSIVE, not a
# failure: the request may have been received and acted on. Every other
# `ApiError` code carries a server verdict and is reported as-is.
_INCONCLUSIVE_CODES = frozenset({"api_timeout", "api_unavailable"})


class ExecutionApi(RevisionApi, InFlightApi, Protocol):
    """`RevisionApi` + `InFlightApi` (the derived reads these two verbs run on)
    plus the three writes `ready` and `dispatch` make.

    A structural `Protocol`, same reasoning as `RevisionApi`: a test double only
    has to implement these methods, not *be* an `OrchestratorApi`. Extending
    `RevisionApi` rather than repeating its methods keeps this to one Protocol
    family, not a parallel one.
    """

    def resolve_version(self, unit_id: str, *, probe: dict, command: str = "ready") -> int: ...
    def command(self, unit_id: str, command: str, payload: dict, /) -> dict: ...
    def dispatch(self, unit_id: str, payload: dict, /) -> dict: ...


def next_runner_attempt(attempt_count: int, latest_runner_attempt: int) -> int:
    """The next dispatch ordinal, given facts already scanned from `history`.

    Dispatch and claim ordinals are INDEPENDENT: `DispatchRecord.runner_attempt`
    counts dispatch decisions including skipped ones, while `attempt_count`
    counts worker claims. They drift apart the moment a dispatch is skipped or
    a claim is reclaimed, so `attempt_count + 1` is not a safe substitute for
    either.

    Fix round 2/5: this used to take `(api, unit_id, attempt_count)` and do its
    own history scan -- so `dispatch()`, which also needs the record-id set from
    that same scan, called it twice, issuing two `api.history()` requests for
    what should be one atomic read. The fix for Important 2 (fix round 1/5) was
    never "this function must do its own I/O" -- only that `dispatch()` must
    call the SAME tested arithmetic it is measured by, not a parallel inline
    copy. Making this a pure function over the scan's own outputs satisfies that
    while collapsing the read to one: `dispatch()` calls
    `reads.scan_dispatch_events` once and feeds both resulting facts onward --
    `latest_runner_attempt` here, the record-id set into the no-op guard. Two
    sequential reads could also disagree if a concurrent dispatch landed in
    between; one read cannot.
    """
    return max(attempt_count, latest_runner_attempt) + 1


def ready(
    revision_id: str, unit_key: str, *, api: ExecutionApi | None = None, verbose: bool = False
) -> int:
    """SYSTEM: move a unit DRAFT -> READY.

    Authority approval alone never does this (it only sets
    `authority_approval_id`); `ready` is the separate SYSTEM `(DRAFT, READY)`
    edge. The unit's current version is unknown up front (DRAFT units carry
    no `version` on any read surface), so this resolves it via
    `api.resolve_version`'s documented probe before posting the real command.
    """
    api = api or OrchestratorApi(verbose=verbose)
    try:
        revision_id = resolve_revision(revision_id)
    except RevisionRequired as error:
        print(f"ready failed: {error}", file=sys.stderr)
        return 2

    idempotency_key = f"factory-ready-{uuid.uuid4()}"
    try:
        unit_id = reads.resolve_unit_id(api, revision_id, unit_key, verb="ready")
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


def dispatch(
    revision_id: str, unit_key: str, *, api: ExecutionApi | None = None, verbose: bool = False
) -> int:
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

    And when the POST itself times out, the answer is neither: see
    `_reconcile_inconclusive_dispatch`. This is the only verb with an
    irreversible external effect, so "did it land?" has to be answered rather
    than left to the operator's judgement.
    """
    api = api or OrchestratorApi(verbose=verbose)
    try:
        revision_id = resolve_revision(revision_id)
    except RevisionRequired as error:
        print(f"dispatch failed: {error}", file=sys.stderr)
        return 2

    unit_id: str | None = None
    runner_attempt = 0
    prior_dispatch_ids: frozenset[str] = frozenset()
    # A separate flag, not `prior_dispatch_ids` being empty: an empty set is the
    # legitimate "never dispatched" case, and reconciling against a scan that
    # never ran would report every prior record as newly landed.
    scanned_before_post = False
    try:
        unit_id = reads.resolve_unit_id(api, revision_id, unit_key, verb="dispatch")
        if unit_id is None:
            return 1
        snapshot = reads.in_flight_snapshot(api, unit_id)
        if snapshot is None:
            print(
                f"dispatch failed: unit {unit_id} is not in flight (state must be READY) -- "
                f"run: factory status --revision {revision_id}",
                file=sys.stderr,
            )
            return 1
        latest_runner_attempt, prior_dispatch_ids = reads.scan_dispatch_events(api, unit_id)
        scanned_before_post = True
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
        if error.code in _INCONCLUSIVE_CODES and unit_id and scanned_before_post:
            _reconcile_inconclusive_dispatch(api, unit_id, revision_id, prior_dispatch_ids)
        return 1

    return _report_dispatch_outcome(response, prior_dispatch_ids, runner_attempt)


def _reconcile_inconclusive_dispatch(
    api: ExecutionApi,
    unit_id: str,
    revision_id: str,
    prior_dispatch_ids: frozenset[str],
) -> None:
    """Say whether an inconclusive dispatch POST actually landed.

    A 30-second timeout on `POST .../dispatch` does NOT mean nothing happened:
    the orchestrator commits the `DispatchRecord` and fires the
    `workflow_dispatch` before the response reaches us, and the window in which
    the response is slow is precisely the Actions queue delay -- i.e. exactly
    when an operator would retry.

    Retrying is NOT safe. The orchestrator does have a replay path -- it
    short-circuits on `idempotency_key` BEFORE the ordinal check and hands back
    the identical record -- but every `factory dispatch` invocation mints a fresh
    `factory-dispatch-{uuid4()}`, so a retry can never reach it. It computes a
    new ordinal instead and fires a SECOND real workflow run, which is how two
    live dispatches (ordinals 1 and 2) were demonstrated with the second exiting
    0.

    So the decision is made from data already in hand: re-read `history` and diff
    against the record-id set captured BEFORE the POST. A new `dispatch.*` record
    means it landed. Deliberately NOT solved by persisting the idempotency key --
    decision 4 of the design is that this tool holds no state between runs, and a
    key file is a second source of truth that can go stale. The caller has
    already printed the failure and returns non-zero either way; this adds the
    verdict.
    """
    try:
        _latest, current_ids = reads.scan_dispatch_events(api, unit_id)
    except ApiError as reread_error:
        print(
            f"dispatch: could NOT determine whether it landed ({reread_error}) -- do not retry "
            f"blind; run: factory status --revision {revision_id} and compare the latest "
            "dispatch ordinal before deciding",
            file=sys.stderr,
        )
        return
    landed = current_ids - prior_dispatch_ids
    if landed:
        print(
            "dispatch: IT LANDED. A new dispatch record "
            f"({', '.join(sorted(landed))}) appeared on re-read, so the request WAS acted on and "
            "a workflow_dispatch fired despite the timeout. DO NOT RETRY -- a retry mints a fresh "
            "idempotency key, computes the next ordinal and fires a SECOND real run. Confirm the "
            f"Actions run, then continue with: factory status --revision {revision_id}",
            file=sys.stderr,
        )
        return
    print(
        "dispatch: it did not land -- no new dispatch record appeared on re-read, so nothing was "
        "dispatched and re-running this command is safe.",
        file=sys.stderr,
    )


def _report_dispatch_outcome(
    response: dict, prior_dispatch_ids: frozenset[str], runner_attempt: int
) -> int:
    """Accept the response as a real dispatch, or say exactly why it is not.

    Extracted from `dispatch()` to keep both under the C901 ceiling once the
    inconclusive-POST branch joined.
    """
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
