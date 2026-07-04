"""Infrastructure-change domain profile (WS-2.2 spec §4): profile_fields schema +
evidence-tag/evidence_type consistency checks layered on the universal envelope."""
from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.schema import MapSpec, _s, _walk

BLAST_RADIUS_VALUES = {"single-app", "shared-service", "portfolio-wide"}

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "blast_radius": _s(str, enum=BLAST_RADIUS_VALUES),
        "change_window": _s(str, nullable=True),
        "backup_evidence": _s(str, nullable=True),
        "rollback_plan": _s(str),
    }
)


def _check_profile_fields(package: dict) -> list[str]:
    errors: list[str] = []
    if "profile_fields" not in package:
        errors.append("profile_fields: missing required key")
        return errors
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        # validate.py's check K/J already reports "profile_fields: expected a mapping"
        return errors

    _walk(fields, PROFILE_FIELDS_SCHEMA, "profile_fields", errors)
    if errors:
        return errors

    rollback_plan = fields.get("rollback_plan")
    if isinstance(rollback_plan, str) and not rollback_plan.strip():
        errors.append("profile_fields.rollback_plan: must be a non-empty string")

    return errors


TAG_TO_EVIDENCE_TYPE = {
    "health:": "automated_test",
    "backup:": "automated_test",
    "change-log:": "automated_test",
    "human:": "human_review",
}


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors
