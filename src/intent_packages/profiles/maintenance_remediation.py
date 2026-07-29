"""Maintenance-remediation delivery profile (WS-P2.10): a bounded fix in an
existing repository, authored from an approved handoff item. Phase-3 WS-P3.2
emits proposed packages against this profile; every proposal still terminates
at the four human gates."""

from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.profiles.base import AuthorityDefaults, DeliveryProfile
from intent_packages.profiles.dependency_update import BUDGETS, CAPABILITIES
from intent_packages.schema import MapSpec, OptionalKey, _s, _walk

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "repo": _s(str),
        "remediation_source": _s(str),
        "rollback_plan": _s(str),
        "pr_url": OptionalKey(_s(str)),
    }
)

TAG_TO_EVIDENCE_TYPE = {
    "ci:": "automated_check",
    "gate:": "automated_check",
    "human:": "human_review",
}

_NON_EMPTY_STRING_FIELDS = ("repo", "remediation_source", "rollback_plan")


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
    pr_url = fields.get("pr_url")
    if isinstance(pr_url, str) and not pr_url.strip():
        errors.append("profile_fields.pr_url: must be a non-empty string when present")
    return errors


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors


DELIVERY_PROFILE = DeliveryProfile(
    name="maintenance-remediation",
    change_class="maintenance-remediation",
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
        "Runner-opened PR; verifier-owned named-check evidence on the PR head "
        "(automated_check); a human_review AC confirming the handoff item is "
        "closed. budgets.max_llm_calls bounds re-claim eligibility, not "
        "spend-in-run."
    ),
    observation_window=(
        "Declared per package via follow_up; remediations to running services "
        "should declare follow_up.required=true."
    ),
    validate=validate,
)
