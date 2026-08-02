import pytest
import yaml

from intent_packages.factory import scaffolds

# Every scaffold must declare what its work touches; `create` refuses without it (WS-P2.18 Increment 4).
REACH = ("source_repository",)
from intent_packages.profiles import PROFILES
from intent_packages.validate import validate_package


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_every_registered_profile_scaffolds_and_validates(profile_name, tmp_path):
    """The create-side analogue of WS-P2.10's no-silent-noop guard.

    A front door that emits an invalid package is worse than a blank page.
    """
    rc = scaffolds.create(profile_name, "scaffold-probe", str(tmp_path), reach=REACH)
    assert rc == 0
    assert validate_package(tmp_path / "scaffold-probe") == []


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_no_scaffold_declares_automated_test(profile_name, tmp_path):
    scaffolds.create(profile_name, "scaffold-probe", str(tmp_path), reach=REACH)
    document = yaml.safe_load((tmp_path / "scaffold-probe" / "package.yaml").read_text())
    assert all(item["evidence_type"] != "automated_test" for item in document["acceptance"])


def test_unregistered_profile_lists_valid_choices(tmp_path, capsys):
    rc = scaffolds.create("python-service", "probe", str(tmp_path), reach=REACH)
    assert rc == 1
    message = capsys.readouterr().err
    assert "python-service" in message
    for name in PROFILES:
        assert name in message


def test_refuses_to_overwrite(tmp_path):
    assert scaffolds.create("software-delivery", "probe", str(tmp_path), reach=REACH) == 0
    assert scaffolds.create("software-delivery", "probe", str(tmp_path), reach=REACH) == 1


def test_a_scaffold_that_fails_validation_leaves_nothing_behind(tmp_path, capsys, monkeypatch):
    """A5. `create` used to write both files to the target and validate them
    there, so a scaffold that failed its own validation was left on disk — and
    the next `create` then refused with "already exists". A failed create was not
    retryable without a manual `rm -rf`, which is the opposite of what the
    already-exists guard is for.

    Forces the failure by stubbing `validate_package` (the profiles all scaffold
    clean, which is what `test_every_registered_profile_scaffolds_and_validates`
    exists to keep true — so the only honest way to reach this branch is to make
    validation fail).
    """
    monkeypatch.setattr(scaffolds, "validate_package", lambda path: ["acceptance: broken"])

    rc = scaffolds.create("software-delivery", "probe", str(tmp_path), reach=REACH)
    assert rc == 1
    err = capsys.readouterr().err
    assert "failed validation" in err
    assert "acceptance: broken" in err
    assert not (tmp_path / "probe").exists()
    assert list(tmp_path.iterdir()) == []


def test_a_failed_create_is_retryable(tmp_path, monkeypatch):
    """The consequence that matters: after a failed create, the SAME command
    must succeed once the cause is gone — not hit "already exists"."""
    monkeypatch.setattr(scaffolds, "validate_package", lambda path: ["boom"])
    assert scaffolds.create("software-delivery", "probe", str(tmp_path), reach=REACH) == 1

    monkeypatch.undo()
    assert scaffolds.create("software-delivery", "probe", str(tmp_path), reach=REACH) == 0
    assert (tmp_path / "probe" / "package.yaml").exists()
    assert validate_package(tmp_path / "probe") == []


def test_create_makes_missing_parent_directories(tmp_path):
    """`--out` may name a directory that does not exist yet; the staging move
    must not depend on it being there already."""
    out = tmp_path / "nested" / "packages"
    assert scaffolds.create("software-delivery", "probe", str(out), reach=REACH) == 0
    assert (out / "probe" / "lineage.yaml").exists()


def test_lineage_starts_in_draft(tmp_path):
    scaffolds.create("software-delivery", "probe", str(tmp_path), reach=REACH)
    lineage = yaml.safe_load((tmp_path / "probe" / "lineage.yaml").read_text())
    assert lineage["current_state"] == "draft"
    assert lineage["approvals"] == []


def test_ac_id_semantics_are_documented_in_the_output(tmp_path):
    scaffolds.create("software-delivery", "probe", str(tmp_path), reach=REACH)
    text = (tmp_path / "probe" / "package.yaml").read_text()
    assert "database UUID" in text and "AC-001" in text


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_ac001_is_profile_derived_ac002_is_always_human_review(profile_name, tmp_path):
    """AC-002's condition ("a reviewer confirms...") describes human judgment,
    so its evidence_type must be human_review regardless of what AC-001's
    profile-derived evidence type happens to be (fix round 1)."""
    scaffolds.create(profile_name, "scaffold-probe", str(tmp_path), reach=REACH)
    document = yaml.safe_load((tmp_path / "scaffold-probe" / "package.yaml").read_text())
    ac1, ac2 = document["acceptance"]

    assert ac1["id"] == "AC-001"
    assert ac1["evidence_type"] == scaffolds._evidence_type(PROFILES[profile_name])
    assert ac1["evidence_type"] != "automated_test"

    assert ac2["id"] == "AC-002"
    assert ac2["evidence_type"] == "human_review"


def test_dependency_update_envelope_comment_precedes_authority_not_acceptance(tmp_path):
    """The envelope-discipline comment is about allowed_commands, a downstream
    work-unit authority-envelope concern that never appears in package.yaml —
    it belongs above `authority:`, not adjacent to `acceptance:` where the
    unrelated ac_id comment lives (fix round 1)."""
    scaffolds.create("dependency-update", "probe", str(tmp_path), reach=REACH)
    text = (tmp_path / "probe" / "package.yaml").read_text()

    ac_id_index = text.index("ac_id means two different things")
    acceptance_index = text.index("\nacceptance:\n")
    envelope_index = text.index("allowed_commands is an ORDERED list")
    authority_index = text.index("\nauthority:\n")

    assert ac_id_index < acceptance_index < envelope_index < authority_index

    # Not adjacent: both acceptance items sit between the two comment blocks.
    between = text[acceptance_index:envelope_index]
    assert "id: AC-001" in between
    assert "id: AC-002" in between
