"""`/review` URL builders -- the human surfaces the front door hands off to.

Pure string composition, no I/O. Human gates are browser-only permanently
(ADR-0006), so a deep link is the entire mechanism by which this CLI crosses
one.

These FOUR are every page a `factory` verb actually links to: a staged intake
(`submit`), the paste form (`submit --print`), a decomposition proposal
(`status`), and a unit (`status`, `verify`). Add one when a verb needs it,
not before; `test_links.py` fails on a builder with no caller.
"""

from __future__ import annotations


def _root(base_url: str) -> str:
    return base_url.rstrip("/")


def staged_intake(base_url: str, review_path: str) -> str:
    """The orchestrator returns the page as a path (`/review/staged-intakes/{id}`), so this
    joins it to the base rather than rebuilding it from the id."""
    return f"{_root(base_url)}/{review_path.lstrip('/')}"


def intake_new(base_url: str) -> str:
    return f"{_root(base_url)}/review/intakes/new"


def decomposition_proposal(base_url: str, proposal_id: str) -> str:
    return f"{_root(base_url)}/review/decomposition-proposals/{proposal_id}"


def unit(base_url: str, unit_id: str) -> str:
    return f"{_root(base_url)}/review/units/{unit_id}"
