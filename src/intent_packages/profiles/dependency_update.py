"""Dependency-update delivery profile (WS-P2.10): per-tooling pin discovery,
mutators, deterministic verifiers, and the byte-pinned authority envelope.

The envelope shape is fixed by orchestrator's
tests/fixtures/runner_authority_envelope.json (a cross-repo contract). We emit it
minus constraints.work_unit_id, which the orchestrator stamps.
"""

from __future__ import annotations

import json
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


def _uv_sections(data: dict) -> list[tuple[str, list[str]]]:
    """Build the (label, specs) sections of a parsed pyproject.toml to scan for pins."""
    sections: list[tuple[str, list[str]]] = []
    project = data.get("project", {})
    if isinstance(project.get("dependencies"), list):
        sections.append(("project.dependencies", project["dependencies"]))
    for group, specs in (data.get("dependency-groups") or {}).items():
        if isinstance(specs, list):
            sections.append((f"dependency-groups.{group}", specs))
    for extra, specs in (project.get("optional-dependencies") or {}).items():
        if isinstance(specs, list):
            sections.append((f"optional-dependencies.{extra}", specs))
    return sections


def _uv_discover(repo: Path, package: str) -> list[PinSite]:
    path = repo / "pyproject.toml"
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sites: list[PinSite] = []
    for label, specs in _uv_sections(data):
        for spec in specs:
            if not isinstance(spec, str):
                continue
            version = _uv_pin_version(spec, package)
            if version is not None:
                sites.append(PinSite("pyproject.toml", label, version))
                break
    return sites


def _uv_section_flag(label: str) -> str:
    """Map a discovered pin-site section to the `uv add` flag that targets it."""
    if label == "project.dependencies":
        return ""
    if label.startswith("dependency-groups."):
        group = label.split(".", 1)[1]
        return "--dev" if group == "dev" else f"--group {group}"
    if label.startswith("optional-dependencies."):
        return f"--optional {label.split('.', 1)[1]}"
    raise ProfileError(f"unknown pin-site section: {label}")


def _uv_add(package: str, new: str, label: str, *, frozen: bool) -> str:
    parts = ["uv", "add"]
    if frozen:
        parts.append("--frozen")
    if flag := _uv_section_flag(label):
        parts.append(flag)
    parts.append(f"'{package}>={new}'")
    return " ".join(parts)


def _uv_mutation(package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    if not sites:
        return []
    if len(sites) == 1:
        # Single site: `uv add` locks inline — the shape proven in production.
        return [_uv_add(package, new, sites[0].label, frozen=False)]
    # uv resolves groups and extras jointly, so a pin split across sections is
    # unsatisfiable the moment one site diverges. Edit every site with --frozen
    # (skip locking), then resolve the whole tree once. `uv lock` mutates
    # uv.lock, so it precedes the `uv lock --check` verifier.
    return [_uv_add(package, new, s.label, frozen=True) for s in sites] + ["uv lock"]


def _uv_verifier(package: str, old: str, new: str, sites: list[PinSite]) -> str:
    return "uv lock --check"


# ----- npm / package.json -----

_NPM_SECTIONS = ("dependencies", "devDependencies")


def _npm_discover(repo: Path, package: str) -> list[PinSite]:
    path = repo / "package.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    sites: list[PinSite] = []
    for section in _NPM_SECTIONS:
        deps = data.get(section)
        if isinstance(deps, dict) and package in deps:
            version = str(deps[package]).lstrip("^~")
            sites.append(PinSite("package.json", section, version))
    return sites


def _npm_mutation(package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    dev = bool(sites) and all(s.label == "devDependencies" for s in sites)
    flag = " --save-dev" if dev else ""
    return [f"npm install {package}@{new} --save-exact{flag}"]


def _npm_verifier(package: str, old: str, new: str, sites: list[PinSite]) -> str:
    return f'grep -q \'"{package}": "{new}"\' package.json'


PROFILES: dict[str, ToolingProfile] = {
    "npm": ToolingProfile("npm", _npm_discover, _npm_mutation, _npm_verifier),
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
