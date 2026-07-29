"""non-software-operational profile (WS-P2.10): the WS-P2.13 vehicle, shaped
from the historical listing-launch package. No repo, no CI, no authority
envelope — evidence is human/external/observation only, so automated_test is
structurally unreachable AND explicitly forbidden."""

from intent_packages import profiles

VALID_FIELDS = {
    "owner": "Devon",
    "operating_procedure": "listing-description skill + listing-launch checklist",
}
VALID_AC = [
    {
        "id": "AC-001",
        "condition": "listing is live on the MLS",
        "evidence_type": "external_attestation",
        "evidence": "external: MLS listing number recorded",
        "approver": "external:mls",
    },
    {
        "id": "AC-002",
        "condition": "Devon confirms marketing assets shipped",
        "evidence_type": "human_review",
        "evidence": "human: Devon signs off",
        "approver": "human:devon",
    },
]


def _pkg(fields: dict, acceptance: list) -> dict:
    return {
        "profile": "non-software-operational",
        "profile_fields": fields,
        "acceptance": acceptance,
    }


def test_registered_without_envelope_or_tooling():
    profile = profiles.PROFILES["non-software-operational"]
    assert profile.change_class is None
    assert profile.default_authority is None
    assert profile.tooling is None
    assert profile.forbidden_evidence_types == frozenset({"automated_test"})


def test_valid_package_passes():
    assert profiles.validate_profile(_pkg(VALID_FIELDS, VALID_AC)) == []


def test_optional_external_systems_list():
    fields = dict(VALID_FIELDS, external_systems=["MLS", "Zillow"])
    assert profiles.validate_profile(_pkg(fields, VALID_AC)) == []
    bad = dict(VALID_FIELDS, external_systems="MLS")
    errs = profiles.validate_profile(_pkg(bad, VALID_AC))
    assert "profile_fields.external_systems: expected a list, got str" in errs


def test_ci_tag_is_not_in_this_profiles_vocabulary():
    bad = [dict(VALID_AC[0], evidence="ci: something automated")]
    errs = profiles.validate_profile(_pkg(VALID_FIELDS, bad))
    assert any("does not start with a recognized producer tag" in e for e in errs)


def test_observation_tag_maps_to_observation_type():
    ac = [
        dict(
            VALID_AC[0],
            evidence="observation: post-launch signals recorded",
            evidence_type="observation",
            approver="role:verifier",
        )
    ]
    assert profiles.validate_profile(_pkg(VALID_FIELDS, ac)) == []


def test_missing_owner_fails():
    errs = profiles.validate_profile(_pkg({"operating_procedure": "x"}, VALID_AC))
    assert "profile_fields.owner: missing required key" in errs


def test_new_prefixes_are_known():
    assert {"external:", "observation:"} <= profiles.KNOWN_EVIDENCE_PREFIXES
