"""`create-rotation`: revision 1 of a standing rotation package the rotation proposer rendered.

Each fixture is the orchestrator's generator output for an example credential, held
byte-identical in both repositories (orchestrator `tests/rotation_proposer/test_generate.py`),
so a change to what the generator renders must still validate here. Besides the rotation, there
is an issue package for each class with an issue plan (ADR-0055 amendment 19): a lane
credential's first value, with no retire and no confirm-dead criterion.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from intent_packages import lineage as ln
from intent_packages.canonical import package_hash
from intent_packages.cli import main
from intent_packages.loader import load_package
from intent_packages.operations import do_transition
from intent_packages.validate import validate_package

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "rotation_package_generated.json"
# The orchestrator's issue fixtures at 74e6f19 (#631), pinned so a one-sided edit fails here.
ISSUE_FIXTURE_SHA256 = {
    "rotation_package_issue_bws-lane-token.json": (
        "1aaae6bd72a58095b5d7dca0aa8a6c2a35aa80f42ffb2e77202c9b1bcd9a2b65"
    ),
    "rotation_package_issue_healthchecks-ping-url.json": (
        "f2f086388eb8881b999af7e54c4a6b5272db0bca1e23e77d626286c0e4b697d6"
    ),
}
RENDERED = [FIXTURE, *(FIXTURES / name for name in ISSUE_FIXTURE_SHA256)]
NOW = "2026-10-28T12:00:00Z"


class StubEmitter:
    def emit(self, action, ref, evidence):
        return "evt-create-rotation"


def _source(tmp_path: Path, **changes: object) -> Path:
    package = {**json.loads(FIXTURE.read_text(encoding="utf-8")), **changes}
    path = tmp_path / "rendered.json"
    path.write_text(json.dumps(package), encoding="utf-8")
    return path


@pytest.mark.parametrize("name", sorted(ISSUE_FIXTURE_SHA256))
def test_the_issue_fixture_is_the_orchestrator_s(name) -> None:
    """A one-sided edit here means the orchestrator's copy has silently drifted."""
    digest = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
    assert digest == ISSUE_FIXTURE_SHA256[name]


@pytest.mark.parametrize("fixture", RENDERED, ids=lambda path: path.stem)
def test_the_rendered_package_is_written_as_a_valid_draft(tmp_path, capsys, fixture) -> None:
    out = tmp_path / "packages"
    assert main(["create-rotation", str(fixture), "--out", str(out)]) == 0

    rendered = json.loads(fixture.read_text(encoding="utf-8"))
    pkg_dir = out / rendered["package_id"]
    assert capsys.readouterr().out.strip() == str(pkg_dir)
    assert validate_package(pkg_dir) == []
    package = load_package(pkg_dir)
    assert package == rendered
    lineage = ln.read(pkg_dir)
    assert lineage["current_state"] == "draft"
    assert lineage["revisions"][0]["hash"] == package_hash(package)
    assert lineage["revisions"][0]["author"] == "rotation-proposer"


@pytest.mark.parametrize("fixture", RENDERED, ids=lambda path: path.stem)
def test_it_goes_to_review_for_a_named_human(tmp_path, fixture) -> None:
    out = tmp_path / "packages"
    assert main(["create-rotation", str(fixture), "--out", str(out)]) == 0
    pkg_dir = out / json.loads(fixture.read_text(encoding="utf-8"))["package_id"]
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
