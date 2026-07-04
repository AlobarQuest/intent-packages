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

import re
from pathlib import Path

from intent_packages import registry
from intent_packages.loader import LoadError, load_package
from intent_packages.schema import TOP_SCHEMA, _scan_forbidden_types, _walk

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
