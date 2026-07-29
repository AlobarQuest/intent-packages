"""WS-P2.10 regression harness: every real package in packages/ must validate
with zero errors, and its package_hash must match the committed snapshot.

Written BEFORE any WS-P2.10 change lands, so drift introduced by the registry
unification or the walker change fails here first. If a hash mismatches, the
fix is to revert the change that caused it — never to regenerate the snapshot
(editing an approved package's YAML invalidates its lineage approvals).
"""

import json
from pathlib import Path

import pytest
import yaml

from intent_packages.canonical import package_hash
from intent_packages.validate import validate_package

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = REPO_ROOT / "packages"
SNAPSHOT_PATH = REPO_ROOT / "tests" / "fixtures" / "package_hashes.json"


def _package_dirs() -> list[Path]:
    return sorted(p for p in PACKAGES_DIR.iterdir() if (p / "package.yaml").is_file())


def _snapshot() -> dict[str, str]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_snapshot_covers_every_package_exactly():
    assert sorted(_snapshot()) == [p.name for p in _package_dirs()]


@pytest.mark.parametrize("pkg_dir", _package_dirs(), ids=lambda p: p.name)
def test_real_package_validates_clean(pkg_dir):
    assert validate_package(pkg_dir) == []


@pytest.mark.parametrize("pkg_dir", _package_dirs(), ids=lambda p: p.name)
def test_real_package_hash_matches_snapshot(pkg_dir):
    pkg = yaml.safe_load((pkg_dir / "package.yaml").read_text(encoding="utf-8"))
    assert package_hash(pkg) == _snapshot()[pkg_dir.name]
