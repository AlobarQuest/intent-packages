"""`create-standing`: a standing dependency-update package that policy can approve.

The bump proposer creates one when a failed Dependabot bump has none, then runs the
existing lifecycle (`transition --to ready_for_review`, `approve --by-policy`). These tests
drive the real CLI entry point, then that lifecycle, against what it wrote.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from intent_packages import approval_policy
from intent_packages import lineage as ln
from intent_packages.canonical import package_hash
from intent_packages.cli import main
from intent_packages.loader import load_package
from intent_packages.operations import do_approve, do_transition
from intent_packages.validate import validate_package

REPO = "AlobarQuest/example-app"
NOW = "2026-10-28T12:00:00Z"


class StubEmitter:
    def emit(self, action, ref, evidence):
        return "evt-create-standing"


def _create(out: Path, *, package: str = "zod", ecosystem: str = "npm") -> int:
    return main(
        [
            "create-standing",
            "--target-repo", REPO,
            "--package", package,
            "--ecosystem", ecosystem,
            "--from", "3.25.76",
            "--to", "4.4.3",
            "--out", str(out),
        ]
    )  # fmt: skip


def test_create_standing_writes_a_package_that_validates(tmp_path, capsys) -> None:
    assert _create(tmp_path) == 0

    pkg_dir = tmp_path / "example-app-npm-zod"
    assert capsys.readouterr().out.strip() == str(pkg_dir)
    assert validate_package(pkg_dir) == []
    package = load_package(pkg_dir)
    assert package["status"] == "draft" and package["revision"] == 1
    assert package["reach"] == ["source_repository"]
    assert package["profile_fields"] == {
        "target_repo": REPO,
        "package": "zod",
        "from_version": "3.25.76",
        "to_version": "4.4.3",
        "standing": True,
    }
    lineage = ln.read(pkg_dir)
    assert lineage["current_state"] == "draft"
    assert lineage["revisions"][0]["hash"] == package_hash(package)


def test_the_created_package_is_approvable_by_policy(
    tmp_path, monkeypatch, fake_registry, member_record
) -> None:
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    member_record(REPO)
    out = tmp_path / "packages"
    assert _create(out) == 0
    pkg_dir = out / "example-app-npm-zod"

    assert approval_policy.load_policy().refusals_for(load_package(pkg_dir)) == ()
    do_transition(pkg_dir, "ready_for_review", emitter=StubEmitter(), now=NOW)
    do_approve(
        pkg_dir,
        emitter=StubEmitter(),
        approver="policy:dependency-update@v2",
        commit="abc1234",
        now=NOW,
    )

    assert ln.read(pkg_dir)["current_state"] == "approved"


def test_create_standing_refuses_an_existing_directory(tmp_path, capsys) -> None:
    assert _create(tmp_path) == 0
    before = (tmp_path / "example-app-npm-zod" / "package.yaml").read_text(encoding="utf-8")
    capsys.readouterr()

    assert _create(tmp_path) != 0

    assert "already exists" in capsys.readouterr().err
    assert (tmp_path / "example-app-npm-zod" / "package.yaml").read_text(encoding="utf-8") == before


def test_create_standing_refuses_an_ecosystem_without_tooling(tmp_path, capsys) -> None:
    assert _create(tmp_path, ecosystem="docker") != 0

    assert "docker" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_the_created_package_has_no_human_review_criterion(tmp_path) -> None:
    assert _create(tmp_path) == 0

    acceptance = load_package(tmp_path / "example-app-npm-zod")["acceptance"]
    assert [(c["id"], c["evidence_type"], c["approver"]) for c in acceptance] == [
        ("AC-001", "automated_check", "policy")
    ]


@pytest.mark.parametrize(
    ("ecosystem", "dependency", "expected"),
    [
        ("npm", "@types/node", "example-app-npm-types-node"),
        ("pip", "Flask_Cors", "example-app-pip-flask-cors"),
        ("uv", "ruff", "example-app-uv-ruff"),
    ],
)
def test_the_package_id_is_a_safe_directory_name(tmp_path, ecosystem, dependency, expected) -> None:
    assert _create(tmp_path, package=dependency, ecosystem=ecosystem) == 0

    assert (tmp_path / expected).is_dir()
    assert validate_package(tmp_path / expected) == []
