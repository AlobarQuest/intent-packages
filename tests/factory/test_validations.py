import subprocess
from pathlib import Path

import pytest

from intent_packages.factory.validations import (
    ValidationError,
    assert_pin_sites_moved,
    assert_runner_honest,
    dry_run_mutation,
)
from intent_packages.profiles.dependency_update import PinSite


def _git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name, text in files.items():
        (repo / name).write_text(text, encoding="utf-8")
    for argv in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(["git", *argv], cwd=repo, check=True)
    return repo


# NOTE: the brief's mutator uses GNU `sed -i 's/.../.../ ' file` (no backup-suffix
# argument), which is correct for the envelope's target — a Linux hosted runner.
# This machine's `sed` is BSD/macOS sed, where `-i` requires an explicit (possibly
# empty) backup-suffix argument; the GNU-style invocation errors here with
# "illegal option -- -". Per the task brief, the production mutator string in
# profiles/dependency_update.py is left untouched (GNU-targeted, correct for the
# runner) and only these TEST commands use a portable `perl -pi -e` substitution
# so the suite is deterministic on both macOS and Linux dev machines.
def test_dry_run_reports_changed_file(tmp_path):
    repo = _git_repo(tmp_path, {"requirements.txt": "fastapi==0.139.0\n"})
    changed = dry_run_mutation(
        repo,
        [
            "perl -pi -e 's/^fastapi==0\\.139\\.0$/fastapi==0.139.2/' requirements.txt",
            "grep -qx 'fastapi==0.139.2' requirements.txt",
        ],
    )
    assert changed == {"requirements.txt"}


def test_dry_run_fails_closed_on_no_diff(tmp_path):
    repo = _git_repo(tmp_path, {"requirements.txt": "fastapi==0.139.2\n"})
    with pytest.raises(ValidationError, match="no diff"):
        dry_run_mutation(
            repo,
            [
                "perl -pi -e 's/^fastapi==0\\.139\\.0$/fastapi==0.139.2/' requirements.txt",
            ],
        )


def test_pin_site_coverage_fails_when_site_untouched():
    sites = [
        PinSite("requirements.txt", "requirements.txt", "0.139.0"),
        PinSite("requirements-dev.txt", "requirements-dev.txt", "0.139.0"),
    ]
    with pytest.raises(ValidationError, match="requirements-dev.txt"):
        assert_pin_sites_moved({"requirements.txt"}, sites)


def test_runner_honest_rejects_make_check():
    with pytest.raises(ValidationError, match="make check"):
        assert_runner_honest(["uv add 'x>=1'", "uv run make check"])


def test_runner_honest_allows_uv_lock_check():
    assert assert_runner_honest(["uv add 'x>=1'", "uv lock --check"]) is None
