"""Every DERIVED read the front door makes -- owned in one place.

Decision 4 of the design is that `--revision` is the only id the operator ever
supplies; everything else is re-derived from the API on every run. The
derivations themselves are what this module owns: resolving a revision, turning
`traceability` into a flat per-unit view, resolving a `--unit-key` to a unit id,
finding a unit's in-flight row, and scanning its dispatch history.

**Why a module of its own.** Those derivations were spread across `journey.py`
and `execution.py`, and `execution` imports `journey` -- so every attempt to
share one more of them pushed code INTO the read/report module that the
lifecycle-writing module depends on. Two duplications had already appeared:
`_unit_id_for_key` existed byte-identically in both files, and
`journey.evidence` reimplemented what is now `resolve_unit_id` here -- the function
that had been made public specifically to be shared -- down to a near-identical
error string. `journey.py`, `execution.py` and `verify.py` now all import from
here and none imports another.

The wire facts encoded here, each verified against the live
`https://sds.alobar.net/openapi.json` rather than inferred from prose:

- `GET /traceability` is a JSON OBJECT: `{anchor, chains[]}`, each chain
  carrying `intent`/`unit`/`pr`/`commit`/... hops.
- `TraceabilityUnitHop` carries `id`, `unit_key`, `title`, `state`,
  `authority_fingerprint`, `authority_approved_by`, `authority_decision`.
- `TraceabilityPrHop` is `{pr_number, head_sha}` -- nothing else.
- `GET /work-units/{id}/history` is a BARE JSON ARRAY of `EventResponse`, whose
  event kind lives under `action` (never `type`).
- `GET /in-flight-units` is a JSON object `{units[], release_bindings[]}` and
  its rows key on `work_unit_id` (never `id`).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Protocol


class RevisionApi(Protocol):
    """The pure-read surface every derivation here needs.

    A structural `Protocol`, not the concrete `OrchestratorApi`: a test double
    only has to implement these methods, not *be* an `OrchestratorApi`. The
    concrete client satisfies it structurally, so production callers pass it
    unchanged. `execution.ExecutionApi` and `verify.VerifyApi` extend this with
    the writes their verbs make, so there is ONE Protocol family rather than
    three parallel ones.

    `readiness` is deliberately absent and its client method has been deleted:
    the next-action logic derives the next step entirely from a unit's `state`,
    so fetching readiness per unit was a round trip for a value nothing read.
    """

    def get_intake(self, revision_id: str) -> dict: ...
    def list_proposals(self, revision_id: str) -> list[dict]: ...
    def traceability(
        self, *, revision_id: str | None = None, work_unit_id: str | None = None
    ) -> Any: ...
    def history(self, unit_id: str) -> list[dict]: ...
    def evidence_pack(self, unit_id: str) -> dict: ...
    def revision_evidence_pack(self, revision_id: str) -> dict: ...
    def evidence_pack_markdown(self, unit_id: str) -> str: ...


class InFlightApi(Protocol):
    """Just `in_flight_units`, which is all `in_flight_snapshot` needs.

    Deliberately NOT folded into `RevisionApi`: `journey`'s verbs never read
    in-flight rows, and a Protocol that demanded the method of them would assert
    a dependency `status`/`evidence` do not have. `ExecutionApi` and `VerifyApi`
    each extend both.
    """

    def in_flight_units(self) -> dict: ...


class RevisionRequired(Exception):
    """Raised when neither `--revision` nor `$FACTORY_REVISION` is set.

    Public, and caught by every verb across three modules, so it has to be part
    of this module's public surface -- a caller elsewhere has nothing precise to
    catch otherwise. Each verb maps it to exit 2, which is reserved for exactly
    this condition.
    """


def resolve_revision(revision_id: str) -> str:
    """Fall back to `$FACTORY_REVISION`; raise when neither is set.

    Shared by every verb that operates on a revision -- `status`, `evidence`,
    `ready`, `dispatch`, `verify` -- so the exit-2 behaviour for a missing
    revision lives in exactly one place.
    """
    if revision_id:
        return revision_id
    from_env = os.environ.get("FACTORY_REVISION", "")
    if from_env:
        return from_env
    raise RevisionRequired("no revision id: pass --revision or set $FACTORY_REVISION")


def units_for(api: RevisionApi, revision_id: str) -> list[dict]:
    """Derive the per-unit view of a revision from `traceability`.

    The single derivation point: no verb re-derives units from `traceability`
    itself. Each returned dict is the chain's `unit` hop (`id`, `unit_key`,
    `state`, `authority_fingerprint`, `authority_approved_by`,
    `authority_decision`) with a `pr` key added when the chain carries one --
    `TraceabilityPrHop`, i.e. `{pr_number, head_sha}` and nothing else.
    """
    data = api.traceability(revision_id=revision_id)
    units = []
    for chain in data.get("chains", []):
        unit = chain["unit"]
        entry = {
            "id": unit["id"],
            "unit_key": unit["unit_key"],
            "state": unit["state"],
            "authority_fingerprint": unit.get("authority_fingerprint"),
            "authority_approved_by": unit.get("authority_approved_by"),
            "authority_decision": unit.get("authority_decision"),
        }
        pr = chain.get("pr")
        if pr is not None:
            entry["pr"] = pr
        units.append(entry)
    return units


def _unit_id_for_key(units: list[dict], unit_key: str) -> str | None:
    for unit in units:
        if unit["unit_key"] == unit_key:
            return unit["id"]
    return None


def resolve_unit_id(api: RevisionApi, revision_id: str, unit_key: str, *, verb: str) -> str | None:
    """Resolve `--unit-key` to a unit id, printing the real keys on a miss.

    Used by `evidence`, `ready`, `dispatch` and `verify`, which is why `verb`
    is a parameter: the refusal line has to name the verb the operator actually
    typed. Returns `None` after printing; every caller maps that to exit 1.
    """
    units = units_for(api, revision_id)
    unit_id = _unit_id_for_key(units, unit_key)
    if unit_id is None:
        keys = ", ".join(sorted(u["unit_key"] for u in units)) or "(none)"
        print(
            f"{verb} failed: unknown --unit-key {unit_key!r}; known keys: {keys}", file=sys.stderr
        )
    return unit_id


def in_flight_snapshot(api: InFlightApi, unit_id: str) -> dict | None:
    """This unit's full in-flight row, or `None` if it is not in flight.

    DRAFT, FAILED, COMPLETED and CANCELLED units are all absent from
    `GET /in-flight-units` (`orchestrator.services.in_flight.IN_FLIGHT_STATES`),
    which is the only read surface carrying `version` or `attempt_count` at all.
    `dispatch` reads `version`/`attempt_count` off the returned row; `verify`
    reads `pr_number`, `head_sha`, `verification_read_head_sha`,
    `work_package_revision_id`, `version` and `state` off the same row. One
    place knows that in-flight rows key on `work_unit_id`.
    """
    for entry in api.in_flight_units().get("units", []):
        if str(entry.get("work_unit_id")) == unit_id:
            return entry
    return None


# All four dispatch decisions share one `runner_attempt` under the same
# `UniqueConstraint("work_unit_id", "runner_attempt")` -- a skipped or blocked
# decision consumes an ordinal exactly as a dispatched one does.
_DISPATCH_ACTION_PREFIX = "dispatch."


def _dispatch_event_payloads(api: RevisionApi, unit_id: str) -> list[tuple[str, dict]]:
    """One `history` read, pre-filtered to `dispatch.*` events, as `(status,
    payload)` pairs in event order -- `status` is the action suffix
    (`dispatched`, `skipped`, `blocked`, `failed`).

    This is the ONE place that knows how a dispatch event is shaped on the wire:
    the event's KIND lives under `action` (`orchestrator.api.schemas.
    EventResponse.action`), not `type`; the dispatch record's id lives in the
    event's `payload` under `dispatch_record_id`
    (`orchestrator.services.dispatch._record_dispatch`), not `dispatch_id`.
    `history()` returns a bare JSON array, so this iterates the list directly.

    Both `scan_dispatch_events` and `latest_dispatched_payload` consume this
    single scan -- neither re-walks `history` with its own predicate.
    """
    events: list[tuple[str, dict]] = []
    for event in api.history(unit_id):
        action = event.get("action", "")
        if not action.startswith(_DISPATCH_ACTION_PREFIX):
            continue
        events.append((action[len(_DISPATCH_ACTION_PREFIX) :], event.get("payload") or {}))
    return events


def scan_dispatch_events(api: RevisionApi, unit_id: str) -> tuple[int, frozenset[str]]:
    """The highest consumed dispatch ordinal, and EVERY `DispatchRecord` id
    already recorded for this unit -- not just the one at the highest ordinal.

    Filtering to only `dispatched` would under-read the highest consumed
    ordinal: `DISPATCH_RECORD_STATUSES` is `(dispatched, skipped, blocked,
    failed)` and all four consume a `runner_attempt`, so a dispatch skipped by a
    closed window still occupies its ordinal. `dispatch()` calls this exactly
    once per invocation -- one `history` request, not two -- and feeds the
    ordinal into `next_runner_attempt` and the id set into its no-op guard.
    `status` calls it to report the latest ordinal.
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


def latest_dispatched_payload(api: RevisionApi, unit_id: str) -> dict | None:
    """The payload of the highest-`runner_attempt` `dispatch.dispatched` event
    -- the canonical dispatch a named-check attests to (`verify`'s `dispatch_id`
    and `repository` source).

    Narrower than `scan_dispatch_events` on purpose: a named-check can only ever
    validate against a dispatch whose `DispatchRecord.status == "dispatched"`
    (`services/verifier_named_check.py::validate_named_check_bindings` checks
    `dispatch.status != "dispatched"`), so a skipped/blocked/failed ordinal --
    even the highest one -- is never a candidate here.
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
