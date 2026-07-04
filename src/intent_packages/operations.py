"""State-changing package operations (spec section 5/9): `transition` today,
`approve`/`revise`/`supersede` in later tasks.

Each operation loads the package, re-validates it (refusing to act on an
invalid package), enacts the change against both `package.yaml` and
`lineage.yaml`, and best-effort emits a factory event — a failed emit never
blocks the operation, it just records `event_id: null`.
"""
from __future__ import annotations

import re
from pathlib import Path

from intent_packages import canonical, lifecycle, lineage, registry
from intent_packages.emitter import EmitError, Emitter
from intent_packages.loader import load_package
from intent_packages.validate import validate_package

_STATUS_LINE_RE = re.compile(r"^status:.*$", re.MULTILINE)
_REVISION_LINE_RE = re.compile(r"^revision:.*$", re.MULTILINE)


class OperationError(Exception):
    """Raised when an operation is refused: invalid package or illegal transition."""


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
