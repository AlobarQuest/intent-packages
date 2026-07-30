"""The read/report verbs: submit, status, evidence.

Every human gate here is a stop, not a step. `submit` prepares the intake
payload, copies it, prints the /review link and exits -- it can never complete
an intake, because the route requires a HUMAN actor and no HUMAN credential
exists or ever will (ADR-0006).

The derived reads these verbs run on (`resolve_revision`, `units_for`,
`resolve_unit_id`, the read Protocol) live in `reads.py`, which `execution.py`
and `verify.py` import too. Nothing imports this module.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from intent_packages.factory import links, reads
from intent_packages.factory.api import ApiError, OrchestratorApi, base_url_from_env
from intent_packages.factory.orchestrator_cli import OrchestratorClient, OrchestratorCliError
from intent_packages.factory.reads import RevisionApi, RevisionRequired, resolve_revision
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


_DECIDED_PROPOSAL_STATES = frozenset({"approved", "rejected", "superseded"})

# Every `WorkUnitState` except `draft`, whose next action depends on whether an
# authority approval is recorded and so is computed rather than looked up.
#
# CROSS-BOUNDARY VOCABULARY. The source of truth is
# `orchestrator/kernel/states.py::WorkUnitState` (13 members); this table must
# name all 13. Read from the orchestrator's own tree, not inferred: draft, ready,
# claimed, executing, blocked, awaiting_approval, submitted, verifying,
# awaiting_review, revision_required, completed, failed, cancelled.
# `test_journey.py::test_every_work_unit_state_has_a_next_action` pins the set.
# Templates are formatted with `rev`, `key` and `link`.
_STATE_NEXT_ACTIONS: dict[str, str] = {
    "ready": "ready to dispatch: factory dispatch --revision {rev} --unit-key {key}",
    "claimed": (
        "a worker holds the claim -- nothing to do here; wait for it to submit, or for the "
        "lease to expire and the unit to be reclaimed"
    ),
    "executing": (
        "the runner is executing -- nothing to do here; wait for the Actions run to conclude "
        "and the unit to reach SUBMITTED"
    ),
    "blocked": "blocked -- a human has to inspect why before it can move: {link}",
    "awaiting_approval": (
        "needs a HUMAN approval before it can become READY -- this is a browser-only gate "
        "(ADR-0006), no factory verb can cross it: {link}"
    ),
    "submitted": (
        "ready to verify: factory verify --revision {rev} --unit-key {key} --ac AC-00N "
        "--check-name <name> --conclusion success --run-id <id> --run-url <url> "
        "--assert <name>=<expected>:<observed>  (check name, run id and run url come from the "
        "Actions run; --ac must name an automated_check criterion)"
    ),
    "verifying": "verification is in progress -- nothing to do here; re-run status",
    "awaiting_review": (
        "verification returned judgment_required for at least one criterion -- a HUMAN must "
        "adjudicate it in the browser (ADR-0006): {link}"
    ),
    "revision_required": (
        "verification found a failure -- the unit needs another attempt: requeue or let the "
        "claim expire, then factory dispatch --revision {rev} --unit-key {key}: {link}"
    ),
    "completed": (
        "nothing to do -- this unit is complete; read its record with "
        "factory evidence --revision {rev} --unit-key {key}"
    ),
    "failed": "terminally failed -- nothing to do here; read the record: {link}",
    "cancelled": "cancelled -- nothing to do here; read the record: {link}",
}


def _draft_next_action(base_url: str, revision_id: str, unit: dict) -> str:
    """The two DRAFT cases, which are the two failure modes that historically
    cost the most time.

    An authority approval does NOT move lifecycle state, so an approved unit
    sits in DRAFT until the SYSTEM `commands/ready` edge is driven. And the
    generic `/review` approve button records `subject_type="action"`, which
    satisfies the `AWAITING_APPROVAL -> READY` guard but NOT readiness --
    readiness wants `subject_type="authority"` bound to this exact fingerprint.
    """
    if unit.get("authority_decision") == "approved":
        return (
            "authority approved but the unit is still DRAFT -- authority approval does not move "
            f"state. Run: factory ready --revision {revision_id} --unit-key {unit['unit_key']}"
        )
    return (
        "needs a HUMAN authority approval bound to fingerprint "
        f"{unit['authority_fingerprint']}. Use the 'Approve this authority envelope' form "
        "(NOT the generic approve button, which records subject_type=action and does not "
        f"satisfy readiness): {links.unit(base_url, unit['id'])}"
    )


def _next_action(base_url: str, revision_id: str, unit: dict) -> str:
    """One actionable line per unit state -- a real command where one exists, an
    honest "nothing to do here" where none does.

    A dispatch table rather than a branch chain: enumerating all 13
    `WorkUnitState` members as `if`s would blow the C901 ceiling, and a table
    can be asserted complete by a test.
    """
    state = unit["state"]
    if state == "draft":
        return _draft_next_action(base_url, revision_id, unit)
    template = _STATE_NEXT_ACTIONS.get(state)
    if template is None:
        return (
            f"state {state!r} is not a known WorkUnitState -- this client's table is behind the "
            f"orchestrator: {links.unit(base_url, unit['id'])}"
        )
    return template.format(
        rev=revision_id, key=unit["unit_key"], link=links.unit(base_url, unit["id"])
    )


def _print_intake(intake: dict) -> None:
    """`PackageIntakeResponse` carries NO lifecycle `state` field.

    This line used to print `intake.get("state")` and therefore printed `None`
    on every production run -- the flagship screen's first line, wrong from the
    first commit, because the fixture it was written against invented the field.
    The real response (confirmed against the live openapi.json) carries
    `status_at_intake` (the package's own `status` at the moment of intake) and
    `intake_source`, plus the package identity. There is nothing else to show as
    a "state": an intake is a registration, not a state machine -- the states
    that matter belong to the proposals and units printed below.
    """
    print(
        f"intake {intake.get('id')}: package {intake.get('package_id')!r} "
        f"revision {intake.get('revision')} from {intake.get('source_repository')!r}"
    )
    print(
        f"  status_at_intake={intake.get('status_at_intake')!r} "
        f"intake_source={intake.get('intake_source')!r} profile={intake.get('profile')!r}"
    )


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


def _print_units(base_url: str, revision_id: str, api: RevisionApi, units: list[dict]) -> None:
    """One block per unit: authority-approval provenance, the next action, and
    the latest dispatch ordinal.

    The ordinal is spec §3's promised field and replaces a bare
    `history: N event(s) recorded` -- one `history` round trip per unit either
    way, but now the read is used for the number that decides the next dispatch.
    A REUSED ordinal makes `dispatch` a silent no-op, so knowing the latest
    consumed one before dispatching is the point of reading history at all.
    """
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
        print(f"    next: {_next_action(base_url, revision_id, unit)}")
        latest_ordinal, record_ids = reads.scan_dispatch_events(api, unit["id"])
        if latest_ordinal:
            print(
                f"    dispatch: latest ordinal {latest_ordinal} "
                f"({len(record_ids)} record(s)); the next one offered will be "
                f"{latest_ordinal + 1} or higher"
            )
        else:
            print("    dispatch: never dispatched")


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
        if _unit_states(reads.units_for(api, revision_id)) != initial:
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
        units = reads.units_for(api, revision_id)
        _print_intake(intake)
        _print_proposals(base_url, proposals)
        _print_units(base_url, revision_id, api, units)
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
            # `reads.resolve_unit_id`, not a local copy: this block used to
            # reimplement it (and a byte-identical `_unit_id_for_key`) down to a
            # near-identical refusal string, in the same repo where the function
            # had been made public specifically to be shared.
            unit_id = reads.resolve_unit_id(api, revision_id, unit_key, verb="evidence")
            if unit_id is None:
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
