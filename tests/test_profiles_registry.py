"""WS-P2.10: the unified DeliveryProfile registry. Existing profiles are
wrapped, not changed — their validation output must be byte-identical (the
Task-1 regression harness enforces that against all 19 real packages; this
file covers the registry mechanics and the shared forbidden-type check)."""

import pytest

from intent_packages import profiles
from intent_packages.profiles import base
from intent_packages.profiles._evidence_tags import check_evidence_tags


def test_registry_values_are_delivery_profiles():
    assert set(profiles.PROFILES) >= {"software-delivery", "infrastructure-change"}
    for name, profile in profiles.PROFILES.items():
        assert isinstance(profile, base.DeliveryProfile)
        assert profile.name == name


def test_wrapped_existing_profiles_forbid_nothing():
    assert profiles.PROFILES["software-delivery"].forbidden_evidence_types == frozenset()
    assert profiles.PROFILES["infrastructure-change"].forbidden_evidence_types == frozenset()


def test_wrapped_profile_delegates_to_original_validator():
    # A software-delivery package missing profile_fields must produce the same
    # error the pre-unification validator produced.
    errs = profiles.validate_profile({"profile": "software-delivery"})
    assert "profile_fields: missing required key" in errs


def test_forbidden_check_rejects_named_types():
    pkg = {
        "acceptance": [
            {"id": "AC-001", "evidence_type": "automated_test", "evidence": "ci: x"},
            {"id": "AC-002", "evidence_type": "automated_check", "evidence": "ci: y"},
        ]
    }
    errs = base.check_forbidden_evidence_types(pkg, frozenset({"automated_test"}))
    assert len(errs) == 1
    assert errs[0].startswith("acceptance[0].evidence_type:")
    assert "judgment_required" in errs[0]


def test_forbidden_check_empty_set_is_noop():
    pkg = {"acceptance": [{"evidence_type": "automated_test"}]}
    assert base.check_forbidden_evidence_types(pkg, frozenset()) == []


def test_factory_executable_profiles_match_routing_change_classes():
    # A profile with a change_class REQUIRES a routing row, and every routing
    # row must belong to a registered factory-executable profile — the
    # design's "shipping a new factory-executable profile requires adding its
    # routing row in the same change", enforced instead of remembered.
    from intent_packages import routing

    declared = {p.change_class for p in profiles.PROFILES.values() if p.change_class is not None}
    assert declared == set(routing.load_policy().change_classes)


def test_no_registered_profile_is_a_silent_noop():
    # A reporting/validation obligation that can be switched off is one that
    # will be: every registered profile must actually check something.
    for name, profile in profiles.PROFILES.items():
        assert profile.validate is not None or profile.forbidden_evidence_types, name


def test_validate_profile_applies_profile_forbid_set(monkeypatch):
    strict = base.DeliveryProfile(
        name="strict-profile", forbidden_evidence_types=frozenset({"automated_test"})
    )
    monkeypatch.setitem(profiles.PROFILES, "strict-profile", strict)
    pkg = {
        "profile": "strict-profile",
        "acceptance": [{"id": "AC-001", "evidence_type": "automated_test", "evidence": "e"}],
    }
    errs = profiles.validate_profile(pkg)
    assert any("forbidden by this profile" in e for e in errs)


def test_every_factory_executable_profile_declares_enrichment():
    """A profile the factory can execute must say what its workers are told.

    An absent spec is indistinguishable from "we forgot", which is the dead-config
    shape this portfolio has paid for before. Empty content is fine; absent is not.
    """
    for profile in profiles.PROFILES.values():
        if profile.change_class is None:
            continue
        assert profile.enrichment is not None, f"{profile.name} declares no EnrichmentSpec"
        assert isinstance(profile.enrichment, profiles.EnrichmentSpec)


def test_software_delivery_pulls_the_error_logging_road():
    spec = profiles.PROFILES["software-delivery"].enrichment
    assert spec is not None
    assert spec.code_road_slugs == ("error-logging",)
    assert spec.infra_min_authority == "required"


