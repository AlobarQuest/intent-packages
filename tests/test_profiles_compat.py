"""Task 4: AC-002 — the universal envelope is provably unchanged by the profiles
module. A universal-only package (no `profile` key) must validate identically and
hash identically to how it did before WS-2.2 landed."""

from intent_packages import canonical, loader, profiles
from intent_packages.validate import validate_package

# Locked regression value: the sha256(JCS(intent_core)) of the exact
# `_VALID_PACKAGE_YAML` fixture in conftest.py, computed before any WS-2.2 code
# existed (verified 2026-07-04, pre-Task-1). If this ever changes, something
# touched the universal envelope, the hash algorithm, or the fixture — all
# three are AC-002 violations.
_LOCKED_VALID_PACKAGE_HASH = "d49794b97c1b930de2150fa7258f0a806df586d9d4c73ed401069d9ba65e7c77"


def test_universal_only_package_is_unaffected_by_check_p(valid_package):
    pkg = loader.load_package(valid_package)
    assert profiles.validate_profile(pkg) == []


def test_universal_only_package_still_validates_clean(valid_package):
    assert validate_package(valid_package) == []


def test_universal_only_package_hash_is_locked(valid_package):
    pkg = loader.load_package(valid_package)
    assert canonical.package_hash(pkg) == _LOCKED_VALID_PACKAGE_HASH
