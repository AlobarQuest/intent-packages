"""Package validation (spec §6): structural + typing + identity + acceptance + trust checks.

`validate_package` runs, in this task, checks:
  - K  (closed schema)  — no unknown keys at any level except the reserved
                           top-level `profile`/`profile_fields`.
  - J  (strict typing)  — no float/datetime/date/bytes anywhere; every
                           documented key present.
  - ID (identity)        — package_id == the package directory's basename.
  - TR (trust)            — every sources[] entry declares a legal `trust`.
  - A  (acceptance)       — unique well-formed ids, enum evidence_type,
                           non-empty evidence, legal approver form.

Task 8 appends the cross-file checks (S/H/T/O/L); this module is written so
those can be added as additional `_check_*` calls in `validate_package`
without disturbing the checks implemented here.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

from . import registry
from .lifecycle import STATES
from .loader import LoadError, load_package

RESERVED_TOP_LEVEL = frozenset({"profile", "profile_fields"})

TRUST_VALUES = frozenset({"trusted_instruction", "untrusted_data"})
EVIDENCE_TYPES = frozenset(
    {
        "automated_test",
        "automated_check",
        "human_review",
        "external_attestation",
        "observation",
    }
)
EXTERNAL_APPROVER_EVIDENCE_TYPES = frozenset({"external_attestation", "human_review"})
ACCEPTANCE_ID_RE = re.compile(r"^AC-[0-9]{3,}$")


# --------------------------------------------------------------------------
# Closed-schema spec: a plain nested structure the checks walk. No jsonschema.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalarSpec:
    py_type: type
    nullable: bool = False
    enum: frozenset[str] | None = None


@dataclass(frozen=True)
class ListSpec:
    item: ScalarSpec | MapSpec


@dataclass(frozen=True)
class MapSpec:
    fields: dict[str, ScalarSpec | ListSpec | MapSpec | OpenMapSpec]


@dataclass(frozen=True)
class OpenMapSpec:
    """A mapping with arbitrary str keys and str values, plus required keys."""

    required: frozenset[str] = frozenset()


def _s(py_type: type, *, nullable: bool = False, enum: set[str] | None = None) -> ScalarSpec:
    return ScalarSpec(py_type, nullable=nullable, enum=frozenset(enum) if enum else None)


def _l(py_type: type = str, **kw) -> ListSpec:
    return ListSpec(_s(py_type, **kw))


TOP_SCHEMA = MapSpec(
    {
        "schema_version": _s(int),
        "package_id": _s(str),
        "title": _s(str),
        "revision": _s(int),
        "status": _s(str, enum=set(STATES)),
        "created_by": _s(str),
        "owner": _s(str),
        "created_at": _s(str),
        "supersedes": _s(str, nullable=True),
        "outcome": MapSpec(
            {
                "what": _s(str),
                "why": _s(str),
                "beneficiary": _s(str),
                "success_signal": _s(str),
            }
        ),
        "scope": MapSpec(
            {
                "included": _l(),
                "excluded": _l(),
                "non_goals": _l(),
                "assumptions": _l(),
                "open_questions": _l(),
            }
        ),
        "sources": ListSpec(
            MapSpec(
                {
                    "location": _s(str),
                    "authority_level": _s(
                        str, enum={"authoritative", "supporting", "reference"}
                    ),
                    "required_version": _s(str, nullable=True),
                    "trust": _s(str),  # legal values enforced by dedicated TR check
                    "sensitivity": _s(
                        str, enum={"public", "internal", "confidential", "secret"}
                    ),
                }
            )
        ),
        "constraints": MapSpec(
            {
                "time_budget": _s(str, nullable=True),
                "technology": _s(str, nullable=True),
                "policy_legal": _s(str, nullable=True),
                "privacy_security": _s(str, nullable=True),
                "compatibility": _s(str, nullable=True),
                "quality_accessibility": _s(str, nullable=True),
                "operational": _s(str, nullable=True),
                "other": _l(),
            }
        ),
        "acceptance": ListSpec(
            MapSpec(
                {
                    "id": _s(str),
                    "condition": _s(str),
                    "evidence_type": _s(str),  # enum enforced by dedicated A check
                    "evidence": _s(str),
                    "approver": _s(str),  # form enforced by dedicated A check
                }
            )
        ),
        "authority": MapSpec(
            {
                "allowed": _l(),
                "requires_approval": _l(),
                "prohibited": _l(),
                "budgets": MapSpec(
                    {
                        "max_attempts": _s(int, nullable=True),
                        "max_llm_calls": _s(int, nullable=True),
                    }
                ),
            }
        ),
        "deliverables": MapSpec(
            {
                "artifacts": _l(),
                "destination": _s(str),
                "recipient": _s(str),
                "definition_of_done": _s(str),
                "operator_responsibilities": _l(),
            }
        ),
        "dependencies": MapSpec(
            {
                "predecessor_packages": ListSpec(
                    MapSpec({"package": _s(str), "revision": _s(int)})
                ),
                "external_decisions": _l(),
                "required_people_systems": _l(),
                "required_capabilities": _l(),
                "blocking_conditions": _l(),
            }
        ),
        "risk": MapSpec(
            {
                "failure_modes": _l(),
                "max_impact": _s(str),
                "stop_conditions": _l(),
                "rollback": _s(str),
                "escalation_target": _s(str),
            }
        ),
        "verification": MapSpec(
            {
                "independent_review": _l(),
                "non_mechanical": _l(),
            }
        ),
        "follow_up": MapSpec(
            {
                "required": _s(bool),
                "revisit_when": _s(str, nullable=True),
                "signals": _l(),
                "owner": _s(str, nullable=True),
            }
        ),
        "applicable_standards": OpenMapSpec(required=frozenset({"project"})),
    }
)


def _typename(value: object) -> str:
    return "null" if value is None else type(value).__name__


def _join(path: str, key: str) -> str:
    return key if not path else f"{path}.{key}"


def _check_scalar(value: object, spec: ScalarSpec, path: str, errors: list[str]) -> None:
    if value is None:
        if not spec.nullable:
            errors.append(f"{path}: null is not allowed here")
        return
    expected = spec.py_type
    if expected is bool:
        ok = isinstance(value, bool)
    elif expected is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    else:
        ok = isinstance(value, expected)
    if not ok:
        errors.append(f"{path}: expected {expected.__name__}, got {_typename(value)}")
        return
    if spec.enum is not None and value not in spec.enum:
        errors.append(f"{path}: value {value!r} is not one of {sorted(spec.enum)}")


def _walk(value: object, spec, path: str, errors: list[str]) -> None:
    if isinstance(spec, ScalarSpec):
        _check_scalar(value, spec, path, errors)
    elif isinstance(spec, ListSpec):
        _walk_list(value, spec, path, errors)
    elif isinstance(spec, MapSpec):
        _walk_map(value, spec, path, errors)
    elif isinstance(spec, OpenMapSpec):
        _walk_open_map(value, spec, path, errors)
    else:
        raise TypeError(f"unknown schema spec type: {type(spec).__name__}")  # pragma: no cover


def _walk_list(value: object, spec: ListSpec, path: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{path}: expected a list, got {_typename(value)}")
        return
    for i, item in enumerate(value):
        _walk(item, spec.item, f"{path}[{i}]", errors)


def _walk_map(value: object, spec: MapSpec, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected a mapping, got {_typename(value)}")
        return
    for key in value:
        if key not in spec.fields:
            errors.append(f"{_join(path, key)}: unknown key")
    for key, subspec in spec.fields.items():
        if key not in value:
            errors.append(f"{_join(path, key)}: missing required key")
            continue
        _walk(value[key], subspec, _join(path, key), errors)


def _walk_open_map(value: object, spec: OpenMapSpec, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected a mapping, got {_typename(value)}")
        return
    for key in spec.required:
        if key not in value:
            errors.append(f"{_join(path, key)}: missing required key")
    for key, v in value.items():
        if not isinstance(key, str) or not key:
            errors.append(f"{path}: keys must be non-empty strings (got {key!r})")
        if not isinstance(v, str):
            errors.append(f"{_join(path, key)}: expected str, got {_typename(v)}")


def _check_k_and_j(pkg: object, errors: list[str]) -> None:
    """Check K (closed schema) + the "required keys present" half of check J."""
    if not isinstance(pkg, dict):
        errors.append("top-level document must be a mapping")
        return
    for key in pkg:
        if key not in TOP_SCHEMA.fields and key not in RESERVED_TOP_LEVEL:
            errors.append(f"{key}: unknown key")
    for key, subspec in TOP_SCHEMA.fields.items():
        if key not in pkg:
            errors.append(f"{key}: missing required key")
            continue
        _walk(pkg[key], subspec, key, errors)
    if "profile" in pkg and pkg["profile"] is not None and not isinstance(pkg["profile"], str):
        errors.append("profile: expected str")
    if "profile_fields" in pkg and not isinstance(pkg["profile_fields"], dict):
        errors.append("profile_fields: expected a mapping")


def _scan_forbidden_types(value: object, path: str, errors: list[str]) -> None:
    """Check J (the rest): reject float/datetime/date/bytes ANYWHERE in the tree,
    including inside the opaque `profile_fields` — not just schema-known fields."""
    if isinstance(value, float):
        errors.append(f"{path}: float value {value!r} is not allowed (quote the value)")
    elif isinstance(value, (datetime.datetime, datetime.date)):
        errors.append(f"{path}: datetime/date value is not allowed (use a quoted ISO-8601 string)")
    elif isinstance(value, bytes):
        errors.append(f"{path}: bytes value is not allowed")
    elif isinstance(value, dict):
        for k, v in value.items():
            _scan_forbidden_types(v, _join(path, str(k)), errors)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _scan_forbidden_types(v, f"{path}[{i}]", errors)


def _check_package_id(pkg: dict, pkg_dir: Path, errors: list[str]) -> None:
    """Check ID: package_id must equal the package directory's basename."""
    package_id = pkg.get("package_id")
    expected = pkg_dir.name
    if package_id != expected:
        errors.append(
            f"package_id: {package_id!r} does not match the package directory name {expected!r}"
        )