def test_dependency_update_is_enriched_but_empty_of_code_roads():
    """Empty by CONTENT, not absent. Code Brain holds nothing for this class yet."""
    spec = profiles.PROFILES["dependency-update"].enrichment
    assert spec is not None
    assert spec.code_road_slugs == ()
    assert spec.infra_min_authority == "required"


# --- check_evidence_tags' matching rule, across every registered profile's tag map --------
#
# _evidence_tags.py's docstring states the rule as "case-sensitive prefix (colon required)".
# These tests lock the three edges of that rule that are easy to get backwards under a refactor:
# an uppercased or mixed-case tag is unrecognized rather than folded to lowercase, the colon need
# not be followed by a space (both forms are accepted), and leading whitespace before the tag is
# never skipped. Parametrized over every (profile, tag) pair on the registry, not one profile's
# map, so a future profile's tags are covered automatically.

_PROFILE_TAG_CASES = [
    pytest.param(profile.name, tag, evidence_type, id=f"{profile.name}:{tag}")
    for profile in profiles.PROFILES.values()
    for tag, evidence_type in profile.tag_to_evidence_type.items()
]


def _evidence_item(evidence: str, evidence_type: str) -> dict:
    return {
        "id": "AC-001",
        "condition": "x",
        "evidence_type": evidence_type,
        "evidence": evidence,
        "approver": "policy",
    }


@pytest.mark.parametrize("profile_name, tag, evidence_type", _PROFILE_TAG_CASES)
def test_unspaced_tag_is_accepted(profile_name, tag, evidence_type):
    """The colon need not be followed by a space."""
    tag_map = dict(profiles.PROFILES[profile_name].tag_to_evidence_type)
    pkg = {"acceptance": [_evidence_item(f"{tag}something happened", evidence_type)]}
    assert check_evidence_tags(pkg, tag_map) == []


@pytest.mark.parametrize("profile_name, tag, evidence_type", _PROFILE_TAG_CASES)
def test_spaced_tag_is_accepted(profile_name, tag, evidence_type):
    """A space after the colon is also accepted -- both forms are legal."""
    tag_map = dict(profiles.PROFILES[profile_name].tag_to_evidence_type)
    pkg = {"acceptance": [_evidence_item(f"{tag} something happened", evidence_type)]}
    assert check_evidence_tags(pkg, tag_map) == []


@pytest.mark.parametrize("profile_name, tag, evidence_type", _PROFILE_TAG_CASES)
def test_uppercased_tag_is_rejected_as_unrecognized(profile_name, tag, evidence_type):
    """Matching is case-sensitive: an uppercased tag matches no producer tag at all,
    rather than being folded onto its lowercase form."""
    tag_map = dict(profiles.PROFILES[profile_name].tag_to_evidence_type)
    pkg = {"acceptance": [_evidence_item(f"{tag.upper()}something happened", evidence_type)]}
    errs = check_evidence_tags(pkg, tag_map)
    assert any("recognized producer tag" in e for e in errs), errs


@pytest.mark.parametrize("profile_name, tag, evidence_type", _PROFILE_TAG_CASES)
def test_mixed_case_tag_is_rejected_as_unrecognized(profile_name, tag, evidence_type):
    """Same rule, a milder mutation: only the tag's first letter capitalized."""
    tag_map = dict(profiles.PROFILES[profile_name].tag_to_evidence_type)
    mixed = tag[0].upper() + tag[1:]
    pkg = {"acceptance": [_evidence_item(f"{mixed}something happened", evidence_type)]}
    errs = check_evidence_tags(pkg, tag_map)
    assert any("recognized producer tag" in e for e in errs), errs


@pytest.mark.parametrize("profile_name, tag, evidence_type", _PROFILE_TAG_CASES)
def test_leading_whitespace_before_tag_is_rejected(profile_name, tag, evidence_type):
    """A tag is recognized only as a prefix of the evidence string; leading
    whitespace before it is not skipped."""
    tag_map = dict(profiles.PROFILES[profile_name].tag_to_evidence_type)
    pkg = {"acceptance": [_evidence_item(f" {tag}something happened", evidence_type)]}
    errs = check_evidence_tags(pkg, tag_map)
    assert any("recognized producer tag" in e for e in errs), errs
