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


class OrchestratorCliError(Exception):
    """Raised when an `orchestrator` CLI call fails or returns an error body."""


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=120)


class OrchestratorClient:
    def __init__(self, runner: Runner | None = None) -> None:
        self._run = runner or _default_runner

    def _call(self, argv: list[str]) -> dict:
        result = self._run(["orchestrator", *argv, "--json"])
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
