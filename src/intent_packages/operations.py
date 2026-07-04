"""State-changing package operations (spec section 5/9): `transition`,
`approve`, `revise`, `supersede`, and the read-only `verify_approval` gate.

Each state-changing operation loads the package, re-validates it (refusing to
act on an invalid package), enacts the change against both `package.yaml` and
`lineage.yaml`, and best-effort emits a factory event — a failed emit never
blocks the operation, it just records `event_id: null`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from intent_packages import canonical, lifecycle, lineage, registry
from intent_packages.emitter import EmitError, Emitter, _events_python, _security_standards_dir
from intent_packages.loader import load_package
from intent_packages.validate import validate_package

_STATUS_LINE_RE = re.compile(r"^status:.*$", re.MULTILINE)
_REVISION_LINE_RE = re.compile(r"^revision:.*$", re.MULTILINE)
_CHAIN_VERIFY_TIMEOUT_SECONDS = 30


class OperationError(Exception):
    """Raised when an operation is refused: invalid package or illegal transition."""


class ChainUnavailable(Exception):
    """Raised by a `chain_checker` when the factory-events chain cannot be
    consulted at all (store or security-standards checkout missing,
    subprocess failure, chain integrity check failed). `verify_approval`
    catches this and fails closed rather than letting it bubble up.
    """


def set_status_in_file(pkg_dir: str | Path, new_status: str) -> None:
    """Replace the top-level `status:` line in package.yaml in place.

    `package.yaml` is hand-authored (Devon reviews its diffs; it may carry
    comments and a deliberate key ordering), so this never re-dumps the whole
    document — it does a targeted, line-oriented replacement of the one
    `status:` line and leaves every other byte untouched. Safe because
    `status` is guaranteed a plain top-level scalar by strict typing (check J).
    """
    path = Path(pkg_dir) / "package.yaml"
    text = path.read_text(encoding="utf-8")
    new_text, count = _STATUS_LINE_RE.subn(f"status: {new_status}", text, count=1)
    if count != 1:
        raise OperationError("package.yaml: could not find a top-level `status:` line to update")
    path.write_text(new_text, encoding="utf-8")


def set_revision_in_file(pkg_dir: str | Path, new_revision: int) -> None:
    """Replace the top-level `revision:` line in package.yaml in place.

    Same targeted-line-edit approach as `set_status_in_file` — `revision` is
    guaranteed a plain top-level scalar by strict typing, so this preserves
    every other byte of the hand-authored file.
    """
    path = Path(pkg_dir) / "package.yaml"
    text = path.read_text(encoding="utf-8")
    new_text, count = _REVISION_LINE_RE.subn(f"revision: {new_revision}", text, count=1)
    if count != 1:
        raise OperationError(
            "package.yaml: could not find a top-level `revision:` line to update"
        )
    path.write_text(new_text, encoding="utf-8")


def do_transition(
    pkg_dir: str | Path,
    to_state: str,
    *,
    emitter: Emitter,
    actor: str = "claude-code-interactive",
    now: str,
) -> None:
    """Transition the package at `pkg_dir` to `to_state`.

    Refuses (raises `OperationError`) if the package is currently invalid, or
    if `to_state` is not a legal transition from the current lineage state.
    On `ready_for_review`, re-snapshots the current revision's hash first, to
    capture any draft edits made since the last snapshot. The factory-event
    emit is best-effort: a raised `EmitError` is swallowed and recorded as a
    `null` `event_id` rather than blocking the transition.
    """
    pkg_dir = Path(pkg_dir)

    errors = validate_package(pkg_dir)
    if errors:
        raise OperationError(
            "refusing to transition an invalid package:\n" + "\n".join(errors)
        )

    package = load_package(pkg_dir)
    lin = lineage.read(pkg_dir)
    current = lin["current_state"]

    if not lifecycle.is_legal_transition(current, to_state):
        raise OperationError(f"illegal transition: {current!r} -> {to_state!r}")

    if to_state == "ready_for_review":
        lineage.snapshot_revision(
            lin, package["revision"], canonical.package_hash(package), now, actor
        )

    try:
        event_id = emitter.emit(
            "package.transitioned",
            package["package_id"],
            {"from": current, "to": to_state, "revision": package["revision"]},
        )
    except EmitError:
        event_id = None

    lineage.append_transition(lin, "transition", current, to_state, now, actor, event_id)
    lin["current_state"] = to_state
    lineage.write(pkg_dir, lin)

    set_status_in_file(pkg_dir, to_state)


def do_approve(
    pkg_dir: str | Path,
    *,
    emitter: Emitter,
    approver: str = "devon",
    commit: str,
    now: str,
) -> None:
    """Approve the package at `pkg_dir` (ready_for_review -> approved).

    Approval is the sensitive, audited transition (spec §8) — unlike every
    other operation here, the emit is FATAL, not best-effort: if it fails,
    nothing is written, so an unaudited approval can never exist. Order
    matters for crash-safety:
      1. `validate_package` first — refuse an invalid package outright.
      2. `current_state` must be `ready_for_review` (or, for idempotent
         replay only, already `approved` — see step 6).
      3. `scope.open_questions` must be empty. `validate_package` only warns
         about this (check O); approval is where it becomes a hard error.
      4. `approver` must resolve to a human-operator registry identity —
         approval is a human act.
      5. Compute the package hash.
      6. Idempotency (MVP, lineage-based): if `lineage["approvals"]` already
         has an entry for this exact hash by a human-operator approver, this
         is a repeat call (e.g. retried after a crash between `lineage.write`
         and `set_status_in_file`, or simply called twice) — complete any
         missing write, but never re-emit or double-append. A stronger,
         hash-chain-verified idempotency check is a documented Phase-3
         refinement; this is sufficient for MVP.
      7. Emit `package.approved`. A raised `EmitError` aborts here — nothing
         below this point runs.
      8. Only after a successful emit: append the approval, flip
         `current_state`, write lineage, then flip `status` in package.yaml.
    """
    pkg_dir = Path(pkg_dir)

    errors = validate_package(pkg_dir)
    if errors:
        raise OperationError(
            "refusing to approve an invalid package:\n" + "\n".join(errors)
        )

    package = load_package(pkg_dir)
    lin = lineage.read(pkg_dir)
    current = lin["current_state"]

    if current not in ("ready_for_review", "approved"):
        raise OperationError(
            f"illegal transition: {current!r} -> 'approved' "
            "(approve is only legal from 'ready_for_review')"
        )

    if package["scope"]["open_questions"]:
        raise OperationError("refusing to approve: scope.open_questions is not empty")

    if not registry.is_human_operator(approver):
        raise OperationError(
            f"approval is a human act; {approver!r} is not a human-operator identity"
        )

    h = canonical.package_hash(package)

    already_approved = any(
        a["approved_hash"] == h and registry.is_human_operator(a["approver"])
        for a in lin.get("approvals", [])
    )
    if already_approved:
        if lin["current_state"] != "approved":
            lin["current_state"] = "approved"
            lineage.write(pkg_dir, lin)
        if package["status"] != "approved":
            set_status_in_file(pkg_dir, "approved")
        return

    if current != "ready_for_review":
        raise OperationError(
            f"illegal transition: {current!r} -> 'approved' "
            "(approve is only legal from 'ready_for_review')"
        )

    try:
        event_id = emitter.emit(
            "package.approved",
            package["package_id"],
            {
                "revision": package["revision"],
                "approved_hash": h,
                "approver": approver,
                "commit": commit,
            },
        )
    except EmitError as exc:
        raise OperationError(f"approval emit failed, aborting: {exc}") from exc

    lineage.append_approval(lin, package["revision"], h, approver, now, commit, event_id)
    lin["current_state"] = "approved"
    lineage.write(pkg_dir, lin)
    set_status_in_file(pkg_dir, "approved")


def do_revise(
    pkg_dir: str | Path,
    *,
    emitter: Emitter,
    actor: str = "claude-code-interactive",
    now: str,
) -> None:
    """Resolve a material intent edit by bumping to a new, unapproved revision.

    `revise` is a distinct operation, not a normal lifecycle transition — it
    deliberately does NOT call `validate_package`, because validate would
    hard-error on hash drift, which is exactly the drift revise exists to
    resolve. Legal only from `lifecycle.REVISE_LEGAL_FROM`; from an execution
    state the package has materially changed after execution began, so the
    correct operation is `supersede`, not `revise`.

    Revising from `approved` leaves the old approval in `lineage["approvals"]`
    bound to its old revision — it is never deleted; the new revision is
    simply unapproved until a fresh `do_approve` call.
    """
    pkg_dir = Path(pkg_dir)
    lin = lineage.read(pkg_dir)
    current = lin["current_state"]

    if current not in lifecycle.REVISE_LEGAL_FROM:
        raise OperationError(
            f"cannot revise from {current!r}: the package has materially "
            "changed after execution began — use `supersede`, not `revise`"
        )

    package = load_package(pkg_dir)
    new_revision = package["revision"] + 1
    set_revision_in_file(pkg_dir, new_revision)

    reloaded = load_package(pkg_dir)
    new_hash = canonical.package_hash(reloaded)

    lineage.snapshot_revision(lin, new_revision, new_hash, now, actor)

    try:
        event_id = emitter.emit(
            "package.revised",
            package["package_id"],
            {"from": current, "revision": new_revision},
        )
    except EmitError:
        event_id = None

    lineage.append_transition(lin, "revision", current, "draft", now, actor, event_id)
    lin["current_state"] = "draft"
    lineage.write(pkg_dir, lin)
    set_status_in_file(pkg_dir, "draft")


def do_supersede(
    pkg_dir: str | Path,
    new_package_id: str,
    *,
    emitter: Emitter,
    actor: str = "claude-code-interactive",
    now: str,
) -> None:
    """Mark the package at `pkg_dir` superseded by `new_package_id`.

    Legal only per `lifecycle.is_legal_transition(current, "superseded")`.
    The emit is best-effort, like `transition`/`revise` (approval is the only
    operation where a failed emit is fatal).
    """
    pkg_dir = Path(pkg_dir)
    lin = lineage.read(pkg_dir)
    current = lin["current_state"]

    if not lifecycle.is_legal_transition(current, "superseded"):
        raise OperationError(f"illegal transition: {current!r} -> 'superseded'")

    package = load_package(pkg_dir)

    try:
        event_id = emitter.emit(
            "package.superseded",
            package["package_id"],
            {"from": current, "superseded_by": new_package_id},
        )
    except EmitError:
        event_id = None

    lineage.append_transition(lin, "supersession", current, "superseded", now, actor, event_id)
    lin["transitions"][-1]["superseded_by"] = new_package_id
    lin["current_state"] = "superseded"
    lineage.write(pkg_dir, lin)
    set_status_in_file(pkg_dir, "superseded")


def _factory_events_file() -> Path:
    """Locate the tamper-evident factory-events JSONL store.

    `FACTORY_EVENTS_FILE` overrides for tests/alternate deployments; otherwise
    the real per-machine store at `~/.factory/events.jsonl`.
    """
    env_file = os.environ.get("FACTORY_EVENTS_FILE")
    return Path(env_file) if env_file else Path.home() / ".factory" / "events.jsonl"


def _verify_chain_integrity(sec_std_dir: Path) -> None:
    """Run `factory_events verify`; raise `ChainUnavailable` unless it
    reports the chain intact (exit 0)."""
    python = _events_python(sec_std_dir)
    env = dict(os.environ)
    src_dir = str(sec_std_dir / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{src_dir}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else src_dir
    )

    try:
        result = subprocess.run(
            [python, "-m", "factory_events", "verify"],
            capture_output=True,
            text=True,
            env=env,
            timeout=_CHAIN_VERIFY_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ChainUnavailable(f"factory_events verify failed to run: {exc}") from exc

    if result.returncode != 0:
        raise ChainUnavailable(
            f"factory_events verify: chain integrity check failed: {result.stderr}"
        )


def _events_file_has_matching_approval(approved_hash: str, revision: int) -> bool:
    """Scan the factory-events JSONL store for a `package.approved` event
    carrying this exact `approved_hash` + `revision`."""
    events_file = _factory_events_file()
    if not events_file.is_file():
        raise ChainUnavailable(f"factory events file not found: {events_file}")

    try:
        text = events_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ChainUnavailable(f"could not read factory events file: {exc}") from exc

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("action") != "package.approved":
            continue
        evidence = event.get("evidence") or {}
        if evidence.get("approved_hash") == approved_hash and evidence.get("revision") == revision:
            return True

    return False


def default_chain_checker(approved_hash: str, revision: int) -> bool:
    """Default `chain_checker` for `verify_approval` (spec §4.4).

    True iff the tamper-evident factory-events chain verifies AND contains a
    `package.approved` event whose evidence carries this exact
    `approved_hash` + `revision`. Raises `ChainUnavailable` — never returns
    False silently — for anything that stops the chain from being consulted
    at all: security-standards/registry missing, the `factory_events verify`
    subprocess failing to run or reporting a broken chain (nonzero exit), or
    the events file being missing/unreadable. A verified chain that simply
    has no matching event is a genuine "not approved" answer, so that (and
    only that) path returns False rather than raising.
    """
    try:
        sec_std_dir = _security_standards_dir()
    except EmitError as exc:
        raise ChainUnavailable(f"cannot locate security-standards: {exc}") from exc

    _verify_chain_integrity(sec_std_dir)
    return _events_file_has_matching_approval(approved_hash, revision)


def verify_approval(
    pkg_dir: str | Path,
    *,
    chain_checker: Callable[[str, int], bool] | None = None,
    ledger_only: bool = False,
) -> bool:
    """Verify that the CURRENT revision of the package at `pkg_dir` was
    approved (spec §4.4) — the Phase-3 orchestrator's mechanical gate.

    Only the current revision is checked; historical revisions aren't on
    disk. This is the security-critical read path: it must **fail closed**,
    returning False whenever a required check does not affirmatively pass.

      1. Recompute `h`, the hash of the package as it stands right now.
      2. Ledger check (always required): `lineage["approvals"]` must contain
         an entry whose `approved_hash == h`, approved by an identity
         `registry.is_human_operator` confirms is human. This alone catches
         both "never approved" and "approved, then the intent drifted"
         (revise bumps the revision but the old approval stays bound to the
         old hash).
      3. Chain check (required unless `ledger_only`): `chain_checker(h,
         revision)` must independently confirm, via the tamper-evident
         factory-events chain, that a `package.approved` event for this exact
         hash+revision exists and the chain verifies. A forged/edited ledger
         entry cannot pass this — it isn't in the chain. If `chain_checker`
         returns False, or raises (chain unavailable for any reason), the
         result is False; a raise never bubbles out of this function.
      4. `ledger_only=True` skips the chain check entirely (the escape hatch
         for tests/environments where the chain can't be reached) — the CLI
         is responsible for printing the loud "UNVERIFIED CHAIN" warning that
         makes this an explicit, visible choice rather than a silent gap.
    """
    pkg_dir = Path(pkg_dir)
    package = load_package(pkg_dir)
    h = canonical.package_hash(package)

    lin = lineage.read(pkg_dir)
    ledger_ok = any(
        a["approved_hash"] == h and registry.is_human_operator(a["approver"])
        for a in lin.get("approvals", [])
    )
    if not ledger_ok:
        return False

    if ledger_only:
        return True

    checker = chain_checker if chain_checker is not None else default_chain_checker
    try:
        chain_ok = checker(h, package["revision"])
    except Exception:  # noqa: BLE001 - any failure to consult the chain fails closed
        return False

    return bool(chain_ok)
