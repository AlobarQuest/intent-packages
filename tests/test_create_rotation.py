"""`create-rotation`: revision 1 of a standing rotation package the rotation proposer rendered.

The fixture is the orchestrator's generator output for an example credential, held
byte-identical in both repositories (orchestrator `tests/rotation_proposer/test_generate.py`),
so a change to what the generator renders must still validate here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intent_packages import lineage as ln
from intent_packages.canonical import package_hash
from intent_packages.cli import main
from intent_packages.loader import load_package
from intent_packages.operations import do_transition
from intent_packages.validate import validate_package

FIXTURE = Path(__file__).parent / "fixtures" / "rotation_package_generated.json"
NOW = "2026-10-28T12:00:00Z"


class StubEmitter:
    def emit(self, action, ref, evidence):
        return "evt-create-rotation"


def _source(tmp_path: Path, **changes: object) -> Path:
    package = {**json.loads(FIXTURE.read_text(encoding="utf-8")), **changes}
    path = tmp_path / "rendered.json"
    path.write_text(json.dumps(package), encoding="utf-8")
    return path


def test_the_rendered_package_is_written_as_a_valid_draft(tmp_path, capsys) -> None:
    out = tmp_path / "packages"
    assert main(["create-rotation", str(_source(tmp_path)), "--out", str(out)]) == 0

    pkg_dir = out / "rotation-example-pat"
    assert capsys.readouterr().out.strip() == str(pkg_dir)
    assert validate_package(pkg_dir) == []
    package = load_package(pkg_dir)
    assert package == json.loads(FIXTURE.read_text(encoding="utf-8"))
    lineage = ln.read(pkg_dir)
    assert lineage["current_state"] == "draft"
    assert lineage["revisions"][0]["hash"] == package_hash(package)
    assert lineage["revisions"][0]["author"] == "rotation-proposer"


def test_it_goes_to_review_for_a_named_human(tmp_path) -> None:
    out = tmp_path / "packages"
    assert main(["create-rotation", str(_source(tmp_path)), "--out", str(out)]) == 0
    pkg_dir = out / "rotation-example-pat"
    do_transition(pkg_dir, "ready_for_review", emitter=StubEmitter(), now=NOW)
    assert ln.read(pkg_dir)["current_state"] == "ready_for_review"


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "ready_for_review"},
        {"revision": 2},
        {"package_id": "rotation-another"},
        {"profile": "dependency-update"},
    ],
)
def test_anything_but_a_draft_revision_1_named_for_its_credential_is_refused(
    tmp_path, capsys, changes
) -> None:
    out = tmp_path / "packages"
    assert main(["create-rotation", str(_source(tmp_path, **changes)), "--out", str(out)]) == 1
    assert "not a draft revision 1" in capsys.readouterr().err
    assert not out.exists()


def test_an_existing_package_is_never_overwritten(tmp_path, capsys) -> None:
    out = tmp_path / "packages"
    source = _source(tmp_path)
    assert main(["create-rotation", str(source), "--out", str(out)]) == 0
    before = (out / "rotation-example-pat" / "package.yaml").read_text(encoding="utf-8")
    assert main(["create-rotation", str(source), "--out", str(out)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert (out / "rotation-example-pat" / "package.yaml").read_text(encoding="utf-8") == before


def test_a_package_that_fails_validation_writes_nothing(tmp_path) -> None:
    out = tmp_path / "packages"
    source = _source(tmp_path, outcome={"what": "only half an outcome"})
    assert main(["create-rotation", str(source), "--out", str(out)]) == 1
    assert not (out / "rotation-example-pat").exists()
