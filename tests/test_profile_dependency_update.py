"""dependency-update as a declarable delivery profile (WS-P2.10): formalizes
what GAP-4 proved in production. The tooling half (pin discovery, mutators,
envelope) is unchanged and covered by tests/factory/."""

import pytest

from intent_packages import profiles
from intent_packages.profiles import dependency_update
from intent_packages.profiles.dependency_update import PinSite, build_envelope


def test_registered_with_change_class_and_tooling():
    profile = profiles.PROFILES["dependency-update"]
    assert profile.change_class == "dependency-update"
    assert profile.tooling is dependency_update.TOOLING_PROFILES
    assert set(profile.tooling) == {"npm", "pip", "uv"}
    assert profile.forbidden_evidence_types == frozenset({"automated_test"})
    assert profile.default_authority is not None
    assert profile.default_authority.budgets["max_attempts"] == 3


def _pkg(profile_fields: dict, acceptance: list) -> dict:
    return {
        "profile": "dependency-update",
        "profile_fields": profile_fields,
        "acceptance": acceptance,
    }


VALID_FIELDS = {
    "target_repo": "AlobarQuest/change-manager",
    "package": "httpx2",
    "from_version": "2.8.0",
    "to_version": "2.9.1",
}
VALID_AC = [
    {
        "id": "AC-001",
        "condition": "pin moved and named check passes",
        "evidence_type": "automated_check",
        "evidence": "ci: named check on the PR head",
        "approver": "role:verifier",
    }
]


def test_valid_package_passes():
    assert profiles.validate_profile(_pkg(VALID_FIELDS, VALID_AC)) == []


def test_missing_profile_field_fails():
    fields = {k: v for k, v in VALID_FIELDS.items() if k != "to_version"}
    errs = profiles.validate_profile(_pkg(fields, VALID_AC))
    assert "profile_fields.to_version: missing required key" in errs


def test_automated_test_is_a_validation_failure():
    bad_ac = [dict(VALID_AC[0], evidence_type="automated_test")]
    errs = profiles.validate_profile(_pkg(VALID_FIELDS, bad_ac))
    # Rejected twice, deliberately: the tag map pins ci: -> automated_check,
    # and the forbid set names automated_test explicitly.
    assert any("forbidden by this profile" in e for e in errs)


def test_unrecognized_evidence_tag_fails():
    bad_ac = [dict(VALID_AC[0], evidence="scan: not in this profile's tag map")]
    errs = profiles.validate_profile(_pkg(VALID_FIELDS, bad_ac))
    assert any("does not start with a recognized producer tag" in e for e in errs)


def test_empty_string_field_fails():
    errs = profiles.validate_profile(_pkg(dict(VALID_FIELDS, package="  "), VALID_AC))
    assert "profile_fields.package: must be a non-empty string" in errs


def test_envelope_key_set_is_the_pinned_contract():
    envelope = build_envelope(
        "AlobarQuest/x",
        "uv",
        "httpx2",
        "2.8.0",
        "2.9.1",
        {"scanner": "real"},
        [PinSite("pyproject.toml", "dependency-groups.dev", "2.8.0")],
    )
    assert set(envelope) == {
        "budgets",
        "capabilities",
        "change_class",
        "conformance",
        "constraints",
    }
    assert set(envelope["constraints"]) == {
        "allowed_commands",
        "mutation_commands",
        "target_repository",
    }
    assert envelope["constraints"]["allowed_commands"][-1] == "uv lock --check"


def test_old_registry_name_is_gone():
    with pytest.raises(AttributeError):
        dependency_update.PROFILES  # noqa: B018
