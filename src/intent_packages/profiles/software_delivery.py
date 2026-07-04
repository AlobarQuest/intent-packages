"""Software-delivery domain profile (WS-2.2 spec §3): profile_fields schema +
evidence-tag/evidence_type consistency checks layered on the universal envelope."""
from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.schema import MapSpec, _l, _s, _walk

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "repo": _s(str),
        "branch": _s(str),
        "deploy_target": _s(str, nullable=True),
        "required_checks": _l(str),
        "rollback_plan": _s(str),
    }
)

TAG_TO_EVIDENCE_TYPE = {
    "ci:": "automated_test",
    "gate:": "automated_test",
    "scan:": "automated_test",
    "review:": "automated_test",
    "health:": "automated_test",
    "human:": "human_review",
}

_NON_EMPTY_STRING_FIELDS = ("repo", "branch", "rollback_plan")


def _check_profile_fields(package: dict) -> list[str]:
    errors: list[str] = []
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        errors.append("profile_fields: missing required key")
        return errors

    _walk(fields, PROFILE_FIELDS_SCHEMA, "profile_fields", errors)
    if errors:
        return errors

    for key in _NON_EMPTY_STRING_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and not value.strip():
            errors.append(f"profile_fields.{key}: must be a non-empty string")

    required_checks = fields.get("required_checks")
    if isinstance(required_checks, list) and not required_checks:
        errors.append("profile_fields.required_checks: must be a non-empty list")

    return errors


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors
