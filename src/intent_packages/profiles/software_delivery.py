"""Software-delivery domain profile (WS-2.2 spec §3): profile_fields schema +
evidence-tag/evidence_type consistency checks layered on the universal envelope."""

from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.profiles.base import DeliveryProfile, EnrichmentSpec
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

    for key in _NON_EMPTY_STRING_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and not value.strip():
            errors.append(f"profile_fields.{key}: must be a non-empty string")

    required_checks = fields.get("required_checks")
    if isinstance(required_checks, list):
        if not required_checks:
            errors.append("profile_fields.required_checks: must be a non-empty list")
        else:
            for i, item in enumerate(required_checks):
                if isinstance(item, str) and not item.strip():
                    errors.append(
                        f"profile_fields.required_checks[{i}]: must be a non-empty string"
                    )

    return errors


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors


DELIVERY_PROFILE = DeliveryProfile(
    name="software-delivery",
    change_class="software-delivery",
    enrichment=EnrichmentSpec(code_road_slugs=("error-logging",), infra_min_authority="required"),
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    evidence_expectations="Tag-mapped producers per TAG_TO_EVIDENCE_TYPE; declared per package.",
    observation_window="Declared per package (follow_up); no profile default.",
    validate=validate,
)
