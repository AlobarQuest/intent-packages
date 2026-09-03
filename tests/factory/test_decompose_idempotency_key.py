"""The decomposition idempotency key must identify the REVISION, not the bump.

Found 2026-09-03 by exercising the lane the standing-package model exists to create. Revision 2
of `infraops-mcp-server-npm-zod` failed, revision 3 was authored to carry the same bump, and the
submit was refused:

    idempotency_conflict: idempotency key belongs to a different operation

because the key was `factory-decompose-{target_repo}-{package}-{new}` -- which names the bump. A
standing package is revised per bump (ADR-0028), so the second revision of one bump is not an
exception, it is the recovery path. The old key made that path structurally impossible.

This is the estate's own rule that a key identifies an OPERATION rather than a subject, in a
third artifact after the landing ledger's source_reference and the work-carrier's
`work-carry-{record}-{revision}`.
"""

import pytest

from intent_packages.factory.decompose import DecomposeError, _idempotency_key


def _intake(revision_id: str | None) -> dict:
    return {"id": revision_id} if revision_id is not None else {}


def test_two_revisions_of_the_same_bump_get_different_keys() -> None:
    """THE regression. Both proposals name zod 4.4.3; only the revision differs."""
    first = _idempotency_key(_intake("a8dc9225-79a3-4aeb-a42e-29a2db79d595"), "zod", "4.4.3")
    second = _idempotency_key(_intake("7e597f88-6e35-4b1e-99f1-67386d11bc53"), "zod", "4.4.3")

    assert first != second


def test_the_same_revision_replays_to_the_same_key() -> None:
    """The other half: idempotency must still WORK for a genuine retry of one operation."""
    args = (_intake("a8dc9225-79a3-4aeb-a42e-29a2db79d595"), "zod", "4.4.3")

    assert _idempotency_key(*args) == _idempotency_key(*args)


@pytest.mark.parametrize("missing", [None, "", 3], ids=["absent", "empty", "not-a-string"])
def test_an_intake_with_no_revision_id_is_REFUSED_not_fallen_back(missing: object) -> None:
    """A fallback to the old shape would restore the collision silently.

    That is the failure mode this fix exists to end, so the absent case must raise rather than
    degrade -- for a payload whose shape nobody checked, a quiet reuse is worse than a refusal.
    """
    intake = {} if missing is None else {"id": missing}

    with pytest.raises(DecomposeError, match="no revision id"):
        _idempotency_key(intake, "zod", "4.4.3")


def test_the_key_stays_within_the_orchestrator_s_bound() -> None:
    """`idempotency_key` is maxLength 200 on the command model; a UUID plus a bump is far under."""
    key = _idempotency_key(
        _intake("a8dc9225-79a3-4aeb-a42e-29a2db79d595"), "typescript-eslint", "8.67.0"
    )

    assert len(key) <= 200
    assert "/" not in key
