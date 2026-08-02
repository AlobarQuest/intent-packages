import pytest

from intent_packages.validate import PRE_APPROVAL_STATES, validate_package


def test_valid_package_has_no_errors(valid_package):
    assert validate_package(valid_package) == []


def test_float_is_rejected(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_raw="quality_accessibility: 1.5")
    errs = validate_package(valid_package)
    assert any("float" in e.lower() for e in errs)


def test_acceptance_missing_approver(valid_package, drop_key):
    drop_key(valid_package, "package.yaml", "acceptance", 0, "approver")
    assert any("approver" in e for e in validate_package(valid_package))


def test_external_approver_only_for_attestation(valid_package, edit_yaml):
    # evidence_type stays automated_test; external: is only legal for
    # external_attestation/human_review, so this must fail.
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "approver"), "external:seller"),
    )
    errs = validate_package(valid_package)
    assert any("external" in e for e in errs)


def test_external_approver_ok_for_human_review(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "approver"), "external:seller"),
    )
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence_type"), "human_review"),
    )
    errs = validate_package(valid_package)
    assert not any("external" in e for e in errs)


def test_unknown_top_level_key(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_raw="bogus_key: 1")
    assert any("unknown" in e.lower() for e in validate_package(valid_package))


def test_package_id_must_match_dir(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("package_id", "wrong"))
    assert any("package_id" in e for e in validate_package(valid_package))


def test_source_missing_trust_is_rejected(valid_package, drop_key):
    drop_key(valid_package, "package.yaml", "sources", 0, "trust")
    assert any("trust" in e for e in validate_package(valid_package))


def test_source_invalid_trust_value_is_rejected(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("sources", 0, "trust"), "bogus_trust_value"),
    )
    assert any("trust" in e for e in validate_package(valid_package))


def test_acceptance_bad_id_format_is_rejected(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_nested=(("acceptance", 0, "id"), "AC-1"))
    errs = validate_package(valid_package)
    assert any("id" in e and "AC-" in e for e in errs)


def test_acceptance_duplicate_id_is_rejected(valid_package, edit_yaml):
    data_path_value = [
        {
            "id": "AC-001",
            "condition": "duplicate of the first item",
            "evidence_type": "automated_test",
            "evidence": "duplicate evidence",
            "approver": "policy",
        },
        {
            "id": "AC-001",
            "condition": "validate returns zero errors on this package",
            "evidence_type": "automated_test",
            "evidence": "pytest test_validate_structure.py::test_valid_package_has_no_errors",
            "approver": "policy",
        },
    ]
    edit_yaml(valid_package, "package.yaml", set_key=("acceptance", data_path_value))
    assert any("duplicate" in e.lower() for e in validate_package(valid_package))


def test_acceptance_bad_evidence_type_is_rejected(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence_type"), "bogus_type"),
    )
    assert any("evidence_type" in e for e in validate_package(valid_package))


def test_registered_agent_approver_is_accepted(
    valid_package, edit_yaml, fake_registry, monkeypatch
):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "approver"), "devon"),
    )
    assert validate_package(valid_package) == []


def test_profile_fields_non_str_key_is_rejected_with_field_path(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_raw="profile_fields:\n  1: bad\n")
    errs = validate_package(valid_package)
    assert any("profile_fields" in e for e in errs)


def test_profile_fields_yaml_set_value_is_rejected_with_field_path(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "package.yaml",
        set_raw="profile_fields:\n  bad_field: !!set {a: null, b: null}\n",
    )
    errs = validate_package(valid_package)
    assert any("profile_fields.bad_field" in e for e in errs)


def test_unregistered_agent_approver_is_rejected(
    valid_package, edit_yaml, fake_registry, monkeypatch
):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "approver"), "nobody-xyz"),
    )
    errs = validate_package(valid_package)
    assert any("approver" in e and "registered" in e for e in errs)


def test_reach_is_an_accepted_top_level_key(valid_package, edit_yaml):
    # WS-P2.18 / orchestrator ADR-0009. Without this, a package declaring its reach fails
    # validation as an unknown key and the field is undeclarable -- decoration, not a contract.
    edit_yaml(valid_package, "package.yaml", set_key=("reach", ["source_repository"]))
    assert validate_package(valid_package) == []


def test_a_membership_error_in_reach_is_left_to_the_orchestrator(valid_package, edit_yaml):
    # This repo checks SHAPE only. Enumerating the members here would be a second copy of a
    # vocabulary whose single source of truth is the orchestrator's `reach_vocabulary`.
    edit_yaml(valid_package, "package.yaml", set_key=("reach", ["nowhere_in_particular"]))
    assert validate_package(valid_package) == []


def test_a_misshapen_reach_is_reported_here(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("reach", "source_repository"))
    assert any("reach:" in e for e in validate_package(valid_package))


def test_an_empty_reach_list_is_reported_here(valid_package, edit_yaml):
    # An empty list would read as "reaches nothing", the most permissive claim available, and it
    # is a different mistake from omitting the key -- which is now its own error below.
    edit_yaml(valid_package, "package.yaml", set_key=("reach", []))
    assert any("reach:" in e for e in validate_package(valid_package))


def test_a_blank_reach_entry_is_reported_here(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("reach", ["  "]))
    assert any("reach[0]:" in e for e in validate_package(valid_package))


# WS-P2.18 Increment 4: reach stops being optional, at the boundary a package cannot go round.


def test_a_package_still_being_authored_must_declare_reach(valid_package, drop_key):
    # The fixture is `status: draft`, which is where every package starts. Failing here is what
    # makes the requirement unmissable: the file is still editable, and after approval it is not,
    # because the lineage approval is hashed over it.
    drop_key(valid_package, "package.yaml", "reach")

    errors = validate_package(valid_package)

    assert any("reach: missing required key" in e for e in errors)


@pytest.mark.parametrize("status", sorted(PRE_APPROVAL_STATES))
def test_every_pre_approval_state_requires_it(valid_package, edit_yaml, drop_key, status):
    drop_key(valid_package, "package.yaml", "reach")
    edit_yaml(valid_package, "package.yaml", set_key=("status", status))

    assert any("reach: missing required key" in e for e in validate_package(valid_package))


def test_an_already_approved_package_is_asked_for_nothing(valid_package, edit_yaml, drop_key):
    """The twenty-four packages authored before the key existed, and why they are not backfilled.

    Their YAML is hashed into a lineage approval, so editing one invalidates the approval bound to
    it -- conforming the old population would cost twenty-four fresh human approvals to satisfy a
    rule that will never be applied to it. They are exempt because they are FINISHED, not because
    they are old: a package cannot reach `approved` without passing through a state above.
    """
    drop_key(valid_package, "package.yaml", "reach")
    edit_yaml(valid_package, "package.yaml", set_key=("status", "closed"))

    assert not any("reach: missing required key" in e for e in validate_package(valid_package))
