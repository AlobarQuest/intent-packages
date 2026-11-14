"""The approval check against the database chain of record (orchestrator ADR-0055 amendment 24).

`default_chain_checker` runs this module under the security-standards events interpreter
(`python -m intent_packages.chain_db <approved_hash> <revision>`), with that repository's `src`
on `PYTHONPATH`, when `FACTORY_EVENTS_READ_PASSWORD` is set. It walks the chain and looks for the
matching `package.approved` event in one read-only transaction at repeatable read, so the walk
and the match see one snapshot (item 8). The walk is `factory_events.store.walk_records`, the
walker FE-1 uses for both chains; the `SELECT` is the one FE-1's README gives readers in other
repositories.

The result is the exit code: `MATCH`, `NO_MATCH` (the chain verified and holds no matching
event), or `UNAVAILABLE` for anything else. The connection is the read role's, built from its
password and the three settings by `factory_events.chain.connection_params` (amendment 26),
and passed to psycopg as keyword parameters. A setting that refuses is reported by name; any
later failure only by its type, because a driver error's text can repeat connection details.

The top level imports only the standard library, because `operations` imports
`evidence_matches` from here in an interpreter that has neither psycopg nor `factory_events`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from importlib import import_module
from typing import Protocol

MATCH = 0
NO_MATCH = 10
UNAVAILABLE = 2
CONNECT_TIMEOUT_SECONDS = 10
HEAD_PREFIX = 12

_WALK = "SELECT seq, prev_hash, hash, event_id, event FROM factory_events ORDER BY seq"


def evidence_matches(evidence: object, approved_hash: str, revision: int) -> bool:
    """True iff any item in `evidence` (a list of evidence records) carries
    this exact `approved_hash` + `revision`. Guards against a non-list
    `evidence` or non-dict items."""
    if not isinstance(evidence, list):
        return False
    return any(
        isinstance(e, dict)
        and e.get("approved_hash") == approved_hash
        and e.get("revision") == revision
        for e in evidence
    )


def _log(outcome: str, **fields: object) -> None:
    """One structured JSON record on stdout (item 13). Never pass a password or a driver's text."""
    record = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "logger": "intent_packages.chain_db",
        "op": "verify-approval",
        "outcome": outcome,
        **{key: value for key, value in fields.items() if value is not None},
    }
    print(json.dumps(record, sort_keys=True), flush=True)


def _records(
    rows: Iterable[tuple], approved_hash: str, revision: int, matches: list[str]
) -> Iterator[dict]:
    """Map rows to the walker's records, noting each matching approval's event id as it passes.

    A match only counts when the walk reports no error, so noting it before the walker checks
    the row is safe: a broken row anywhere makes the whole read unavailable.
    """
    for seq, prev_hash, hash_hex, event_id, event_text in rows:
        try:
            event = json.loads(event_text)
        except TypeError, json.JSONDecodeError:
            event = None  # the walker reports it as a tampered row
        if (
            isinstance(event, dict)
            and event.get("action") == "package.approved"
            and evidence_matches(event.get("evidence"), approved_hash, revision)
        ):
            matches.append(event_id)
        yield {
            "seq": seq,
            "prev_hash": prev_hash,
            "hash": hash_hex,
            "event_id": event_id,
            "event": event,
        }


class _ConnectParams(Protocol):
    """`factory_events.db.ConnectParams`, which this module can't import at its top level."""

    def as_kwargs(self) -> dict[str, str]: ...


def _walk(
    params: _ConnectParams, approved_hash: str, revision: int
) -> tuple[list[str], dict | None, int, list]:
    """`params.as_kwargs()` holds the password, so it goes straight to `psycopg.connect` and is
    never logged."""
    psycopg = import_module("psycopg")
    store = import_module("factory_events.store")
    matches: list[str] = []
    with psycopg.connect(
        **params.as_kwargs(),
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        application_name="intent_packages",
    ) as conn:
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction(), conn.cursor(name="intent_packages_approval_walk") as cur:
            cur.execute(_WALK)
            errors, last, count = store.walk_records(
                _records(cur, approved_hash, revision, matches)
            )
    return errors, last, count, matches


def _failed(exc: Exception) -> int:
    """Log and report a failure by its type only: a driver's text can repeat connection details.
    Not a swallow: the caller raises UNAVAILABLE as ChainUnavailable."""
    _log("failure", error_type=type(exc).__name__)
    print(f"chain read failed ({type(exc).__name__})", file=sys.stderr)
    return UNAVAILABLE


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        approved_hash, revision = args[0], int(args[1])
        chain = import_module("factory_events.chain")
        # An AttributeError here means a security-standards checkout older than amendment 26.
        refusal, connection_params, read_role = (
            chain.db.ChainError,
            chain.connection_params,
            chain.READ_ROLE,
        )
    except Exception as exc:
        return _failed(exc)
    try:
        params = connection_params(read_role)  # strictly the read role: no append fallback
    except refusal as exc:
        # Not swallowed: a missing or retired setting, refused before any connection and
        # reported as UNAVAILABLE. Logged as any failure is; factory_events.chain's refusal
        # names only the variable, never a value (amendment 26 item 5), so its text is printed.
        _log("failure", error_type=type(exc).__name__)
        print(f"chain read refused: {exc}", file=sys.stderr)
        return UNAVAILABLE
    try:
        errors, last, count, matches = _walk(params, approved_hash, revision)
    except Exception as exc:
        return _failed(exc)
    head = last["hash"][:HEAD_PREFIX] if last else None
    seq = last["seq"] if last else 0
    if errors:
        _log("broken", seq=seq, head=head, events=count)
        print(f"chain broken: {errors[0]}", file=sys.stderr)
        return UNAVAILABLE
    _log(
        "match" if matches else "no-match",
        seq=seq,
        head=head,
        events=count,
        event_id=matches[0] if matches else None,
    )
    return MATCH if matches else NO_MATCH


if __name__ == "__main__":
    sys.exit(main())
