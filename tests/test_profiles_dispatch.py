"""Task 1: profiles.validate_profile dispatch — unknown-profile error, no-profile
passthrough, and delegation to a registered profile's validate() function.

Uses monkeypatch.setitem on profiles.PROFILES to inject a fake validator, so this
test file has zero dependency on the real software-delivery/infrastructure-change
profiles built in Tasks 2/3.
"""
from intent_packages import profiles
from intent_packages.validate import validate_package


def test_no_profile_key_returns_no_errors():
    assert profiles.validate_profile({"title": "no profile here"}) == []


def test_profile_none_returns_no_errors():
    assert profiles.validate_profile({"profile": None}) == []


def test_unknown_profile_name_is_a_hard_error():
    errs = profiles.validate_profile({"profile": "not-a-real-profile"})
    assert len(errs) == 1
    assert "not-a-real-profile" in errs[0]
    assert "profile" in errs[0]


def test_known_profile_delegates_to_its_validator(monkeypatch):
    calls = []

    def fake_validate(package):
        calls.append(package)
        return ["fake error from the profile validator"]

    monkeypatch.setitem(profiles.PROFILES, "fake-profile", fake_validate)
    pkg = {"profile": "fake-profile", "title": "x"}

    errs = profiles.validate_profile(pkg)

    assert errs == ["fake error from the profile validator"]
    assert calls == [pkg]


def test_validate_package_still_passes_for_universal_only_package(valid_package):
    # valid_package (conftest) has no `profile` key at all — check P must be a
    # complete no-op for it (AC-003's "unaffected" guarantee, proven early).
    assert validate_package(valid_package) == []


def test_validate_package_surfaces_unknown_profile_error(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("profile", "not-a-real-profile"))
    errs = validate_package(valid_package)
    assert any("not-a-real-profile" in e for e in errs)
