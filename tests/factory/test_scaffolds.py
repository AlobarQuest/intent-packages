import pytest
import yaml

from intent_packages.factory import scaffolds
from intent_packages.profiles import PROFILES
from intent_packages.validate import validate_package


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_every_registered_profile_scaffolds_and_validates(profile_name, tmp_path):
    """The create-side analogue of WS-P2.10's no-silent-noop guard.

    A front door that emits an invalid package is worse than a blank page.
    """
    rc = scaffolds.create(profile_name, "scaffold-probe", str(tmp_path))
    assert rc == 0
    assert validate_package(tmp_path / "scaffold-probe") == []


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_no_scaffold_declares_automated_test(profile_name, tmp_path):
    scaffolds.create(profile_name, "scaffold-probe", str(tmp_path))
    document = yaml.safe_load((tmp_path / "scaffold-probe" / "package.yaml").read_text())
    assert all(item["evidence_type"] != "automated_test" for item in document["acceptance"])


def test_unregistered_profile_lists_valid_choices(tmp_path, capsys):
    rc = scaffolds.create("python-service", "probe", str(tmp_path))
    assert rc == 1
    message = capsys.readouterr().err
    assert "python-service" in message
    for name in PROFILES:
        assert name in message


def test_refuses_to_overwrite(tmp_path):
    assert scaffolds.create("software-delivery", "probe", str(tmp_path)) == 0
    assert scaffolds.create("software-delivery", "probe", str(tmp_path)) == 1


def test_lineage_starts_in_draft(tmp_path):
    scaffolds.create("software-delivery", "probe", str(tmp_path))
    lineage = yaml.safe_load((tmp_path / "probe" / "lineage.yaml").read_text())
    assert lineage["current_state"] == "draft"
    assert lineage["approvals"] == []


def test_ac_id_semantics_are_documented_in_the_output(tmp_path):
    scaffolds.create("software-delivery", "probe", str(tmp_path))
    text = (tmp_path / "probe" / "package.yaml").read_text()
    assert "database UUID" in text and "AC-001" in text