def _check_trust(pkg: dict, errors: list[str]) -> None:
    """Check TR: every sources[] entry must declare a legal `trust`."""
    sources = pkg.get("sources")
    if not isinstance(sources, list):
        return
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            continue
        trust = src.get("trust")
        if trust not in TRUST_VALUES:
            errors.append(
                f"sources[{i}].trust: {trust!r} is not one of {sorted(TRUST_VALUES)}"
            )


def _check_acceptance_id(item_id: object, path: str, seen_ids: set[str], errors: list[str]) -> None:
    if not isinstance(item_id, str) or not ACCEPTANCE_ID_RE.match(item_id):
        errors.append(f"{path}.id: {item_id!r} must match ^AC-[0-9]{{3,}}$")
    elif item_id in seen_ids:
        errors.append(f"{path}.id: duplicate acceptance id {item_id!r}")
    else:
        seen_ids.add(item_id)


def _check_acceptance_approver(
    approver: object, evidence_type: object, path: str, registry_present: bool, errors: list[str]
) -> None:
    if not isinstance(approver, str) or not approver:
        errors.append(f"{path}.approver: missing or invalid approver")
        return

    if approver == "policy":
        return

    if approver.startswith("external:"):
        label = approver[len("external:") :]
        if not label:
            errors.append(f"{path}.approver: external: approver must include a label")
        if evidence_type not in EXTERNAL_APPROVER_EVIDENCE_TYPES:
            errors.append(
                f"{path}.approver: external: approver is only legal when evidence_type is "
                f"one of {sorted(EXTERNAL_APPROVER_EVIDENCE_TYPES)} "
                f"(got evidence_type={evidence_type!r})"
            )
        return

    # Third legal form: a registered agent id. If the registry isn't checked
    # out here, degrade to a pass rather than a hard failure (Task 8 can
    # tighten this once the registry is a hard dependency).
    if registry_present and not registry.is_registered_agent(approver):
        errors.append(
            f"{path}.approver: {approver!r} is not `policy`, `external:<label>`, "
            "or a registered agent id"
        )


