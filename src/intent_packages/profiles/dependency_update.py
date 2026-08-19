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

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.profiles.base import (
    AuthorityDefaults,
    DeliveryProfile,
    EnrichmentSpec,
)
from intent_packages.schema import MapSpec, OptionalKey, _s, _walk

CAPABILITIES: dict[str, str] = {
    "command.run": "allowed",
    "github.pr.create": "allowed",
    "orchestrator.claim": "allowed",
    "orchestrator.evidence.write": "allowed",
    "repo.edit": "allowed",
    "repo.read": "allowed",
}
BUDGETS: dict[str, int] = {"max_attempts": 3, "max_llm_calls": 120}

# 120 is structural, not an estimate: `max_attempts` x factory-runner's own
# `max_turns` literal, which is 40 and is the only thing bounding a single
# attempt. Setting it there is what makes the RECOVERABLE gate
# (`attempts_exhausted`, curable by approve_retry) bind before the UNRECOVERABLE
# one (`budget_exceeded`, curable by nothing, because the envelope is write-once
# and its approval cannot be taken back). Over-provisioning costs nothing --
# nothing checks spend mid-run -- and measured burns run 9, 29 and 58 calls.
#
# It was 4 until 2026-08-19, while `approval-policy.toml`'s grant already
# granted 120 and said so. A package therefore declared 120 and the unit
# envelope `build_envelope` derived from it declared 4, because this constant is
# what the envelope is stamped from. Nothing compared the two. Keep them equal:
# the policy is a CEILING, so a lower default here is not a safety margin, it is
# a way to kill a unit permanently that no later act can undo.

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
    mutation_commands: Callable[[Path, str, str, str, list[PinSite]], list[str]]
    verifier_commands: Callable[[Path, str, str, str, list[PinSite]], list[str]]


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


