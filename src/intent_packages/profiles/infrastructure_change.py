"""Infrastructure-change domain profile (WS-2.2 spec §4): profile_fields schema +
evidence-tag/evidence_type consistency checks layered on the universal envelope."""

from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.profiles.base import DeliveryProfile
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


# Deliberately NOT automated_check, decided 2026-08-04 (WS-P2.36) rather than left silent.
#
# software-delivery's ci:/gate: moved to automated_check in the same change, because those tags
# are satisfied by a GitHub Actions job on the pull-request head, which the verifier can observe.
# None of this profile's tags is. Measured across the seven factory-target repositories: no
# repository publishes a health-probe job that runs on a pull-request head (brain's is a step
# inside a deploy job gated to pushes on main), and there is no backup or change-log job at all.
# Health in this estate is Coolify health checks, the Dockerfile HEALTHCHECK and post-deploy
# deployment_observation records; backups are the vps-backup recipes on a schedule. All are
# non-CI routes that no named check reports.
#
# So automated_check here would fail with named_check_not_found -- the unreachable-lane defect
# WS-P2.36 closed for software-delivery, merely relocated. automated_test is correct: it carries a
# deterministic-permitted floor, resolving deterministically when a worker records a readable
# evidence row and asking a human otherwise, which is what operator-run drills and probes produce.
# Revisit only if a repository starts publishing one of these as a job on the PR head.
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


DELIVERY_PROFILE = DeliveryProfile(
    name="infrastructure-change",
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    evidence_expectations="Tag-mapped producers per TAG_TO_EVIDENCE_TYPE; declared per package.",
    observation_window="Declared per package (follow_up); no profile default.",
    validate=validate,
)
