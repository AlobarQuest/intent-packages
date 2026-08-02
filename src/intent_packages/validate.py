"""Package validation (spec §6): structural + typing + identity + acceptance +
trust + cross-file semantic checks.

`validate_package` runs checks:
  - K  (closed schema)  — no unknown keys at any level except the reserved
                           top-level `profile`/`profile_fields`.
  - J  (strict typing)  — no float/datetime/date/bytes anywhere; every
                           documented key present.
  - ID (identity)        — package_id == the package directory's basename.
  - TR (trust)            — every sources[] entry declares a legal `trust`.
  - A  (acceptance)       — unique well-formed ids, enum evidence_type,
                           non-empty evidence, legal approver form.
  - P  (profiles, WS-2.2) — dispatches to a registered domain profile's own
                           validator when the package declares `profile:`;
                           see `profiles/__init__.py`.
  - S/H/T/L (cross-file)  — status/lineage mirror, hash drift, authority
                           envelope, lineage consistency; implemented in
                           `checks_semantic.py` (kept out of this file so it
                           doesn't grow unwieldy) and appended here.

`validate_package` returns hard ERRORS only (empty == valid; the CI gate
exits non-zero on any error). Two things are deliberately warnings, not
errors, and never appear in `validate_package`'s return value:
  - non-empty `scope.open_questions` (check O) — `approve` enforces this as
    a hard error later; here it is surfaced by `validate_warnings`.
  - a missing registry (`registry.registry_dir() is None`) — degrades check
    T's in-vocabulary check to a skip, and is separately noted by
    `validate_warnings` so CI/other checkouts without a security-standards
    checkout aren't misled into thinking authority terms were verified.
The `validate` CLI prints `validate_warnings`' output to stderr; it never
affects `validate_package`'s errors or the process exit code.
"""

from __future__ import annotations

import re
from pathlib import Path

from intent_packages import checks_semantic, profiles, registry
from intent_packages.loader import LoadError, load_package
from intent_packages.schema import TOP_SCHEMA, _scan_forbidden_types, _walk

# Top-level keys the universal TOP_SCHEMA does not describe but a package may still carry.
# `reach` (WS-P2.18, orchestrator ADR-0009) declares what the work touches when it runs; its
# MEMBERSHIP is owned by the orchestrator (`reach_vocabulary.py`) and deliberately not enumerated
# here. Two copies of one vocabulary is the drift the orchestrator has paid for three times, and
# both failure directions are already loud: a member the orchestrator does not know fails intake
# with a named error, and a key this repo does not accept fails right here.
RESERVED_TOP_LEVEL = frozenset({"profile", "profile_fields", "reach"})

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
ISO_8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
EXTERNAL_TARGET_RE = re.compile(r"^external:.+")


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


# The states a package passes through before it is approved, and the boundary at which `reach`
# becomes mandatory (WS-P2.18 Increment 4). Keyed on the lifecycle rather than on a date because a
# date is a boundary a package authored before it still satisfies afterwards: every package reaches
# `approved` THROUGH one of these, so requiring it here is a requirement no new package can miss.
# The twenty-four packages authored before the key existed are all `approved` or later and their
# YAML is hashed into lineage approvals, so this asks nothing of them -- which is the point. They
# are exempt because they are finished, not because they are old.
PRE_APPROVAL_STATES = frozenset({"draft", "needs_clarification", "ready_for_review"})


def _check_reach(pkg: dict, errors: list[str]) -> None:
    """Check RE: `reach` must be declared before approval, and must be a list of strings.

    SHAPE ONLY. An author gets the mistyped-field answer here, one step before intake; the
    orchestrator answers "is that a real reach value" against the vocabulary it owns.

    The orchestrator refuses to admit work whose reach nobody declared, so a package that reaches
    approval without one is a package that cannot run. Failing here means the author learns that
    while the file is still editable -- afterwards it is not, because approval hashes it.
    """
    if "reach" not in pkg:
        if pkg.get("status") in PRE_APPROVAL_STATES:
            errors.append(
                "reach: missing required key — declare what this work touches when it runs "
                "(the orchestrator refuses to admit work with no declared reach)"
            )
        return
    reach = pkg["reach"]
    if not isinstance(reach, list) or not reach:
        errors.append("reach: expected a non-empty list of reach values")
        return
    for i, item in enumerate(reach):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"reach[{i}]: expected a non-empty string")


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
            errors.append(f"sources[{i}].trust: {trust!r} is not one of {sorted(TRUST_VALUES)}")


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

    _check_acceptance_approver(item.get("approver"), evidence_type, path, registry_present, errors)


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


def _check_scalar_formats(pkg: dict, errors: list[str]) -> None:
    created_at = pkg.get("created_at")
    if isinstance(created_at, str) and not ISO_8601_RE.fullmatch(created_at):
        errors.append("created_at: must be an ISO-8601 timestamp with timezone")

    risk = pkg.get("risk")
    target = risk.get("escalation_target") if isinstance(risk, dict) else None
    if not isinstance(target, str):
        return
    if EXTERNAL_TARGET_RE.fullmatch(target):
        return
    if registry.registry_dir() is not None and not registry.is_registered_agent(target):
        errors.append("risk.escalation_target: must be a registered agent id or external:<label>")


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
        _check_reach(pkg, errors)
        _check_trust(pkg, errors)
        _check_acceptance(pkg, errors)
        _check_scalar_formats(pkg, errors)
        errors.extend(profiles.validate_profile(pkg))

    result = [f"package.yaml: {e}" for e in errors]

    if isinstance(pkg, dict):
        result.extend(checks_semantic.cross_file_errors(pkg, pkg_dir))

    return result


def validate_warnings(pkg_dir: str | Path) -> list[str]:
    """Non-fatal warnings `validate_package` deliberately excludes: open
    questions remaining (check O — `approve` enforces this as a hard error;
    this is the earlier, non-blocking heads-up) and registry absence (which
    silently narrows check T). Returned separately so `validate_package`
    keeps its "empty == valid" contract; the `validate` CLI prints these to
    stderr without affecting the exit code."""
    pkg_dir = Path(pkg_dir)
    try:
        pkg = load_package(pkg_dir)
    except LoadError:
        return []

    warnings: list[str] = []
    if isinstance(pkg, dict):
        scope = pkg.get("scope")
        open_questions = scope.get("open_questions") if isinstance(scope, dict) else None
        if isinstance(open_questions, list) and open_questions:
            warnings.append(
                f"warning: {len(open_questions)} open question(s) — "
                "approve will refuse until resolved"
            )
        if pkg.get("profile") is None and pkg.get("status") not in {"closed", "superseded"}:
            acceptance = pkg.get("acceptance")
            if isinstance(acceptance, list):
                tagged = [
                    i
                    for i, item in enumerate(acceptance)
                    if isinstance(item, dict)
                    and isinstance(item.get("evidence"), str)
                    and item["evidence"].startswith(tuple(profiles.KNOWN_EVIDENCE_PREFIXES))
                ]
                if tagged:
                    warnings.append(
                        "warning: recognized profile evidence tags appear without "
                        f"a declared profile (acceptance indexes: {tagged})"
                    )

    if registry.registry_dir() is None:
        warnings.append(
            "note: registry not found; authority-vocabulary and registered-approver checks skipped"
        )

    return warnings
