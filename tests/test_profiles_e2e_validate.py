"""End-to-end validate_package coverage for the three WS-P2.10 profiles
(dependency-update, maintenance-remediation, non-software-operational).

The unit tests in tests/test_profile_dependency_update.py,
tests/test_profile_maintenance_remediation.py and
tests/test_profile_non_software_operational.py exercise `validate_profile`
(check P) in isolation, against a bare dict. They never exercise the full
`validate_package` — the universal checks (K/J/ID/TR/A/S/H/T/L) plus check P
together, against a real package.yaml + lineage.yaml pair on disk. This file
closes that gap: one test per profile, each asserting a complete,
realistically-authored package validates with zero errors end to end."""

from intent_packages.validate import validate_package


def test_dependency_update_package_validates_end_to_end(dependency_update_package):
    assert validate_package(dependency_update_package) == []


def test_maintenance_remediation_package_validates_end_to_end(maintenance_remediation_package):
    assert validate_package(maintenance_remediation_package) == []


def test_non_software_operational_package_validates_end_to_end(non_software_operational_package):
    assert validate_package(non_software_operational_package) == []
