"""The archive holds exactly the settled packages, and nothing drops out of verification."""

from pathlib import Path

import pytest
import yaml

from intent_packages import layout, lifecycle


def _states(pkg_dir: Path) -> tuple[str, str]:
    package = yaml.safe_load((pkg_dir / "package.yaml").read_text(encoding="utf-8"))
    lineage = yaml.safe_load((pkg_dir / "lineage.yaml").read_text(encoding="utf-8"))
    return package["status"], lineage["current_state"]


@pytest.mark.parametrize("pkg_dir", layout.archived_package_dirs(), ids=lambda p: p.name)
def test_every_archived_package_is_settled(pkg_dir):
    status, current_state = _states(pkg_dir)
    assert status == current_state
    assert status in lifecycle.TERMINAL


@pytest.mark.parametrize("pkg_dir", layout.active_package_dirs(), ids=lambda p: p.name)
def test_no_settled_package_is_left_in_packages(pkg_dir):
    """A terminal package in packages/ is history sitting where work is looked for. Move it:
    `git mv packages/<id> archive/<id>` -- its hash and approval travel with it."""
    status, current_state = _states(pkg_dir)
    assert status not in lifecycle.TERMINAL, f"{pkg_dir.name} is {status}; archive it"
    assert current_state not in lifecycle.TERMINAL


def test_a_package_id_lives_in_one_place():
    active = {p.name for p in layout.active_package_dirs()}
    archived = {p.name for p in layout.archived_package_dirs()}
    assert active and archived
    assert not active & archived


def test_all_package_dirs_is_both_directories(tmp_path):
    for base, name in (("packages", "live"), ("archive", "settled"), ("archive", "stray")):
        (tmp_path / base / name).mkdir(parents=True)
    for base, name in (("packages", "live"), ("archive", "settled")):
        (tmp_path / base / name / "package.yaml").write_text("{}\n")

    assert [p.name for p in layout.all_package_dirs(tmp_path)] == ["live", "settled"]
    assert layout.all_package_dirs(tmp_path / "missing") == []
