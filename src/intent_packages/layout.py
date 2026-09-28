"""Where packages live in this repository: `packages/` for live work, `archive/` for settled.

A package is SETTLED once its lifecycle state is terminal (`lifecycle.TERMINAL`): nothing can
move it again, so it is history rather than work. Settled packages live under `archive/`, which
keeps `packages/` equal to the set anything may still act on. That matters beyond tidiness:
`bump_proposer` (orchestrator) builds its lane from `packages/*/package.yaml`, and the work
carrier resolves a record's package at `packages/<package_id>`.

**ARCHIVING MOVES A DIRECTORY AND CHANGES NOTHING ELSE.** The package hash covers the YAML, not
its path, so an archived package keeps its hash, its lineage and its approval, and still
verifies. Every reader that means "every package" must read both directories through
`all_package_dirs`, or an archived package drops out of validation silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
ACTIVE_DIRNAME: Final = "packages"
ARCHIVE_DIRNAME: Final = "archive"


def _dirs(base: Path) -> list[Path]:
    """Every subdirectory, whether or not it holds a package.yaml.

    Not filtered on the file being present: a directory whose package.yaml is missing is a
    broken package, and it must reach `validate_package` and fail there rather than drop out
    of every check unseen.
    """
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))


def active_package_dirs(root: Path = REPO_ROOT) -> list[Path]:
    """Packages anything may still act on."""
    return _dirs(root / ACTIVE_DIRNAME)


def archived_package_dirs(root: Path = REPO_ROOT) -> list[Path]:
    """Settled packages: terminal, kept so they still validate and verify."""
    return _dirs(root / ARCHIVE_DIRNAME)


def all_package_dirs(root: Path = REPO_ROOT) -> list[Path]:
    """Every package in the repository, live and settled, ordered by package id."""
    return sorted(active_package_dirs(root) + archived_package_dirs(root), key=lambda p: p.name)
