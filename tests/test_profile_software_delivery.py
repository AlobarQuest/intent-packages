"""Task 2: the software-delivery profile — profile_fields schema + evidence-tag/
evidence_type consistency checks (WS-2.2 spec §3)."""
from intent_packages.validate import validate_package


def test_valid_software_delivery_package_has_no_errors(software_delivery_package):
    assert validate_package(software_delivery_package) == []


def test_missing_profile_fields_is_rejected(software_delivery_package, drop_key):
    drop_key(software_delivery_package, "package.yaml", "profile_fields")
    errs = validate_package(software_delivery_package)
    assert any("profile_fields" in e and "missing" in e for e in errs)


def test_profile_fields_unknown_key_is_rejected(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("profile_fields", "bogus_key"), "x"),
    )
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.bogus_key" in e and "unknown key" in e for e in errs)


def test_profile_fields_missing_repo_is_rejected(software_delivery_package, drop_key):
    drop_key(software_delivery_package, "package.yaml", "profile_fields", "repo")
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.repo" in e and "missing" in e for e in errs)


def test_profile_fields_repo_must_be_non_empty(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package, "package.yaml", set_nested=(("profile_fields", "repo"), "")
    )
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.repo" in e and "non-empty" in e for e in errs)


def test_profile_fields_deploy_target_may_be_null(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("profile_fields", "deploy_target"), None),
    )
    assert validate_package(software_delivery_package) == []


def test_profile_fields_required_checks_must_be_non_empty_list(
    software_delivery_package, edit_yaml
):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("profile_fields", "required_checks"), []),
    )
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.required_checks" in e and "non-empty" in e for e in errs)


def test_profile_fields_rollback_plan_must_be_non_empty(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("profile_fields", "rollback_plan"), ""),
    )
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.rollback_plan" in e and "non-empty" in e for e in errs)


def test_required_checks_element_must_be_non_empty_string(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("profile_fields", "required_checks"), ["ci:validate.yml", "  "]),
    )
    errs = validate_package(software_delivery_package)
    assert any(
        "profile_fields.required_checks[1]" in e and "non-empty" in e for e in errs
    )


def test_profile_fields_wrong_type_is_not_mislabeled_as_missing(
    software_delivery_package, edit_yaml
):
    edit_yaml(software_delivery_package, "package.yaml", set_key=("profile_fields", []))
    errs = validate_package(software_delivery_package)
    assert any("profile_fields" in e and "expected a mapping" in e for e in errs)
    assert not any("profile_fields" in e and "missing required key" in e for e in errs)


def test_evidence_without_a_recognized_tag_is_rejected(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence"), "no tag here at all"),
    )
    errs = validate_package(software_delivery_package)
    assert any(
        "acceptance[0].evidence" in e and "recognized producer tag" in e for e in errs
    )


def test_each_valid_tag_is_accepted(software_delivery_package, edit_yaml):
    # One acceptance item per tag, each evidence_type matched correctly.
    tags_and_types = [
        ("ci: validate.yml passes", "automated_test"),
        ("gate: Gate A passed", "automated_test"),
        ("scan: no BLOCK findings", "automated_test"),
        ("review: /code-review approved", "automated_test"),
        ("health: /api/health 200 after deploy", "automated_test"),
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
    edit_yaml(software_delivery_package, "package.yaml", set_key=("acceptance", items))
    assert validate_package(software_delivery_package) == []


def test_tag_evidence_type_mismatch_is_rejected(software_delivery_package, edit_yaml):
    # "ci:" requires automated_test, not human_review. approver stays "policy"
    # (legal regardless of evidence_type per check A) so this test isolates
    # the tag/evidence_type check alone.
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence_type"), "human_review"),
    )
    errs = validate_package(software_delivery_package)
    assert any(
        "acceptance[0].evidence_type" in e and "ci:" in e and "human_review" in e for e in errs
    )
