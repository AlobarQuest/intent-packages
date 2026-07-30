"""The flow verbs: submit, status, evidence, ready, dispatch.

Every human gate here is a stop, not a step. `submit` prepares the intake
payload, copies it, prints the /review link and exits -- it can never complete
an intake, because the route requires a HUMAN actor and no HUMAN credential
exists or ever will (ADR-0006).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from intent_packages.factory import links
from intent_packages.factory.api import ApiError, OrchestratorApi, base_url_from_env
from intent_packages.factory.orchestrator_cli import OrchestratorClient, OrchestratorCliError
from intent_packages.loader import LoadError, load_lineage, load_package

Clipboard = Callable[[str], None]


class IntakeClient(Protocol):
    """The one `OrchestratorClient` method `submit` needs.

    A structural protocol (not the concrete class) so a test double only has
    to implement `emit_intake_payload` -- it does not need to *be* an
    `OrchestratorClient`. Parameters are positional-only (`/`) so a double
    naming its first argument differently (e.g. `path`) still satisfies this
    protocol -- pyright otherwise treats a differing keyword name as a
    genuine incompatibility.
    """

    def emit_intake_payload(
        self, package_path: str, source_repository: str, idempotency_key: str, /
    ) -> dict: ...


class RevisionApi(Protocol):
    """The read surface `status`/`evidence`/`units_for` need.

    A structural protocol, same reasoning as `IntakeClient`: a test double
    only has to implement these seven methods, not *be* an `OrchestratorApi`.
    The concrete `OrchestratorApi` satisfies this structurally, so production
    callers pass it unchanged. `readiness` is deliberately absent: nothing
    here calls it (fix round 1/5, task 7) -- `_next_action` derives the next
    step entirely from `unit["state"]`, so fetching readiness per unit was an
    HTTP round trip for a value nothing ever read.
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


def _default_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True, check=True)


def _resolve_package_dir(package_path: str) -> Path:
    """Accept a package directory or its package.yaml file."""
    path = Path(package_path)
    return path.parent if path.is_file() else path


def _print_refusal(pkg_dir: Path, status: object, current_state: object) -> None:
    print(
        f"submit: {pkg_dir} is not approved (package.yaml status={status!r}, "
        f"lineage.yaml current_state={current_state!r}) -- intake requires both to read "
        "'approved'. Run:",
        file=sys.stderr,
    )
    print(f"  intent_packages transition {pkg_dir} --to ready_for_review", file=sys.stderr)
    print(f"  intent_packages approve {pkg_dir} --approver devon", file=sys.stderr)


def _copy_to_clipboard(text: str, clipboard: Clipboard) -> bool:
    """Return whether the payload actually made it to the clipboard.

    A clipboard failure is a warning, never fatal -- but the caller must not
    then claim success: a `pbcopy` that exists but exits nonzero (headless or
    remote session) must be caught (hence `check=True` in the default), and
    when it fails the payload must still be visible in the output.
    """
    try:
        clipboard(text)
    except Exception as error:
        print(
            f"warning: could not copy the intake payload to the clipboard ({error}); "
            f"here it is instead:\n{text}",
            file=sys.stderr,
        )
        return False
    return True


def submit(
    package_path: str,
    source_repository: str,
    *,
    open_browser: bool = False,
    client: IntakeClient | None = None,
    clipboard: Clipboard | None = None,
) -> int:
    """Stage an intake payload and hand off to `/review/intakes/new`, then stop.

    This is a human gate (ADR-0006): package intake requires a HUMAN actor and
    no HUMAN credential exists or ever will, so `submit` never calls the API --
    it has no `api` parameter at all, and never imports `OrchestratorApi`.
    Tasks 7-9 add their own `api` parameters to the sibling verbs in this
    module; that is not a reason to carry an unused one here.
    """
    client = client or OrchestratorClient()

    pkg_dir = _resolve_package_dir(package_path)
    try:
        package = load_package(pkg_dir)
        lineage = load_lineage(pkg_dir)
    except LoadError as error:
        print(f"submit: {error}", file=sys.stderr)
        return 1

    status = package.get("status")
    current_state = lineage.get("current_state")
    if status != "approved" or current_state != "approved":
        _print_refusal(pkg_dir, status, current_state)
        return 1

    idempotency_key = f"factory-submit-{uuid.uuid4()}"
    try:
        payload = client.emit_intake_payload(str(pkg_dir), source_repository, idempotency_key)
    except OrchestratorCliError as error:
        # Covers both the `orchestrator` binary being unreachable and the
        # local emit-intake-payload subprocess itself refusing the package
        # (e.g. no lineage approval matching the canonical hash, no git HEAD)
        # -- that check lives one layer down in `orchestrator`'s own
        # emit-intake-payload command, not duplicated here.
        print(f"submit failed: {error}", file=sys.stderr)
        return 1

    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    copied = _copy_to_clipboard(text, clipboard or _default_clipboard)

    link = links.intake_new(base_url_from_env())
    if open_browser:
        webbrowser.open(link)

    if copied:
        print(f"Intake payload staged and copied to your clipboard: {link}")
    else:
        print(f"Intake payload staged (see the clipboard warning above): {link}")
    print(
        "This is a human gate (ADR-0006) -- factory submit stops here, waiting on your "
        "approval in the browser; it never posts the intake itself."
    )
    print(
        "Note: the form takes its idempotency key from the FORM FIELD, not the pasted "
        "payload -- re-submitting a rendered page replays this same intake, not a new one; "
        "reload the page first if you need a genuinely new registration."
    )
    print("Once the form redirects, resume with: factory status --revision <id from the URL>")
    return 0