def _pip_mutation(repo: Path, package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    return [f"sed -i 's/^{package}=={old}$/{package}=={new}/' {site.file}" for site in sites]


def _pip_verifier(repo: Path, package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    primary = next((s.file for s in sites if s.file == "requirements.txt"), None)
    primary = primary or (sites[0].file if sites else "requirements.txt")
    return [f"grep -qx '{package}=={new}' {primary}"]


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


def _uv_mutation(repo: Path, package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
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


def _uv_verifier(repo: Path, package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    return ["uv lock --check"]


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


def _npm_build_script(repo: Path) -> bool:
    """Whether the checkout declares an npm `build` script."""
    path = repo / "package.json"
    if not path.is_file():
        return False
    scripts = json.loads(path.read_text(encoding="utf-8")).get("scripts")
    return isinstance(scripts, dict) and bool(scripts.get("build"))


def _npm_mutation(repo: Path, package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    dev = bool(sites) and all(s.label == "devDependencies" for s in sites)
    flag = " --save-dev" if dev else ""
    commands = [f"npm install {package}@{new} --save-exact{flag}"]
    # A compiler or bundler bump is only claimed to work once the repository's own
    # build has run against it, and the grep below cannot say anything about that:
    # it asserts that the mutator did what the mutator does. Declared as a MUTATOR
    # rather than a verifier because a build can write tracked files --
    # infraops-mcp-server tracks 376 of them under dist/ and fails a pull request
    # whose committed output is stale -- so calling it a pure check would
    # understate what the envelope authorises, and the envelope is what a human's
    # authority approval attests. Resolved here, at authoring time, rather than
    # with npm's own --if-present: a flag that skips silently leaves the envelope
    # ambiguous about what will run, and the dry-run cannot tell the two apart.
    if _npm_build_script(repo):
        commands.append("npm run build")
    return commands


def _npm_verifier(repo: Path, package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    commands: list[str] = []
    # `npm install` and `npm ci` disagree, and the repository's gate runs the second.
    # npm install resolves a workable tree and writes a lockfile; npm ci installs that
    # lockfile strictly and REFUSES it when a peer range is unsatisfied. So a bump can
    # pass every validation here and fail the target repository's named check at
    # dependency installation, before anything is compiled or tested -- which is what
    # happened on 2026-08-19 with typescript 7.0.2 against typescript-eslint's
    # `peer typescript >=4.8.4 <6.1.0`. Because `dry_run_mutation` executes this whole
    # list, naming npm ci here moves that refusal to authoring time, where it costs a
    # decompose run rather than two human approvals and a work-unit attempt.
    #
    # Gated on the lockfile because npm ci requires one and fails without it; a
    # repository that tracks none is verified by the grep alone, as before.
    if (repo / "package-lock.json").is_file():
        commands.append("npm ci")
    commands.append(f'grep -q \'"{package}": "{new}"\' package.json')
    return commands


TOOLING_PROFILES: dict[str, ToolingProfile] = {
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
    *,
    repo: Path,
) -> dict:
    if tooling not in TOOLING_PROFILES:
        raise ProfileError(f"unknown tooling: {tooling}")
    profile = TOOLING_PROFILES[tooling]
    mutations = profile.mutation_commands(repo, package, old, new, sites)
    if not mutations:
        raise ProfileError(f"{tooling}: no mutation commands (no pin sites for {package}?)")
    verifiers = profile.verifier_commands(repo, package, old, new, sites)
    return {
        "budgets": dict(BUDGETS),
        "capabilities": dict(CAPABILITIES),
        "change_class": "dependency-update",
        "conformance": conformance,
        "constraints": {
            "allowed_commands": [*mutations, *verifiers],
            "mutation_commands": list(mutations),
            "target_repository": target_repo,
        },
    }


# ----- declarable delivery profile (WS-P2.10) -----

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "target_repo": _s(str),
        "package": _s(str),
        "from_version": _s(str),
        "to_version": _s(str),
        # ADR-0028. A STANDING package is authored once per (repository, ecosystem,
        # dependency) and revised once per bump; every dependency-update package before
        # this field existed named one specific bump and is finished. Optional, so the
        # historical population still validates -- and declared by the AUTHOR, never by
        # the producer that revises it, which is what keeps it a statement about intent
        # rather than a value the same program writes and then satisfies.
        "standing": OptionalKey(_s(bool)),
    }
)

# Never automated_test: it resolves to judgment_required in the verifier.
# ci:/gate: evidence for this profile is verifier-owned named-check evidence,
# which is exactly what automated_check evaluates deterministically against.
TAG_TO_EVIDENCE_TYPE = {
    "ci:": "automated_check",
    "gate:": "automated_check",
    "human:": "human_review",
}

_NON_EMPTY_STRING_FIELDS = ("target_repo", "package", "from_version", "to_version")


def _check_profile_fields(package: dict) -> list[str]:
    errors: list[str] = []
    if "profile_fields" not in package:
        errors.append("profile_fields: missing required key")
        return errors
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        return errors
    _walk(fields, PROFILE_FIELDS_SCHEMA, "profile_fields", errors)
    if errors:
        return errors
    for key in _NON_EMPTY_STRING_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and not value.strip():
            errors.append(f"profile_fields.{key}: must be a non-empty string")
    return errors


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors


DELIVERY_PROFILE = DeliveryProfile(
    name="dependency-update",
    change_class="dependency-update",
    # Enriched, but empty of code roads: Code Brain holds no content for this
    # class yet. Empty by CONTENT is not the same as absent.
    enrichment=EnrichmentSpec(code_road_slugs=(), infra_min_authority="required"),
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    forbidden_evidence_types=frozenset({"automated_test"}),
    required_checks=("target repo's own named check on the PR head",),
    default_authority=AuthorityDefaults(
        budgets=BUDGETS,
        capabilities=CAPABILITIES,
        command_ordering="mutators first, verifier last; make check never in an envelope",
    ),
    evidence_expectations=(
        "Runner-opened PR; verifier-owned named-check evidence "
        "(verifier.github.named_check) on the PR head; adjudication via "
        "evidence_type automated_check. budgets.max_attempts bounds claims; "
        "budgets.max_llm_calls bounds re-claim eligibility, not spend-in-run."
    ),
    observation_window=(
        "None beyond the named check: a pin move ships no runtime change of its "
        "own, so observation rides the target repo's ordinary release lane."
    ),
    validate=validate,
    tooling=TOOLING_PROFILES,
)
