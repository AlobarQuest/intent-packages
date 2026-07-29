"""Model-routing policy loader (WS-P2.10).

The versioned routing-policy.toml at the repo root is the sole source of model
selection (program exit criterion #11). Consumers: `factory route` (query) and
`factory decompose` (fail-closed change-class lookup). There is deliberately
no implicit default: an unknown surface or change-class is an error, so a new
factory-executable profile cannot ship without its routing row.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class RoutingPolicyError(Exception):
    """Raised when the policy file is missing/malformed or a lookup fails."""


@dataclass(frozen=True)
class RoutingRow:
    id: str
    models: tuple[str, ...]
    model_ids: tuple[str, ...]
    rationale: str
    decided: str


@dataclass(frozen=True)
class RoutingPolicy:
    version: int
    models: dict[str, str]
    surfaces: dict[str, RoutingRow]
    change_classes: dict[str, RoutingRow]
    no_llm: tuple[str, ...]


def default_policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "routing-policy.toml"


def _require_str(table: dict, key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RoutingPolicyError(f"{where}: {key} must be a non-empty string")
    return value


def _build_row(table: dict, row_id: str, models: dict[str, str], where: str) -> RoutingRow:
    slugs = table.get("models")
    if not isinstance(slugs, list) or not slugs:
        raise RoutingPolicyError(f"{where}: models must be a non-empty list")
    for slug in slugs:
        if slug not in models:
            raise RoutingPolicyError(
                f"{where}: unknown model slug {slug!r}; valid: {sorted(models)}"
            )
    return RoutingRow(
        id=row_id,
        models=tuple(slugs),
        model_ids=tuple(models[s] for s in slugs),
        rationale=_require_str(table, "rationale", where),
        decided=_require_str(table, "decided", where),
    )


def _parse_toml(path: Path) -> dict:
    if not path.is_file():
        raise RoutingPolicyError(f"routing policy not found: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise RoutingPolicyError(f"routing policy is not valid TOML: {error}") from error


def _validate_version(data: dict) -> int:
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise RoutingPolicyError("version must be a positive integer")
    return version


def _validate_models_table(data: dict) -> dict[str, str]:
    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise RoutingPolicyError("[models] must be a non-empty table")
    for slug, model_id in models.items():
        if not isinstance(model_id, str) or not model_id.strip():
            raise RoutingPolicyError(f"[models].{slug}: model id must be a non-empty string")
    return models


def _parse_surfaces(data: dict, models: dict[str, str]) -> dict[str, RoutingRow]:
    surfaces: dict[str, RoutingRow] = {}
    for table in data.get("surface") or []:
        row_id = _require_str(table, "id", "[[surface]]")
        if row_id in surfaces:
            raise RoutingPolicyError(f"duplicate surface id: {row_id}")
        _require_str(table, "where", f"surface {row_id}")
        surfaces[row_id] = _build_row(table, row_id, models, f"surface {row_id}")
    if not surfaces:
        raise RoutingPolicyError("policy declares no [[surface]] rows")
    return surfaces


def _parse_change_classes(
    data: dict, models: dict[str, str], surfaces: dict[str, RoutingRow]
) -> dict[str, RoutingRow]:
    change_classes: dict[str, RoutingRow] = {}
    for name, table in (data.get("change_class") or {}).items():
        surface_ref = _require_str(table, "surface", f"change_class {name}")
        if surface_ref not in surfaces:
            raise RoutingPolicyError(
                f"change_class {name}: unknown surface {surface_ref!r}; valid: {sorted(surfaces)}"
            )
        change_classes[name] = _build_row(table, name, models, f"change_class {name}")
    return change_classes


def _validate_no_llm(data: dict) -> tuple[str, ...]:
    no_llm_table = data.get("no_llm") or {}
    items = no_llm_table.get("items")
    if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
        raise RoutingPolicyError("[no_llm].items must be a list of strings")
    return tuple(items)


def load_policy(path: Path | None = None) -> RoutingPolicy:
    path = path or default_policy_path()
    data = _parse_toml(path)

    version = _validate_version(data)
    models = _validate_models_table(data)
    surfaces = _parse_surfaces(data, models)
    change_classes = _parse_change_classes(data, models, surfaces)
    no_llm = _validate_no_llm(data)

    return RoutingPolicy(
        version=version,
        models=dict(models),
        surfaces=surfaces,
        change_classes=change_classes,
        no_llm=no_llm,
    )


def resolve_surface(policy: RoutingPolicy, surface_id: str) -> RoutingRow:
    row = policy.surfaces.get(surface_id)
    if row is None:
        raise RoutingPolicyError(
            f"unknown surface {surface_id!r}; valid: {sorted(policy.surfaces)}"
        )
    return row


def resolve_change_class(policy: RoutingPolicy, change_class: str) -> RoutingRow:
    row = policy.change_classes.get(change_class)
    if row is None:
        raise RoutingPolicyError(
            f"unknown change-class {change_class!r}; valid: {sorted(policy.change_classes)}"
        )
    return row
