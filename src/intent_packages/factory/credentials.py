"""M2M bearer resolution for the `factory` front door.

Two roles, two credentials: SYSTEM drives reads, decomposition submit, `ready`
and dispatch; VERIFIER drives named-check evidence and verifier evaluation.
`orchestrator-drift-reporter` is deliberately absent -- its registry profile is
observe-and-propose and `agent_id` attribution is permanent.

Env first so CI and tests never touch BWS; `bws secret get` second so a human
session needs no wrapper script. A token returned from here is held in a local
and passed straight to the HTTP client: it is never logged, never placed in an
exception message, and never written to disk.
"""

from __future__ import annotations

import enum
import os
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
MANIFEST = Path(__file__).resolve().parents[3] / ".bws-secrets.toml"
BWS_TIMEOUT_SECONDS = 30


class CredentialError(Exception):
    """Raised when neither the environment nor BWS can supply a bearer token."""


class Role(enum.StrEnum):
    SYSTEM = "orchestrator-system"
    VERIFIER = "orchestrator-verifier"

    @property
    def env_var(self) -> str:
        return f"ORCHESTRATOR_{self.name}_TOKEN"


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=BWS_TIMEOUT_SECONDS)


def secret_uuid(role: Role) -> str:
    """Look up `role`'s BWS UUID from the `[[secret]]` array in MANIFEST.

    Selects by the manifest's `role` field, never by `name` -- BWS secret
    names are mutable labels, so a by-name lookup would silently break on a
    rename (secret-handling standard rule 3).
    """
    try:
        manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    except OSError as error:
        raise CredentialError(f"cannot read {MANIFEST}") from error
    for entry in manifest.get("secret", []):
        if entry.get("role") == role.value:
            uuid = entry.get("uuid")
            if isinstance(uuid, str) and uuid:
                return uuid
    raise CredentialError(f"{MANIFEST} has no [[secret]] entry with role = {role.value!r}")


def resolve_token(role: Role, *, runner: Runner | None = None) -> str:
    """Return the bearer for `role`, from the environment or BWS. Never logged."""
    from_env = os.environ.get(role.env_var, "")
    if from_env:
        return from_env
    return fetch_bws_secret(
        secret_uuid(role), subject=role.value, env_var=role.env_var, runner=runner
    )


def bws_get_argv(uuid: str) -> list[str]:
    """The one `bws secret get` invocation every resolver in this package uses.

    `FORCE_COLOR` / `CLICOLOR_FORCE` make bws wrap its output in ANSI escapes
    even when stdout is a pipe, and Node toolchains set them routinely; the
    token then arrives wrapped in control bytes and every API call dies as a
    bare HTTP 400 naming nothing. Unsetting both and passing `--color no` does
    not depend on the flag winning against a forcing variable.
    """
    return [
        "env",
        "-u",
        "FORCE_COLOR",
        "-u",
        "CLICOLOR_FORCE",
        "bws",
        "secret",
        "get",
        uuid,
        "--output",
        "env",
        "--color",
        "no",
    ]


def fetch_bws_secret(uuid: str, *, subject: str, env_var: str, runner: Runner | None = None) -> str:
    """Fetch and parse one BWS secret's value. Never logged, never echoed on failure.

    `subject` names what the value is for and `env_var` names the environment
    override, so every failure tells the operator both routes.
    """
    if not os.environ.get("BWS_ACCESS_TOKEN"):
        raise CredentialError(
            f"no credential for {subject}: set {env_var}, or set BWS_ACCESS_TOKEN "
            f"so it can be fetched from BWS secret {uuid}"
        )
    not_found = CredentialError(
        f"bws CLI not found while resolving {subject}: install and authenticate bws, "
        f"or set {env_var} instead"
    )
    try:
        result = (runner or _default_runner)(bws_get_argv(uuid))
    except FileNotFoundError as error:
        raise not_found from error
    except subprocess.TimeoutExpired as error:
        raise CredentialError(
            f"bws secret get timed out after {BWS_TIMEOUT_SECONDS}s while resolving "
            f"{subject}: authenticate bws, or set {env_var} instead"
        ) from error
    # `env` reports a missing program as exit 127 rather than raising.
    if result.returncode == 127:
        raise not_found
    if result.returncode != 0:
        raise CredentialError(
            f"bws secret get failed for {subject} (secret {uuid}), exit {result.returncode}"
        )
    return _parse_bws_env_output(result.stdout, subject, uuid)


def _parse_bws_env_output(stdout: str, subject: str, uuid: str) -> str:
    """Extract the value from `bws secret get --output env` (KEY="value" lines).

    Falls back to the whole trimmed stdout only when no line looked like
    KEY=value at all (a bare value). A KEY="" line is a value that failed to
    resolve, not a bare value -- it must raise, never fall through to the
    bare-stdout branch (which would otherwise return the literal `KEY=""`
    text as if it were a token). Never echoes stdout on failure -- it is the
    secret.
    """
    saw_separator = False
    for line in stdout.splitlines():
        _, separator, value = line.partition("=")
        if not separator:
            continue
        saw_separator = True
        value = value.strip().strip('"')
        if value:
            return value
    if not saw_separator:
        bare = stdout.strip()
        if bare:
            return bare
    raise CredentialError(f"bws secret get returned no value for {subject} (secret {uuid})")
