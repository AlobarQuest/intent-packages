import json
from pathlib import Path

import yaml

from intent_packages.factory import scaffolds
from intent_packages.validate import validate_package

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "readiness" / "gap-repo.v1.json"


def _fixture_doc():
    return json.loads(FIXTURE.read_text())


def test_fixture_is_live_captured_v1():
    doc = _fixture_doc()
    assert doc["schema"] == "portfolio-readiness/v1"
    assert doc["remediation_queue"], "fixture must carry a real queue"


def test_wrong_schema_string_fails_closed_naming_both(tmp_path, capsys):
    doc = _fixture_doc()
    doc["schema"] = "portfolio-readiness/v2"
    path = tmp_path / "readiness.json"
    path.write_text(json.dumps(doc))
    rc = scaffolds.create_from_readiness(str(path), "", str(tmp_path / "out"))
    assert rc == 1
    err = capsys.readouterr().err
    assert "portfolio-readiness/v1" in err
    assert "portfolio-readiness/v2" in err


def test_empty_queue_refused(tmp_path, capsys):
    doc = _fixture_doc()
    doc["remediation_queue"] = []
    path = tmp_path / "readiness.json"
    path.write_text(json.dumps(doc))
    rc = scaffolds.create_from_readiness(str(path), "", str(tmp_path / "out"))
    assert rc == 1
    assert "empty" in capsys.readouterr().err


def test_unreadable_file_fails_closed(tmp_path, capsys):
    path = tmp_path / "readiness.json"
    path.write_text("{not json")
    rc = scaffolds.create_from_readiness(str(path), "", str(tmp_path / "out"))
    assert rc == 1


def test_happy_path_scaffolds_one_validating_package(tmp_path, capsys):
    out = tmp_path / "out"
    rc = scaffolds.create_from_readiness(str(FIXTURE), "", str(out))
    assert rc == 0
    doc = _fixture_doc()
    pkg_dir = out / f"{doc['repo']}-onboarding-remediation"
    assert pkg_dir.is_dir()
    assert validate_package(pkg_dir) == []
    pkg = yaml.safe_load((pkg_dir / "package.yaml").read_text())
    assert pkg["profile"] == "maintenance-remediation"
    queue = doc["remediation_queue"]
    assert len(pkg["acceptance"]) == len(queue)
    for item, ac in zip(queue, pkg["acceptance"], strict=True):
        assert item["check"] in ac["condition"]
        assert ac["evidence_type"] == "human_review"
    assert pkg["profile_fields"]["repo"] == doc["repo"]
    assert "portfolio-readiness/v1" in pkg["profile_fields"]["remediation_source"]


def test_explicit_name_overrides_derived(tmp_path):
    out = tmp_path / "out"
    rc = scaffolds.create_from_readiness(str(FIXTURE), "my-remediation", str(out))
    assert rc == 0
    assert (out / "my-remediation").is_dir()
