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

from intent_packages import canonical, lifecycle, lineage
from intent_packages.emitter import EmitError, Emitter
from intent_packages.loader import load_package
from intent_packages.validate import validate_package

_STATUS_LINE_RE = re.compile(r"^status:.*$", re.MULTILINE)


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
