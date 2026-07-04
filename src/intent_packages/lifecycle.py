"""Intent-package lifecycle state machine (spec section 5.2).

Pure data module: no IO, no dependencies on other project modules. Later
tasks (validate, transition, approve/revise/supersede) read these constants
rather than re-deriving them.
"""
from __future__ import annotations

STATES: frozenset[str] = frozenset(
    {
        "draft",
        "needs_clarification",
        "ready_for_review",
        "approved",
        "executable",
        "in_execution",
        "verification",
        "completed",
        "follow_up_due",
        "blocked",
        "rejected",
        "closed",
        "cancelled",
        "failed",
        "superseded",
    }
)

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"needs_clarification", "ready_for_review", "cancelled"}),
    "needs_clarification": frozenset({"draft", "ready_for_review", "cancelled"}),
    "ready_for_review": frozenset(
        {"approved", "rejected", "needs_clarification", "cancelled"}
    ),
    "approved": frozenset({"executable", "superseded", "cancelled"}),
    "executable": frozenset({"in_execution", "blocked", "superseded", "cancelled"}),
    "in_execution": frozenset(
        {"verification", "blocked", "failed", "superseded", "cancelled"}
    ),
    "verification": frozenset(
        {"completed", "in_execution", "failed", "blocked", "superseded"}
    ),
    "completed": frozenset({"follow_up_due", "closed"}),
    "follow_up_due": frozenset({"closed"}),
    "blocked": frozenset({"executable", "in_execution", "cancelled"}),
    "rejected": frozenset({"draft"}),
    "closed": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
    "superseded": frozenset(),
}

TERMINAL: frozenset[str] = frozenset({"closed", "cancelled", "failed", "superseded"})

DRIFT_LOCKED: frozenset[str] = frozenset(
    {
        "ready_for_review",
        "approved",
        "executable",
        "in_execution",
        "verification",
        "completed",
        "follow_up_due",
        "blocked",
        "rejected",
    }
)

REVISE_LEGAL_FROM: frozenset[str] = frozenset(
    {"draft", "needs_clarification", "ready_for_review", "rejected", "approved"}
)


def is_legal_transition(src: str, dst: str) -> bool:
    return dst in LEGAL_TRANSITIONS.get(src, frozenset())