def _check_acceptance_item(
    item: object, path: str, seen_ids: set[str], registry_present: bool, errors: list[str]
) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path}: expected a mapping")
        return

    _check_acceptance_id(item.get("id"), path, seen_ids, errors)

    evidence_type = item.get("evidence_type")
    if evidence_type not in EVIDENCE_TYPES:
        errors.append(
            f"{path}.evidence_type: {evidence_type!r} is not one of {sorted(EVIDENCE_TYPES)}"
        )

    evidence = item.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        errors.append(f"{path}.evidence: must be a non-empty string")

    _check_acceptance_approver(
        item.get("approver"), evidence_type, path, registry_present, errors
    )


def _check_acceptance(pkg: dict, errors: list[str]) -> None:
    """Check A: acceptance items — unique well-formed id, enum evidence_type,
    non-empty evidence, and an approver in one of the three legal forms."""
    items = pkg.get("acceptance")
    if not isinstance(items, list):
        return

    seen_ids: set[str] = set()
    registry_present = registry.registry_dir() is not None

    for i, item in enumerate(items):
        _check_acceptance_item(item, f"acceptance[{i}]", seen_ids, registry_present, errors)


def validate_package(pkg_dir: str | Path) -> list[str]:
    """Validate the package at `pkg_dir`. Returns human-readable error strings
    (empty list == valid). Each message names the field path; all are
    additionally prefixed with the file they apply to."""
    pkg_dir = Path(pkg_dir)
    try:
        pkg = load_package(pkg_dir)
    except LoadError as exc:
        return [f"package.yaml: {exc}"]

    errors: list[str] = []
    _check_k_and_j(pkg, errors)
    _scan_forbidden_types(pkg, "", errors)
    if isinstance(pkg, dict):
        _check_package_id(pkg, pkg_dir, errors)
        _check_trust(pkg, errors)
        _check_acceptance(pkg, errors)

    return [f"package.yaml: {e}" for e in errors]
