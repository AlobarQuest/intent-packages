"""Task 3: the infrastructure-change profile — profile_fields schema + evidence-tag/
evidence_type consistency checks (WS-2.2 spec §4)."""

from intent_packages.validate import validate_package


def test_valid_infrastructure_change_package_has_no_errors(infrastructure_change_package):
    assert validate_package(infrastructure_change_package) == []


def test_missing_profile_fields_is_rejected(infrastructure_change_package, drop_key):
    drop_key(infrastructure_change_package, "package.yaml", "profile_fields")
    errs = validate_package(infrastructure_change_package)
    assert any("profile_fields" in e and "missing" in e for e in errs)


def test_blast_radius_must_be_a_legal_enum_value(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("profile_fields", "blast_radius"), "the-whole-internet"),
    )
    errs = validate_package(infrastructure_change_package)
    assert any("profile_fields.blast_radius" in e and "the-whole-internet" in e for e in errs)


def test_change_window_may_be_null(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("profile_fields", "change_window"), None),
    )
    assert validate_package(infrastructure_change_package) == []


def test_backup_evidence_may_be_null(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("profile_fields", "backup_evidence"), None),
    )
    assert validate_package(infrastructure_change_package) == []


def test_rollback_plan_must_be_non_empty(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("profile_fields", "rollback_plan"), ""),
    )
    errs = validate_package(infrastructure_change_package)
    assert any("profile_fields.rollback_plan" in e and "non-empty" in e for e in errs)


def test_profile_fields_wrong_type_is_not_mislabeled_as_missing(
    infrastructure_change_package, edit_yaml
):
    edit_yaml(infrastructure_change_package, "package.yaml", set_key=("profile_fields", []))
    errs = validate_package(infrastructure_change_package)
    assert any("profile_fields" in e and "expected a mapping" in e for e in errs)
    assert not any("profile_fields" in e and "missing required key" in e for e in errs)


def test_evidence_without_a_recognized_tag_is_rejected(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence"), "no tag here at all"),
    )
    errs = validate_package(infrastructure_change_package)
    assert any("acceptance[0].evidence" in e and "recognized producer tag" in e for e in errs)


def test_each_valid_tag_is_accepted(infrastructure_change_package, edit_yaml):
    tags_and_types = [
        ("health: /api/health 200 after change", "automated_test"),
        ("backup: vps-backup recipe D run 2026-07-04", "automated_test"),
        ("change-log: infra change log entry 2026-07-04", "automated_test"),
        ("human: devon reviews and approves", "human_review"),
    ]
    items = [
        {
            "id": f"AC-{i + 1:03d}",
            "condition": "x",
            "evidence_type": etype,
            "evidence": evidence,
            "approver": "policy" if etype == "automated_test" else "devon",
        }
        for i, (evidence, etype) in enumerate(tags_and_types)
    ]
    edit_yaml(infrastructure_change_package, "package.yaml", set_key=("acceptance", items))
    assert validate_package(infrastructure_change_package) == []


def test_tag_evidence_type_mismatch_is_rejected(infrastructure_change_package, edit_yaml):
    # "health:" requires automated_test, not human_review. approver stays
    # "policy" (legal regardless of evidence_type per check A) so this test
    # isolates the tag/evidence_type check alone.
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence_type"), "human_review"),
    )
    errs = validate_package(infrastructure_change_package)
    assert any(
        "acceptance[0].evidence_type" in e and "health:" in e and "human_review" in e for e in errs
    )
