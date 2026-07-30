"""`/review` URL builders -- the human surfaces the front door hands off to.

Pure string composition, no I/O. Human gates are browser-only permanently
(ADR-0006), so a deep link is the entire mechanism by which this CLI crosses
one.

These THREE are every page a `factory` verb actually links to: the intake form
(`submit`), a decomposition proposal (`status`), and a unit (`status`,
`verify`). Two more once lived here -- `intake(base_url, revision_id)` and
`unit_evidence_pack(...)` -- alongside a docstring claiming "these four ...
there is no fifth" while five existed and two had no caller at all. Both are
deleted rather than kept warm: `submit` already tells the operator to resume
with `factory status --revision <id>` rather than re-linking the intake page,
and the evidence pack is fetched by `factory evidence`, not browsed. Add one
back when a verb needs it, not before.
"""

from __future__ import annotations


def _root(base_url: str) -> str:
    return base_url.rstrip("/")


def intake_new(base_url: str) -> str:
    return f"{_root(base_url)}/review/intakes/new"


def decomposition_proposal(base_url: str, proposal_id: str) -> str:
    return f"{_root(base_url)}/review/decomposition-proposals/{proposal_id}"


def unit(base_url: str, unit_id: str) -> str:
    return f"{_root(base_url)}/review/units/{unit_id}"
