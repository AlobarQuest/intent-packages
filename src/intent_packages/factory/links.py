"""`/review` URL builders -- the human surfaces the front door hands off to.

Pure string composition, no I/O. These four (plus the evidence-pack child) are
every human-reachable page the flow touches; there is no fifth. Human gates are
browser-only permanently (ADR-0006), so a deep link is the entire mechanism by
which this CLI crosses one.
"""

from __future__ import annotations


def _root(base_url: str) -> str:
    return base_url.rstrip("/")


def intake_new(base_url: str) -> str:
    return f"{_root(base_url)}/review/intakes/new"


def intake(base_url: str, revision_id: str) -> str:
    return f"{_root(base_url)}/review/intakes/{revision_id}"


def decomposition_proposal(base_url: str, proposal_id: str) -> str:
    return f"{_root(base_url)}/review/decomposition-proposals/{proposal_id}"


def unit(base_url: str, unit_id: str) -> str:
    return f"{_root(base_url)}/review/units/{unit_id}"


def unit_evidence_pack(base_url: str, unit_id: str) -> str:
    return f"{unit(base_url, unit_id)}/evidence-pack"
