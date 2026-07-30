"""Thin subprocess wrappers over the `orchestrator` CLI (must be on PATH).

Scoped to LOCAL computation the orchestrator owns (e.g. `conformance-claim`,
which runs real scanners against a checkout) -- never API calls. Those speak
HTTP via `intent_packages.factory.api.OrchestratorApi` instead: one transport,
one auth path, one error vocabulary for everything that crosses the network.

Mirrors emitter.py's shell-out pattern so intent-packages keeps a pyyaml-only
runtime footprint. Every call uses --json (compact json.dumps stdout) and treats
an "error" key or a non-zero exit as failure.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

DEFAULT_TIMEOUT_SECONDS = 120


class OrchestratorCliError(Exception):
    """Raised when an `orchestrator` CLI call fails or returns an error body."""


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=DEFAULT_TIMEOUT_SECONDS)


class OrchestratorClient:
    def __init__(self, runner: Runner | None = None) -> None:
        self._run = runner or _default_runner

    def _call(self, argv: list[str]) -> dict:
        try:
            result = self._run(["orchestrator", *argv, "--json"])
        except OSError as error:
            # e.g. FileNotFoundError when `orchestrator` isn't on PATH -- folded
            # into the same error vocabulary as a non-zero exit / bad output,
            # so every caller has exactly one exception type to catch.
            raise OrchestratorCliError(
                f"could not run `orchestrator {' '.join(argv)}`: {error}"
            ) from error
        except subprocess.TimeoutExpired as error:
            # `TimeoutExpired` is a `SubprocessError`, NOT an `OSError`, so the
            # clause above cannot see it: a hung subprocess used to traceback
            # out of both `journey.submit` and `decompose.run`.
            # `credentials.py::resolve_token` already guarded its own runner
            # this way; the repo's two subprocess wrappers now agree.
            raise OrchestratorCliError(
                f"`orchestrator {' '.join(argv)}` timed out after {DEFAULT_TIMEOUT_SECONDS}s"
            ) from error
        if result.returncode != 0:
            raise OrchestratorCliError(
                f"orchestrator {' '.join(argv)} exited {result.returncode}: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise OrchestratorCliError(f"non-JSON output: {result.stdout!r}") from error
        if isinstance(value, dict) and "error" in value:
            raise OrchestratorCliError(str(value["error"]))
        if not isinstance(value, dict):
            raise OrchestratorCliError(f"expected a JSON object, got {type(value).__name__}")
        return value

    def conformance_claim(self, repo_path: str) -> dict:
        return self._call(["conformance-claim", repo_path])

    def emit_intake_payload(
        self, package_path: str, source_repository: str, idempotency_key: str
    ) -> dict:
        return self._call(
            [
                "emit-intake-payload",
                package_path,
                "--source-repository",
                source_repository,
                "--idempotency-key",
                idempotency_key,
            ]
        )
