"""maintenance-remediation profile (WS-P2.10): Phase-3 WS-P3.2's authoring
target — a bounded fix in an existing repo from an approved handoff item.
First consumer of OptionalKey (pr_url)."""

from intent_packages import profiles

VALID_FIELDS = {
    "repo": "AlobarQuest/change-manager",
    "remediation_source": "change-manager item 4711 (app-conformance lane)",
    "rollback_plan": "revert the PR; no data migration involved",
}
VALID_AC = [
    {
        "id": "AC-001",
        "condition": "fix lands and named check passes",
        "evidence_type": "automated_check",
        "evidence": "ci: named check on the PR head",
        "approver": "role:verifier",
    },
    {
        "id": "AC-002",
        "condition": "human confirms the remediation closes the handoff item",
        "evidence_type": "human_review",
        "evidence": "human: Devon reviews the closed item",
        "approver": "human:devon",
    },
]


def _pkg(fields: dict, acceptance: list) -> dict:
    return {
        "profile": "maintenance-remediation",
        "profile_fields": fields,
        "acceptance": acceptance,
    }


def test_registered_factory_executable():
    profile = profiles.PROFILES["maintenance-remediation"]
    assert profile.change_class == "maintenance-remediation"
    assert profile.forbidden_evidence_types == frozenset({"automated_test"})
    assert profile.tooling is None  # no decompose lane yet; authoring-time only


def test_valid_package_without_pr_url_passes():
    assert profiles.validate_profile(_pkg(VALID_FIELDS, VALID_AC)) == []


def test_valid_package_with_pr_url_passes():
    fields = dict(VALID_FIELDS, pr_url="https://github.com/AlobarQuest/change-manager/pull/34")
    assert profiles.validate_profile(_pkg(fields, VALID_AC)) == []


def test_pr_url_wrong_type_fails():
    errs = profiles.validate_profile(_pkg(dict(VALID_FIELDS, pr_url=34), VALID_AC))
    assert "profile_fields.pr_url: expected str, got int" in errs


def test_missing_required_field_fails():
    fields = {k: v for k, v in VALID_FIELDS.items() if k != "rollback_plan"}
    errs = profiles.validate_profile(_pkg(fields, VALID_AC))
    assert "profile_fields.rollback_plan: missing required key" in errs


def test_automated_test_forbidden():
    bad = [dict(VALID_AC[0], evidence_type="automated_test")]
    errs = profiles.validate_profile(_pkg(VALID_FIELDS, bad))
    assert any("forbidden by this profile" in e for e in errs)


def test_unknown_key_in_profile_fields_fails():
    errs = profiles.validate_profile(_pkg(dict(VALID_FIELDS, branch="main"), VALID_AC))
    assert "profile_fields.branch: unknown key" in errs
