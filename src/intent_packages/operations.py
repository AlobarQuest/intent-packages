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
from intent_packages.approval_policy import (
    ApprovalPolicyError,
    is_policy_approver,
    load_policy,
)
from intent_packages.emitter import EmitError, Emitter, _events_python, _security_standards_dir
from intent_packages.loader import load_package
from intent_packages.validate import validate_package

_STATUS_LINE_RE = re.compile(r"^(status:)[^#\n]*(?P<comment>\s+#.*)?$", re.MULTILINE)
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


def _is_recognised_approver(approver: object) -> bool:
    """A human operator, or a policy (ADR-0028). Nothing else may stand in a ledger.

    THE POLICY ARM IS NOT A WEAKER LEDGER CHECK, and the distinction is the whole safety
    of adding it. A forged ledger entry naming `policy:...@v1` still fails
    :func:`verify_approval`, because the chain check demands a `package.approved` event
    for that exact hash and revision -- and the only thing that emits one is
    :func:`do_approve`, which refuses a policy approval the artifact objects to. What
    this arm changes is which approvals are RECOGNISED, never how they are proven.
    """
    return isinstance(approver, str) and (
        registry.is_human_operator(approver) or is_policy_approver(approver)
    )


def _has_matching_approval(approvals: object, approved_hash: str) -> bool:
    if not isinstance(approvals, list):
        return False
    return any(
        isinstance(approval, dict)
        and approval.get("approved_hash") == approved_hash
        and _is_recognised_approver(approval.get("approver"))
        for approval in approvals
    )


def _approval_entries(lineage_data: dict) -> list:
    approvals = lineage_data.get("approvals", [])
    if not isinstance(approvals, list):
        raise OperationError("lineage.yaml: approvals must be a list")
    return approvals


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
    new_text, count = _STATUS_LINE_RE.subn(
        lambda match: f"status: {new_status}{match.group('comment') or ''}",
        text,
        count=1,
    )
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
        raise OperationError("package.yaml: could not find a top-level `revision:` line to update")
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
    Also refuses `completed -> closed` when `follow_up.required` is true
    (spec §5.3) — such a package must route through `follow_up_due` first;
    `follow_up.required: false` still allows `completed -> closed` directly.
    On `ready_for_review`, re-snapshots the current revision's hash first, to
    capture any draft edits made since the last snapshot. The factory-event
    emit is best-effort: a raised `EmitError` is swallowed and recorded as a
    `null` `event_id` rather than blocking the transition.
    """
    pkg_dir = Path(pkg_dir)

    errors = validate_package(pkg_dir)
    if errors:
        raise OperationError("refusing to transition an invalid package:\n" + "\n".join(errors))

    package = load_package(pkg_dir)
    lin = lineage.read(pkg_dir)
    current = lin["current_state"]

    if not lifecycle.is_legal_transition(current, to_state):
        raise OperationError(f"illegal transition: {current!r} -> {to_state!r}")

    if current == "completed" and to_state == "closed" and package["follow_up"]["required"]:
        raise OperationError(
            "follow_up.required is true — route via follow_up_due, not directly to closed"
        )

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


def _authorize_approver(package: dict, approver: str) -> None:
    """Refuse an approver who is neither a human operator nor the policy for this package.

    ADR-0028 relaxes the per-revision human act for one narrow, pre-decided shape of work
    and does so as a POLICY rather than as a removal -- so raising the bar again is an
    edit to `approval-policy.toml` rather than a rebuild. Three properties matter here:

    * the human arm is untouched, and is tried first;
    * a policy approver must be EXACTLY the string this document grants for this
      package's profile, so a caller cannot name a version the artifact is not at, nor
      borrow another profile's grant;
    * an artifact that will not load raises rather than yielding no objections, because a
      caller reading an empty objection list as consent would turn a broken document into
      a standing approval for everything.
    """
    if registry.is_human_operator(approver):
        return
    if not is_policy_approver(approver):
        raise OperationError(
            f"approval is a human act unless a policy grants it; {approver!r} is neither "
            "a human-operator identity nor a policy approver"
        )
    try:
        policy = load_policy()
    except ApprovalPolicyError as exc:
        raise OperationError(f"the approval policy could not be read: {exc}") from exc
    profile = package.get("profile")
    expected = policy.approver_for(profile) if isinstance(profile, str) else None
    if approver != expected:
        raise OperationError(
            f"{approver!r} is not the approver this policy grants for profile "
            f"{profile!r} at version {policy.version}"
        )
    refusals = policy.refusals_for(package)
    if refusals:
        raise OperationError("the approval policy refuses this revision: " + ", ".join(refusals))


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
      4. `approver` must resolve to a human-operator registry identity, or
         to the policy this package's profile is granted by ADR-0028's
         `approval-policy.toml` — in which case the artifact must also raise
         no objection to the revision. Approval is a human act unless a
         standing, versioned policy says otherwise for this exact shape.
      5. Compute the package hash.
      6. Idempotency (MVP, lineage-based): if `lineage["approvals"]` already
         has an entry for this exact hash by a recognised approver, this
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
        raise OperationError("refusing to approve an invalid package:\n" + "\n".join(errors))

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

    _authorize_approver(package, approver)

    h = canonical.package_hash(package)

    approvals = _approval_entries(lin)
    already_approved = _has_matching_approval(approvals, h)
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
    replacement_dir = pkg_dir.parent / new_package_id
    try:
        replacement = load_package(replacement_dir)
    except Exception as exc:
        raise OperationError(
            f"superseding package {new_package_id!r} could not be loaded: {exc}"
        ) from exc
    if replacement.get("package_id") != new_package_id:
        raise OperationError("superseding package id does not match its directory")
    if replacement.get("supersedes") != package.get("package_id"):
        raise OperationError(
            f"superseding package {new_package_id!r} must declare "
            f"supersedes: {package.get('package_id')!r}"
        )

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

    Must resolve to the SAME path the `factory_events` store itself uses
    (`factory_events.store.events_path()`: `$FACTORY_EVENTS_HOME/events.jsonl`,
    defaulting to `~/.factory/events.jsonl`) — otherwise `_verify_chain_integrity`
    (which shells `factory_events verify`, honoring `FACTORY_EVENTS_HOME`) and
    this JSONL scan could read two different files (split-brain). There is no
    separate override env var here; `FACTORY_EVENTS_HOME` is the only knob,
    exactly as the store defines it.
    """
    home = Path(os.environ.get("FACTORY_EVENTS_HOME", str(Path.home() / ".factory")))
    return home / "events.jsonl"


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


