"""Non-software-operational delivery profile (WS-P2.10): work with no repo,
no CI, and no authority envelope — listing launches and similar operational
workflows. Shaped from packages/ws-2.4-historical-listing-launch (the
reference exemplar); WS-P2.13's native run authors the first package that
declares it. Evidence comes from humans, external systems, and observations
only — the tag map has no ci:/gate: entries, so automated_test is
structurally unreachable, and it is explicitly forbidden for defense in
depth."""

from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.profiles.base import DeliveryProfile
from intent_packages.schema import ListSpec, MapSpec, OptionalKey, _s, _walk

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "owner": _s(str),
        "operating_procedure": _s(str),
        "external_systems": OptionalKey(ListSpec(_s(str))),
    }
)

TAG_TO_EVIDENCE_TYPE = {
    "human:": "human_review",
    "external:": "external_attestation",
    "observation:": "observation",
}

_NON_EMPTY_STRING_FIELDS = ("owner", "operating_procedure")


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
    name="non-software-operational",
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    forbidden_evidence_types=frozenset({"automated_test"}),
    evidence_expectations=(
        "human_review, external_attestation, and observation only; no automated "
        "producers exist for this profile's work."
    ),
    observation_window=(
        "Declared per package via follow_up (e.g. days-on-market signals for a listing launch)."
    ),
    validate=validate,
)
