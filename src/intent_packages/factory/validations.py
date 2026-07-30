"""The owned fail-closed validations for a dependency-update envelope.

#0 assert_checkout_current — the local checkout IS origin/main, freshly fetched.
#1 dry_run_mutation      — real diff + idempotency against a clean clone at HEAD.
#4 assert_pin_sites_moved — every discovered pin-site file is actually changed.
#2 assert_runner_honest  — no tool-guarded check the bare runner can't run.
(#3 conformance-from-real-scan is structural in decompose.py — no code path
 accepts a hand-typed conformance.)

#0 exists because #1 is only evidence about what the runner will see if the
clone it runs against matches origin/main. The 2026-07-30 production drive
found a target checkout on a divergent non-ancestor commit — the dry-run would
have passed while proving nothing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from intent_packages.profiles.dependency_update import DENIED_VERIFIER_PATTERNS, PinSite


class ValidationError(Exception):
    """Raised when a fail-closed validation rejects the envelope."""


def _diff_names(repo: Path) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=repo, capture_output=True, text=True, check=True
    )
    return {line for line in result.stdout.splitlines() if line}


def _diff_content(repo: Path) -> str:
    result = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout


def _run_command(command: str, cwd: Path) -> None:
    try:
        subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise ValidationError(
            f"mutation command failed: {command!r} exited {exc.returncode}: "
            f"{(exc.stderr or exc.stdout or '').strip()}"
        ) from exc


def _rev_parse(repo: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def assert_checkout_current(repo: Path) -> None:
    fetch = subprocess.run(
        ["git", "fetch", "--quiet", "origin", "main"], cwd=repo, capture_output=True, text=True
    )
    if fetch.returncode != 0:
        raise ValidationError(
            f"cannot verify checkout currency: 'git fetch origin main' failed in {repo}: "
            f"{(fetch.stderr or fetch.stdout).strip() or f'exit {fetch.returncode}'}"
        )
    head = _rev_parse(repo, "HEAD")
    remote = _rev_parse(repo, "origin/main")
    if head != remote:
        raise ValidationError(
            f"target checkout is not origin/main: HEAD {head[:12]} != origin/main {remote[:12]}. "
            f"Fix: git -C {repo} checkout main && git -C {repo} pull --ff-only origin main"
        )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    )
    if status.stdout.strip():
        raise ValidationError(
            f"target checkout has uncommitted changes; the dry-run clones committed state "
            f"only, so they would be silently ignored. "
            f"Fix: commit, stash, or discard them in {repo}, then re-run"
        )


def dry_run_mutation(repo_path: Path, allowed_commands: list[str]) -> set[str]:
    workdir = Path(tempfile.mkdtemp(prefix="factory-dryrun-"))
    target = workdir / "repo"
    try:
        subprocess.run(
            ["git", "clone", "--local", "--quiet", str(repo_path), str(target)], check=True
        )
        for command in allowed_commands:
            _run_command(command, target)
        names = _diff_names(target)
        if not names:
            raise ValidationError("mutation produced no diff (already at target, or no-op mutator)")
        first_content = _diff_content(target)
        for command in allowed_commands:
            _run_command(command, target)
        second_content = _diff_content(target)
        if second_content != first_content:
            raise ValidationError("mutation is not idempotent: diff content changed on second run")
        return names
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def assert_pin_sites_moved(changed_files: set[str], sites: list[PinSite]) -> None:
    for site in sites:
        if site.file not in changed_files:
            raise ValidationError(
                f"pin site not updated: {site.file} ({site.label}) was not changed by the mutator"
            )


def assert_runner_honest(allowed_commands: list[str]) -> None:
    for command in allowed_commands:
        for pattern in DENIED_VERIFIER_PATTERNS:
            if re.search(pattern, command):
                raise ValidationError(
                    f"runner-dishonest command (bare runner cannot run it): {command!r}"
                )