def _evidence_matches(evidence: object, approved_hash: str, revision: int) -> bool:
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


def _events_file_has_matching_approval(approved_hash: str, revision: int) -> bool:
    """Scan the factory-events JSONL store for a `package.approved` event
    carrying this exact `approved_hash` + `revision`.

    Each line is a factory-event record with the real fields nested under a
    top-level `"event"` key (defensively, an unwrapped line is also tolerated),
    and `evidence` is a LIST of records — the approval fields can live in any
    item, so every item is scanned rather than assuming `evidence[0]`.
    """
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
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev = obj.get("event", obj)
        if ev.get("action") != "package.approved":
            continue
        if _evidence_matches(ev.get("evidence"), approved_hash, revision):
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
         an entry whose `approved_hash == h`, approved by a recognised
         approver — an identity `registry.is_human_operator` confirms is
         human, or a `policy:<profile>@v<version>` string (ADR-0028). The
         policy arm does not weaken step 3, which is what actually proves an
         approval happened: only `do_approve` emits the event it looks for,
         and it refuses a policy approval the artifact objects to. This alone
         catches
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
    approvals = lin.get("approvals", [])
    if not isinstance(approvals, list):
        return False
    ledger_ok = _has_matching_approval(approvals, h)
    if not ledger_ok:
        return False

    if ledger_only:
        return True

    checker = chain_checker if chain_checker is not None else default_chain_checker
    try:
        chain_ok = checker(h, package["revision"])
    except Exception:
        # fail closed: any chain-check failure (incl. ChainUnavailable) => not verified
        return False

    return bool(chain_ok)
