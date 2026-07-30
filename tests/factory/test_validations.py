import subprocess
from pathlib import Path

import pytest

from intent_packages.factory.validations import (
    ValidationError,
    assert_checkout_current,
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
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(["git", *argv], cwd=repo, check=True)
    return repo


def _commit_all(repo: Path, message: str) -> None:
    for argv in (
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message],
    ):
        subprocess.run(["git", *argv], cwd=repo, check=True)


def _checkout_with_origin(tmp_path: Path, files: dict[str, str]) -> Path:
    """A local checkout tracking a file:// origin, the shape decompose runs against."""
    origin = _git_repo(tmp_path, files)
    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(checkout)], check=True, capture_output=True
    )
    return checkout


def test_checkout_current_passes_when_head_is_origin_main(tmp_path):
    checkout = _checkout_with_origin(tmp_path, {"requirements.txt": "fastapi==0.139.0\n"})
    assert assert_checkout_current(checkout) is None


def test_checkout_current_fails_closed_when_origin_advanced(tmp_path):
    checkout = _checkout_with_origin(tmp_path, {"requirements.txt": "fastapi==0.139.0\n"})
    origin = tmp_path / "repo"
    (origin / "requirements.txt").write_text("fastapi==0.139.1\n", encoding="utf-8")
    _commit_all(origin, "advance origin")
    with pytest.raises(ValidationError, match=r"git -C .* pull --ff-only origin main"):
        assert_checkout_current(checkout)


def test_checkout_current_fails_closed_on_divergent_local_commit(tmp_path):
    checkout = _checkout_with_origin(tmp_path, {"requirements.txt": "fastapi==0.139.0\n"})
    (checkout / "local.txt").write_text("local-only\n", encoding="utf-8")
    _commit_all(checkout, "local divergence")
    with pytest.raises(ValidationError, match="origin/main"):
        assert_checkout_current(checkout)


def test_checkout_current_fails_closed_on_dirty_worktree(tmp_path):
    checkout = _checkout_with_origin(tmp_path, {"requirements.txt": "fastapi==0.139.0\n"})
    (checkout / "requirements.txt").write_text("fastapi==0.139.9\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="uncommitted"):
        assert_checkout_current(checkout)


def test_checkout_current_fails_closed_when_fetch_fails(tmp_path):
    repo = _git_repo(tmp_path, {"requirements.txt": "fastapi==0.139.0\n"})
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path / "does-not-exist")],
        cwd=repo,
        check=True,
    )
    with pytest.raises(ValidationError, match="fetch"):
        assert_checkout_current(repo)


def test_checkout_current_fails_closed_without_origin(tmp_path):
    repo = _git_repo(tmp_path, {"requirements.txt": "fastapi==0.139.0\n"})
    with pytest.raises(ValidationError, match="fetch"):
        assert_checkout_current(repo)


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


def test_dry_run_fails_closed_on_command_error(tmp_path):
    repo = _git_repo(tmp_path, {"requirements.txt": "fastapi==0.139.0\n"})
    with pytest.raises(ValidationError, match="mutation command failed"):
        dry_run_mutation(
            repo,
            [
                "perl -pi -e 's/^fastapi==0\\.139\\.0$/fastapi==0.139.2/' requirements.txt",
                "sh -c 'exit 3'",
            ],
        )


def test_dry_run_fails_closed_on_content_non_idempotent(tmp_path):
    repo = _git_repo(tmp_path, {"tracked.txt": "base\n"})
    with pytest.raises(ValidationError, match="idempoten"):
        dry_run_mutation(
            repo,
            [
                "sh -c 'echo x >> tracked.txt'",
            ],
        )
