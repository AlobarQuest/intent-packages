"""Injectable factory-events emitter.

Wraps the security-standards `factory_events` CLI (WS-1.1 audit-event
envelope) so intent-packages code can emit lifecycle audit events without a
hard dependency on that repo being importable in-process. `NullEmitter` is
used for tests and `--no-emit` runs; `FactoryEventsEmitter` shells out to
`python -m factory_events emit` when real emission is wanted.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

from intent_packages import registry

_DEFAULT_ACTOR = "claude-code-interactive"
EMIT_TIMEOUT_SECONDS = 30


class EmitError(Exception):
    """Raised when a factory-events emit attempt fails."""


class Emitter(Protocol):
    def emit(self, action: str, ref: str, evidence: dict) -> str | None: ...


class NullEmitter:
    """No-op emitter for tests and `--no-emit` runs."""

    def emit(self, action: str, ref: str, evidence: dict) -> str | None:
        return None


def _parse_event_id(stdout: str) -> str | None:
    """Extract the emitted event_id from `factory_events emit` stdout.

    Strategy: if any stdout line parses as JSON with an `event_id` key,
    return that. Otherwise fall back to the last non-empty
    whitespace-delimited token if it looks like an id. Otherwise None.

    Note: the `len(token) > 3` bare-token heuristic below is a best-effort
    fallback pending a formal event_id format contract, not a derived rule.
    """
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]

    for line in lines:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "event_id" in data:
            return data["event_id"]

    if not lines:
        return None

    tokens = lines[-1].split()
    if not tokens:
        return None
    token = tokens[-1]
    return token if len(token) > 3 else None


def _security_standards_dir() -> Path:
    env_dir = os.environ.get("SECURITY_STANDARDS_DIR")
    if env_dir:
        return Path(env_dir)

    reg_dir = registry.registry_dir()
    if reg_dir is not None:
        return reg_dir.parent

    raise EmitError("cannot locate security-standards to emit")


def _events_python(sec_std_dir: Path) -> str:
    venv_python = sec_std_dir / ".venv-events" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


class FactoryEventsEmitter:
    """Emits a factory event by shelling out to `python -m factory_events emit`."""

    def emit(self, action: str, ref: str, evidence: dict) -> str | None:
        sec_std_dir = _security_standards_dir()
        actor = os.environ.get("FACTORY_AGENT_ID", _DEFAULT_ACTOR)

        argv = [
            _events_python(sec_std_dir),
            "-m",
            "factory_events",
            "emit",
            "--actor",
            actor,
            "--action",
            action,
            "--result",
            "success",
            "--ref",
            ref,
            "--evidence-json",
            json.dumps(evidence),
        ]

        env = dict(os.environ)
        src_dir = str(sec_std_dir / "src")
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{src_dir}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else src_dir
        )

        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, env=env, timeout=EMIT_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired as exc:
            raise EmitError(
                f"factory_events emit timed out after {EMIT_TIMEOUT_SECONDS}s"
            ) from exc

        if result.returncode != 0:
            raise EmitError(f"factory_events emit failed: {result.stderr}")

        return _parse_event_id(result.stdout)
