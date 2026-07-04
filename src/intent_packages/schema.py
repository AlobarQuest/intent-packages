"""Closed-schema spec + generic walker for the universal intent package envelope.

A plain nested structure (`ScalarSpec`/`ListSpec`/`MapSpec`/`OpenMapSpec`) describes
the schema; `_walk` recursively checks a loaded document against it. No jsonschema.

This module is pure schema machinery — the check functions that wire these into
validator-facing errors (K/J/ID/TR/A) live in `validate.py`.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from intent_packages.lifecycle import STATES


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


# Reimplements float/datetime/bytes rejection separately from canonical.py's own
# forbidden-type checks: this scan needs field-path context to produce actionable
# per-field error messages, which canonical.py's checks don't carry.
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