class RevisionRequired(Exception):
    """Raised when neither `--revision` nor `$FACTORY_REVISION` is set.

    Public (no leading underscore): `execution.py`'s `ready`/`dispatch` catch
    this across the module boundary, same reasoning as `resolve_revision`
    below -- a cross-module helper's raised exception type has to be part of
    the public surface, or callers outside this module have nothing precise
    to catch.
    """


def resolve_revision(revision_id: str) -> str:
    """Fall back to `$FACTORY_REVISION`; raise when neither is set.

    Shared by every verb that operates on a revision -- `status` and
    `evidence` here, `ready`/`dispatch` in `execution.py`, `verify` later --
    so the exit-2 behaviour for a missing revision lives in exactly one
    place. Public (no leading underscore): it is a cross-module helper now,
    not a private one.
    """
    if revision_id:
        return revision_id
    from_env = os.environ.get("FACTORY_REVISION", "")
    if from_env:
        return from_env
    raise RevisionRequired("no revision id: pass --revision or set $FACTORY_REVISION")


_DECIDED_PROPOSAL_STATES = frozenset({"approved", "rejected", "superseded"})


def units_for(api: RevisionApi, revision_id: str) -> list[dict]:
    """Derive the per-unit view of a revision from `traceability`.

    This is the single derivation point -- tasks 8 and 9 (`ready`,
    `dispatch`/`verify`) must call this rather than re-deriving from
    `traceability` themselves. Each returned dict is the chain's `unit` hop
    (`id`, `unit_key`, `state`, `authority_fingerprint`, `authority_approved_by`,
    `authority_decision`) with a `pr` key added when the chain carries one.
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


def _next_action(base_url: str, unit: dict) -> str:
    if unit["state"] == "draft" and unit.get("authority_decision") == "approved":
        return (
            f"authority approved but the unit is still DRAFT -- authority approval does not move "
            f"state. Run: factory ready --revision <rev> --unit-key {unit['unit_key']}"
        )
    if unit["state"] == "draft":
        return (
            f"needs a HUMAN authority approval bound to fingerprint "
            f"{unit['authority_fingerprint']}. Use the 'Approve this authority envelope' form "
            f"(NOT the generic approve button, which records subject_type=action and does not "
            f"satisfy readiness): {links.unit(base_url, unit['id'])}"
        )
    if unit["state"] == "ready":
        return f"ready to dispatch: factory dispatch --revision <rev> --unit-key {unit['unit_key']}"
    return f"state {unit['state']}: {links.unit(base_url, unit['id'])}"


def _print_intake(intake: dict) -> None:
    print(f"intake {intake.get('id')}: {intake.get('state')}")


def _print_proposals(base_url: str, proposals: list[dict]) -> None:
    """`proposals` IS the list -- the route's body is a bare JSON array, not
    `{"items": [...]}`; there is no `items` key to unwrap."""
    if not proposals:
        print("proposals: none yet")
        return
    print("proposals:")
    for item in proposals:
        line = f"  {item.get('id')}: {item.get('state')}"
        if item.get("state") not in _DECIDED_PROPOSAL_STATES:
            line += f" -- {links.decomposition_proposal(base_url, item['id'])}"
        print(line)


def _print_units(base_url: str, api: RevisionApi, units: list[dict]) -> None:
    if not units:
        print("units: none yet")
        return
    print("units:")
    for unit in units:
        approved = unit.get("authority_decision") == "approved"
        approval = (
            f"authority approved by {unit.get('authority_approved_by')} "
            f"({unit.get('authority_fingerprint')})"
            if approved
            else "no authority approval recorded"
        )
        print(f"  {unit['unit_key']} [{unit['state']}] -- {approval}")
        print(f"    next: {_next_action(base_url, unit)}")
        events = api.history(unit["id"]) or []
        if events:
            print(f"    history: {len(events)} event(s) recorded")


def _unit_states(units: list[dict]) -> dict[str, str]:
    return {unit["id"]: unit["state"] for unit in units}


def _wait_for_change(
    api: RevisionApi,
    revision_id: str,
    initial: dict[str, str],
    poll_seconds: float,
    timeout_seconds: float,
) -> bool:
    """Poll `traceability` (only) until a unit's state changes or the timeout elapses."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_seconds)
        if _unit_states(units_for(api, revision_id)) != initial:
            return True
    return False


