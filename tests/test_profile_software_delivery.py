"""Task 2: the software-delivery profile — profile_fields schema + evidence-tag/
evidence_type consistency checks (WS-2.2 spec §3)."""

from pathlib import Path

import yaml

from intent_packages.profiles import software_delivery
from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.validate import validate_package

PACKAGES_DIR = Path(__file__).resolve().parents[1] / "packages"


def _package_dirs() -> list[Path]:
    return sorted(p for p in PACKAGES_DIR.iterdir() if (p / "package.yaml").is_file())


def _load(pkg_dir: Path) -> dict:
    return yaml.safe_load((pkg_dir / "package.yaml").read_text(encoding="utf-8"))


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
    assert any("profile_fields.required_checks[1]" in e and "non-empty" in e for e in errs)


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
    assert any("acceptance[0].evidence" in e and "recognized producer tag" in e for e in errs)


def test_each_valid_tag_is_accepted(software_delivery_package, edit_yaml):
    # One acceptance item per tag, each evidence_type matched correctly.
    tags_and_types = [
        ("ci: validate.yml passes", "automated_check"),
        ("gate: Gate A passed", "automated_check"),
        ("scan: no BLOCK findings", "automated_test"),
        ("review: /code-review approved", "human_review"),
        ("health: /api/health 200 after deploy", "automated_test"),
        ("human: devon reviews and approves", "human_review"),
    ]
    items = [
        {
            "id": f"AC-{i + 1:03d}",
            "condition": "x",
            "evidence_type": etype,
            "evidence": evidence,
            "approver": "devon" if etype == "human_review" else "policy",
        }
        for i, (evidence, etype) in enumerate(tags_and_types)
    ]
    edit_yaml(software_delivery_package, "package.yaml", set_key=("acceptance", items))
    assert validate_package(software_delivery_package) == []


def test_tag_evidence_type_mismatch_is_rejected(software_delivery_package, edit_yaml):
    # "ci:" requires automated_check, not human_review. approver stays "policy"
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


# --- the superseded tag map (WS-P2.36) -------------------------------------------------
#
# ci:/gate: now require automated_check. Twelve already-approved revisions declared
# automated_test under the previous map and cannot be corrected -- editing evidence_type
# invalidates the lineage approval hashed over it. They are validated against the map they
# were authored under. These tests keep that exemption honest: it must stay minimal, it must
# stay pinned to packages that really exist, and it must never widen to new authoring.


def test_ci_and_gate_require_automated_check_for_new_packages(software_delivery_package, edit_yaml):
    """The defect this closed: automated_test made the observed-check lane unreachable."""
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence_type"), "automated_test"),
    )
    errs = validate_package(software_delivery_package)
    assert any("acceptance[0].evidence_type" in e and "automated_check" in e for e in errs), errs


def test_every_superseded_revision_is_a_package_on_disk():
    """Self-retiring: an entry whose package or revision is gone must be deleted, not left."""
    on_disk = {
        (pkg["package_id"], pkg["revision"])
        for pkg in (_load(d) for d in _package_dirs())
        if pkg.get("profile") == "software-delivery"
    }
    stale = software_delivery.SUPERSEDED_MAP_REVISIONS - on_disk
    assert stale == set(), f"delete these superseded entries; they are no longer on disk: {stale}"


def test_every_superseded_revision_still_needs_the_exemption():
    """No entry may be carried that would pass under the canonical map anyway."""
    unnecessary = set()
    for d in _package_dirs():
        pkg = _load(d)
        key = (pkg.get("package_id"), pkg.get("revision"))
        if key not in software_delivery.SUPERSEDED_MAP_REVISIONS:
            continue
        if not check_evidence_tags(pkg, software_delivery.TAG_TO_EVIDENCE_TYPE):
            unnecessary.add(key)
    assert unnecessary == set(), f"these now pass the canonical map; drop them: {unnecessary}"


def test_the_exemption_covers_every_package_that_needs_it():
    """The complement of the two tests above: nothing on disk is left failing."""
    failing = set()
    for d in _package_dirs():
        pkg = _load(d)
        if pkg.get("profile") != "software-delivery":
            continue
        if software_delivery.validate(pkg):
            failing.add((pkg.get("package_id"), pkg.get("revision")))
    assert failing == set(), f"unlisted packages fail the canonical map: {failing}"


def test_a_new_revision_of_an_exempted_package_does_not_inherit_the_exemption():
    """Keyed on (package_id, revision), never package_id alone.

    A new revision is fresh authoring with its own human approval, so it can and must adopt
    the canonical map. Inheriting would let a package keep the unreachable type forever.
    """
    package_id, revision = sorted(software_delivery.SUPERSEDED_MAP_REVISIONS)[0]
    pkg = next(
        p
        for p in (_load(d) for d in _package_dirs())
        if (p.get("package_id"), p.get("revision")) == (package_id, revision)
    )
    assert software_delivery.validate(pkg) == []

    pkg["revision"] = revision + 1
    assert software_delivery.validate(pkg), (
        f"revision {revision + 1} of {package_id!r} inherited the exemption; "
        "the set must be keyed on (package_id, revision)"
    )
