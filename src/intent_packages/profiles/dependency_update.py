"""Dependency-update delivery profile (WS-P2.10): per-tooling pin discovery,
mutators, deterministic verifiers, and the byte-pinned authority envelope.

The envelope shape is fixed by orchestrator's
tests/fixtures/runner_authority_envelope.json (a cross-repo contract). We emit it
minus constraints.work_unit_id, which the orchestrator stamps.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CAPABILITIES: dict[str, str] = {
    "command.run": "allowed",
    "github.pr.create": "allowed",
    "orchestrator.claim": "allowed",
    "orchestrator.evidence.write": "allowed",
    "repo.edit": "allowed",
    "repo.read": "allowed",
}
BUDGETS: dict[str, int] = {"max_attempts": 3, "max_llm_calls": 4}

# Runner-honesty deny-list (validation #2): tool-guarded checks the bare hosted
# runner cannot honestly run (need services / a migrated DB / can exit 0 having
# verified nothing). uv lock --check and grep are deterministic and allowed.
DENIED_VERIFIER_PATTERNS: tuple[str, ...] = (
    r"\bmake\s+check\b",
    r"\bmake\s+test\b",
    r"\bpytest\b",
    r"\bnpm\s+test\b",
    r"\bnpm\s+run\s+test\b",
    r"\btox\b",
    r"\bnox\b",
)


class ProfileError(Exception):
    """Raised when a tooling profile cannot build a valid envelope."""


@dataclass(frozen=True)
class PinSite:
    file: str
    label: str
    current_version: str | None


@dataclass(frozen=True)
class ToolingProfile:
    name: str
    discover_pin_sites: Callable[[Path, str], list[PinSite]]
    mutation_commands: Callable[[str, str, str, list[PinSite]], list[str]]
    verifier_command: Callable[[str, str, str, list[PinSite]], str]


# ----- pip / requirements.txt -----

_PIP_FILES = ("requirements.txt", "requirements-dev.txt")


def _pip_discover(repo: Path, package: str) -> list[PinSite]:
    pattern = re.compile(rf"^{re.escape(package)}==(.+)$")
    sites: list[PinSite] = []
    for name in _PIP_FILES:
        path = repo / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line.strip())
            if match:
                sites.append(PinSite(name, name, match.group(1)))
                break
    return sites


def _pip_mutation(package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    return [f"sed -i 's/^{package}=={old}$/{package}=={new}/' {site.file}" for site in sites]


def _pip_verifier(package: str, old: str, new: str, sites: list[PinSite]) -> str:
    primary = next((s.file for s in sites if s.file == "requirements.txt"), None)
    primary = primary or (sites[0].file if sites else "requirements.txt")
    return f"grep -qx '{package}=={new}' {primary}"


# ----- uv / pyproject.toml -----

_UV_PIN_RE = re.compile(r"^\s*(?:==|>=)\s*(.+?)\s*$")


def _uv_pin_version(spec: str, package: str) -> str | None:
    """Extract version from a PEP 508 requirement string.

    spec is a PEP 508 requirement string, e.g. "fastapi==0.139.0" or "fastapi>=1,<2"
    """
    name = re.split(r"[<>=!~ \[]", spec.strip(), maxsplit=1)[0]
    if name != package:
        return None
    remainder = spec.strip()[len(name) :]
    match = re.search(r"(?:==|>=)\s*([0-9][^,;\s]*)", remainder)
    return match.group(1) if match else None


def _uv_discover(repo: Path, package: str) -> list[PinSite]:  # noqa: C901
    path = repo / "pyproject.toml"
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sections: list[tuple[str, list]] = []
    project = data.get("project", {})
    if isinstance(project.get("dependencies"), list):
        sections.append(("project.dependencies", project["dependencies"]))
    for group, specs in (data.get("dependency-groups") or {}).items():
        if isinstance(specs, list):
            sections.append((f"dependency-groups.{group}", specs))
    for extra, specs in (project.get("optional-dependencies") or {}).items():
        if isinstance(specs, list):
            sections.append((f"optional-dependencies.{extra}", specs))
    sites: list[PinSite] = []
    for label, specs in sections:
        for spec in specs:
            if not isinstance(spec, str):
                continue
            version = _uv_pin_version(spec, package)
            if version is not None:
                sites.append(PinSite("pyproject.toml", label, version))
                break
    return sites


def _uv_mutation(package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    dev_only = bool(sites) and all(
        s.label.startswith(("dependency-groups", "optional-dependencies")) for s in sites
    )
    flag = "--dev " if dev_only else ""
    return [f"uv add {flag}'{package}>={new}'"]


def _uv_verifier(package: str, old: str, new: str, sites: list[PinSite]) -> str:
    return "uv lock --check"


PROFILES: dict[str, ToolingProfile] = {
    "pip": ToolingProfile("pip", _pip_discover, _pip_mutation, _pip_verifier),
    "uv": ToolingProfile("uv", _uv_discover, _uv_mutation, _uv_verifier),
}


def build_envelope(
    target_repo: str,
    tooling: str,
    package: str,
    old: str,
    new: str,
    conformance: dict,
    sites: list[PinSite],
) -> dict:
    if tooling not in PROFILES:
        raise ProfileError(f"unknown tooling: {tooling}")
    profile = PROFILES[tooling]
    mutations = profile.mutation_commands(package, old, new, sites)
    if not mutations:
        raise ProfileError(f"{tooling}: no mutation commands (no pin sites for {package}?)")
    verifier = profile.verifier_command(package, old, new, sites)
    return {
        "budgets": dict(BUDGETS),
        "capabilities": dict(CAPABILITIES),
        "change_class": "dependency-update",
        "conformance": conformance,
        "constraints": {
            "allowed_commands": [*mutations, verifier],
            "mutation_commands": list(mutations),
            "target_repository": target_repo,
        },
    }