def status(
    revision_id: str,
    *,
    wait: bool = False,
    poll_seconds: float = 15,
    timeout_seconds: float = 1800,
    api: RevisionApi | None = None,
    verbose: bool = False,
) -> int:
    """Print one screen for a revision: intake, proposals, units, next action.

    The next-action line is what makes this a front door: it distinguishes an
    authority approval recorded on a still-DRAFT unit (needs `factory ready` --
    authority approval alone never moves lifecycle state) from a unit approved
    with the generic `/review` button (`subject_type=action`, which does not
    satisfy readiness at all).
    """
    api = api or OrchestratorApi(verbose=verbose)
    try:
        revision_id = resolve_revision(revision_id)
    except RevisionRequired as error:
        print(f"status failed: {error}", file=sys.stderr)
        return 2

    base_url = base_url_from_env()
    try:
        intake = api.get_intake(revision_id)
        proposals = api.list_proposals(revision_id)
        units = units_for(api, revision_id)
        _print_intake(intake)
        _print_proposals(base_url, proposals)
        _print_units(base_url, api, units)
        if wait:
            try:
                changed = _wait_for_change(
                    api, revision_id, _unit_states(units), poll_seconds, timeout_seconds
                )
            except KeyboardInterrupt:
                print("status --wait interrupted", file=sys.stderr)
                return 130
            if changed:
                print()
                print("-- a unit's state changed --")
                return status(revision_id, api=api)
            print(f"status --wait: no state change after {timeout_seconds}s")
    except (ApiError, OrchestratorCliError) as error:
        print(f"status failed: {error}", file=sys.stderr)
        return 1
    return 0


def _unit_id_for_key(units: list[dict], unit_key: str) -> str | None:
    for unit in units:
        if unit["unit_key"] == unit_key:
            return unit["id"]
    return None


def evidence(
    revision_id: str,
    *,
    unit_key: str | None = None,
    markdown: bool = False,
    api: RevisionApi | None = None,
    verbose: bool = False,
) -> int:
    """Fetch and print the evidence pack for a revision, or one of its units.

    Without `--unit-key`, fetches the revision-level pack; with one, the unit
    pack. `--markdown` selects the redacted, PR-comment-safe route and needs
    `--unit-key` -- there is no revision-level markdown route to fall back to.
    Both forms print exactly what the API returned: the JSON stays
    full-fidelity (auth-gated); redaction, when it happens, is the renderer's
    decision, never this CLI's.
    """
    api = api or OrchestratorApi(verbose=verbose)
    try:
        revision_id = resolve_revision(revision_id)
    except RevisionRequired as error:
        print(f"evidence failed: {error}", file=sys.stderr)
        return 2

    if markdown and not unit_key:
        print(
            "evidence failed: --markdown requires --unit-key (no revision-level markdown route)",
            file=sys.stderr,
        )
        return 1

    try:
        if unit_key:
            units = units_for(api, revision_id)
            unit_id = _unit_id_for_key(units, unit_key)
            if unit_id is None:
                keys = ", ".join(sorted(u["unit_key"] for u in units)) or "(none)"
                print(
                    f"evidence failed: unknown --unit-key {unit_key!r}; known keys: {keys}",
                    file=sys.stderr,
                )
                return 1
            if markdown:
                print(api.evidence_pack_markdown(unit_id))
            else:
                print(json.dumps(api.evidence_pack(unit_id), indent=2, sort_keys=True))
        else:
            print(json.dumps(api.revision_evidence_pack(revision_id), indent=2, sort_keys=True))
    except (ApiError, OrchestratorCliError) as error:
        print(f"evidence failed: {error}", file=sys.stderr)
        return 1
    return 0
