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

# A tag's mapping is a claim about where its evidence actually comes from.
#
# The two types are NOT ordered: automated_check is special-cased ahead of the evaluator lookup
# and resolves ONLY on verifier-owned verifier.github.named_check evidence, while automated_test
# dispatches on the arriving evidence row's type and so can resolve off a worker-recorded row.
# Each is deterministic for exactly one producer, so a tag belongs with whichever producer really
# supplies it.
#
# ci: -> automated_check. Every factory-target repository runs its test job on the pull-request
# head, which is what the verifier observes. It was automated_test, and named-check ingestion
# refuses any criterion not declared automated_check (orchestrator services/verifier_evidence.py),
# so the observed-check lane was unreachable for every package on this profile -- measured end to
# end by WS-P2.35, which had to complete AC-001 on human adjudication after a 409.
#
# gate: -> automated_check too, matching dependency-update and maintenance-remediation. Note this
# is a consistency choice, not a measurement: the existing corpus uses gate: mostly for LOCAL
# commands ("full local make check passes", "tests pass on the branch"), which a named check does
# not publish. It costs nothing today because the runner records nothing deterministic anyway --
# build_verification_evidence (runner.verification) has no production caller, and runner.pr.opened
# has no deterministic evaluator, so both types alike land on judgment_required on the dispatched
# lane. Revisit if the runner ever starts recording verification evidence.
#
# scan:/health: stay automated_test, deliberately. Measured 2026-08-04 across the seven
# factory-target repositories: only security-standards publishes a scan job (on push and
# pull_request), and none publishes a health-probe job reachable on a pull-request head (brain's
# probe is a step inside a deploy job gated to pushes on main). A per-profile map cannot be
# per-repo, so mapping scan: for that one repository's sake would strand it everywhere else --
# and automated_check would forfeit the worker-recorded row these tags can actually resolve on.
#
# review: is a human verdict; automated_test was plainly wrong.
TAG_TO_EVIDENCE_TYPE = {
    "ci:": "automated_check",
    "gate:": "automated_check",
    "scan:": "automated_test",
    "review:": "human_review",
    "health:": "automated_test",
    "human:": "human_review",
}

# The map above supersedes one that required automated_test for every automated tag. The
# revisions below were authored under that map and are validated against it, because an approved
# package's YAML cannot be corrected: evidence_type is inside the canonical hash, so editing it
# invalidates the lineage approval hashed over it and verify-approval fails closed. Conforming
# them would cost a fresh human approval each to satisfy a rule that will never be applied to
# them -- the same trade the factory-policy grandfathering table records for reach.
#
# Keyed on (package_id, revision), never package_id alone: a new revision is fresh authoring with
# its own approval, so it must adopt the canonical map rather than inherit this exemption.
#
# The set is pinned to reality by tests -- every entry must still be on disk and must still need
# the exemption -- so it retires itself as the population turns over.
SUPERSEDED_TAG_TO_EVIDENCE_TYPE = {
    "ci:": "automated_test",
    "gate:": "automated_test",
    "scan:": "automated_test",
    "review:": "automated_test",
    "health:": "automated_test",
    "human:": "human_review",
}

SUPERSEDED_MAP_REVISIONS = frozenset(
    {
        ("conformance-claim-helper", 1),
        ("factory-cli-main-guard", 1),
        ("pre-phase4-foundation-cleanliness", 1),
        ("ws-2.3-intent-authoring-skill-v2", 1),
        ("ws-2.4-brain-approver-gate", 1),
        ("ws-2.4-ci-evidence-control", 1),
        ("ws-3.1-orchestrator-core", 1),
        ("ws-3.2-package-intake-decomposition", 1),
        ("ws-3.3-protocol-smoke-runtime-semantics", 1),
        ("ws-3.4-evidence-events", 2),
        ("ws-p2.1-recovery-controls-drills", 1),
        ("ws-p2.15-fail-closed-lifecycle-guards", 1),
    }
)

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


def _tag_map(package: dict) -> dict[str, str]:
    """The tag map this package is validated against.

    Every package gets the canonical map except the named superseded revisions. An identity that
    is absent or of the wrong type falls through to the canonical map, so a malformed package is
    never exempted.

    The types are checked rather than assumed. `validate_package` accumulates errors instead of
    returning at the first one, so this runs on packages whose `package_id`/`revision` have
    already failed check J -- and a list or dict there would make the membership test raise
    `TypeError`, replacing check J's clean field-path error with a traceback in the CI gate.
    `bool` is excluded deliberately: it is an `int` subclass and `hash(True) == hash(1)`, so
    `revision: true` would otherwise match a revision-1 entry.
    """
    package_id = package.get("package_id")
    revision = package.get("revision")
    if (
        not isinstance(package_id, str)
        or not isinstance(revision, int)
        or isinstance(revision, bool)
    ):
        return TAG_TO_EVIDENCE_TYPE
    if (package_id, revision) in SUPERSEDED_MAP_REVISIONS:
        return SUPERSEDED_TAG_TO_EVIDENCE_TYPE
    return TAG_TO_EVIDENCE_TYPE


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, _tag_map(package)))
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
