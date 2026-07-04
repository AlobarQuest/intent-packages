"""Lineage read/write helpers (spec section 9).

Pure dict manipulation + file IO. `write` dumps deterministically so the
file re-parses cleanly under `loader.load_yaml_strict` — callers must pass
all timestamp/hash values as strings (never datetimes); this module never
converts them.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from intent_packages.loader import load_lineage


def read(pkg_dir: str | Path) -> dict:
    return load_lineage(pkg_dir)


def write(pkg_dir: str | Path, lineage: dict) -> None:
    text = yaml.safe_dump(
        lineage, sort_keys=False, default_flow_style=False, allow_unicode=True
    )
    (Path(pkg_dir) / "lineage.yaml").write_text(text, encoding="utf-8")


def current_revision_hash(lineage: dict) -> str:
    top = max(lineage["revisions"], key=lambda r: r["revision"])
    return top["hash"]


def append_transition(
    lineage: dict,
    kind: str,
    src: str,
    dst: str,
    at: str,
    actor: str,
    event_id: str | None,
) -> None:
    lineage.setdefault("transitions", []).append(
        {
            "kind": kind,
            "from": src,
            "to": dst,
            "at": at,
            "actor": actor,
            "event_id": event_id,
        }
    )


def snapshot_revision(
    lineage: dict,
    revision: int,
    hash_hex: str,
    at: str,
    author: str,
) -> None:
    entry = {
        "revision": revision,
        "hash": hash_hex,
        "created_at": at,
        "author": author,
    }
    revisions = lineage.setdefault("revisions", [])
    for i, existing in enumerate(revisions):
        if existing["revision"] == revision:
            revisions[i] = entry
            return
    revisions.append(entry)


def append_approval(
    lineage: dict,
    revision: int,
    approved_hash: str,
    approver: str,
    at: str,
    commit: str,
    event_id: str | None,
) -> None:
    lineage.setdefault("approvals", []).append(
        {
            "revision": revision,
            "approved_hash": approved_hash,
            "approver": approver,
            "approved_at": at,
            "commit": commit,
            "event_id": event_id,
        }
    )
