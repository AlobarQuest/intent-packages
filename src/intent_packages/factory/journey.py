"""The flow verbs: submit, status, evidence, ready, dispatch.

Every human gate here is a stop, not a step. `submit` prepares the intake
payload, copies it, prints the /review link and exits -- it can never complete
an intake, because the route requires a HUMAN actor and no HUMAN credential
exists or ever will (ADR-0006).
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from intent_packages.factory import links
from intent_packages.factory.api import base_url_from_env
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
