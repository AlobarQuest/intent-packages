"""The three owned fail-closed validations for a dependency-update envelope.

#1 dry_run_mutation      — real diff + idempotency against a clean clone at HEAD.
#4 assert_pin_sites_moved — every discovered pin-site file is actually changed.
#2 assert_runner_honest  — no tool-guarded check the bare runner can't run.
(#3 conformance-from-real-scan is structural in decompose.py — no code path
 accepts a hand-typed conformance.)
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


def _diff_names(clone: Path) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=clone, capture_output=True, text=True, check=True
    )
    return {line for line in result.stdout.splitlines() if line}


def dry_run_mutation(repo_path: Path, allowed_commands: list[str]) -> set[str]:
    clone = Path(tempfile.mkdtemp(prefix="factory-dryrun-"))
    target = clone / "repo"
    try:
        subprocess.run(
            ["git", "clone", "--local", "--quiet", str(repo_path), str(target)], check=True
        )
        for command in allowed_commands:
            subprocess.run(command, shell=True, cwd=target, check=True)
        first = _diff_names(target)
        if not first:
            raise ValidationError("mutation produced no diff (already at target, or no-op mutator)")
        for command in allowed_commands:
            subprocess.run(command, shell=True, cwd=target, check=True)
        second = _diff_names(target)
        if second != first:
            raise ValidationError(
                f"mutation is not idempotent: changed files differ on second run "
                f"({sorted(first)} -> {sorted(second)})"
            )
        return first
    finally:
        shutil.rmtree(clone, ignore_errors=True)


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
