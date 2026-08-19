"""Approving a revision by policy conformance rather than by a named human (ADR-0028).

THE SUBJECT IS THE REAL SHIPPED PACKAGE, copied into a tmp_path. A synthetic fixture
would prove the approver arm works and say nothing about whether the standing packages
this lane exists for can actually take a policy approval -- which is the property that
breaks silently, because the producer approves them unattended and the failure surfaces
as a work record nobody can carry.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from intent_packages import lineage as ln
from intent_packages.approval_policy import ApprovalPolicyError
from intent_packages.operations import (
    OperationError,
    do_approve,
    do_transition,
    verify_approval,
)

NOW = "2026-08-19T12:00:00Z"
COMMIT = "abc1234"
STANDING = Path("packages/infraops-mcp-server-npm-zod")
POLICY_APPROVER = "policy:dependency-update@v1"


class StubEmitter:
    def __init__(self, event_id="evt-policy-1"):
        self.event_id = event_id
        self.calls = []

    def emit(self, action, ref, evidence):
        self.calls.append((action, ref, evidence))
        return self.event_id


def _fill(pkg_dir: Path, *, before: str = "3.25.76", after: str = "4.4.3") -> None:
    """Write the two per-bump values, the way the producer does -- by line, in place."""
    text = (pkg_dir / "package.yaml").read_text(encoding="utf-8")
    text = text.replace("  from_version: unassigned", f"  from_version: {before}")
    text = text.replace("  to_version: unassigned", f"  to_version: {after}")
    (pkg_dir / "package.yaml").write_text(text, encoding="utf-8")


@pytest.fixture
def standing(tmp_path, monkeypatch, fake_registry) -> Path:
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    pkg_dir = tmp_path / STANDING.name
    shutil.copytree(STANDING, pkg_dir)
    return pkg_dir


def test_a_filled_standing_package_is_approved_by_the_policy(standing) -> None:
    _fill(standing)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)
    emitter = StubEmitter()

    do_approve(standing, emitter=emitter, approver=POLICY_APPROVER, commit=COMMIT, now=NOW)

    lineage = ln.read(standing)
    assert lineage["current_state"] == "approved"
    assert [a["approver"] for a in lineage["approvals"]] == [POLICY_APPROVER]
    action, _ref, evidence = emitter.calls[0]
    assert action == "package.approved"
    assert evidence["approver"] == POLICY_APPROVER


def test_the_ledger_check_recognises_a_policy_approval(standing) -> None:
    """Kills: `_has_matching_approval` left keyed on human operators alone.

    Without this arm every policy-approved revision fails `verify_approval`, and the
    failure surfaces one repository away as an intake refusing `package_not_intakeable`.
    """
    _fill(standing)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)
    do_approve(standing, emitter=StubEmitter(), approver=POLICY_APPROVER, commit=COMMIT, now=NOW)

    assert verify_approval(standing, ledger_only=True) is True


def test_the_ledger_check_still_refuses_an_approver_that_is_neither(standing) -> None:
    """Kills: `_is_recognised_approver` widened to accept any string.

    The forged entry is written straight into the ledger, which is the attack the ledger
    check exists for -- and the arm added for policy must not have opened it.
    """
    _fill(standing)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)
    do_approve(standing, emitter=StubEmitter(), approver=POLICY_APPROVER, commit=COMMIT, now=NOW)
    lineage = ln.read(standing)
    lineage["approvals"][0]["approver"] = "mallory"
    ln.write(standing, lineage)

    assert verify_approval(standing, ledger_only=True) is False


def test_an_unfilled_standing_package_cannot_be_approved(standing) -> None:
    """Kills: `_authorize_approver` dropping the refusals check.

    The shell as authored, with both versions holding the same placeholder. This is the
    case that matters most, because it is the one a mis-wired producer produces.
    """
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)
    with pytest.raises(OperationError, match="bump_versions_not_distinct"):
        do_approve(
            standing, emitter=StubEmitter(), approver=POLICY_APPROVER, commit=COMMIT, now=NOW
        )
    assert ln.read(standing)["current_state"] == "ready_for_review"


def test_a_non_conformant_revision_cannot_be_approved(standing) -> None:
    _fill(standing)
    text = (standing / "package.yaml").read_text()
    text = text.replace("max_llm_calls: 120", "max_llm_calls: 1200")
    (standing / "package.yaml").write_text(text)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)

    with pytest.raises(OperationError, match="budget_above_ceiling"):
        do_approve(
            standing, emitter=StubEmitter(), approver=POLICY_APPROVER, commit=COMMIT, now=NOW
        )


def test_a_policy_version_the_artifact_is_not_at_is_refused(standing) -> None:
    """Kills: `_authorize_approver` accepting any policy-shaped approver.

    A caller must not be able to assert a version. The one the ledger records has to be
    the one that actually decided, or the record is not re-derivable, which is the whole
    reason ADR-0028 records a version rather than a name.
    """
    _fill(standing)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)
    with pytest.raises(OperationError, match="not the approver this policy grants"):
        do_approve(
            standing,
            emitter=StubEmitter(),
            approver="policy:dependency-update@v9",
            commit=COMMIT,
            now=NOW,
        )


def test_another_profiles_grant_cannot_be_borrowed(standing) -> None:
    _fill(standing)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)
    with pytest.raises(OperationError, match="not the approver this policy grants"):
        do_approve(
            standing,
            emitter=StubEmitter(),
            approver="policy:software-delivery@v1",
            commit=COMMIT,
            now=NOW,
        )


def test_an_unknown_approver_is_still_refused(standing) -> None:
    """The human arm is untouched: a name that is neither a human operator nor a policy
    is refused exactly as it was before ADR-0028."""
    _fill(standing)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)
    with pytest.raises(OperationError, match="neither a human-operator identity nor a policy"):
        do_approve(standing, emitter=StubEmitter(), approver="mallory", commit=COMMIT, now=NOW)


def test_an_unreadable_policy_refuses_rather_than_approving(standing, monkeypatch) -> None:
    """Kills: `_authorize_approver` swallowing `ApprovalPolicyError`.

    A caller that read a broken document as "no objections" would turn one unparseable
    byte into a standing approval for everything.
    """
    _fill(standing)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)

    def _boom():
        raise ApprovalPolicyError("nope")

    monkeypatch.setattr("intent_packages.operations.load_policy", _boom)
    with pytest.raises(OperationError, match="could not be read"):
        do_approve(
            standing, emitter=StubEmitter(), approver=POLICY_APPROVER, commit=COMMIT, now=NOW
        )


def test_a_second_revision_of_the_same_standing_package_is_approved_the_same_way(
    standing,
) -> None:
    """The lane, not the first use of it: revision 2 must take the same policy approval,
    with the revision-1 approval left bound to its own hash."""
    _fill(standing)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)
    do_approve(standing, emitter=StubEmitter(), approver=POLICY_APPROVER, commit=COMMIT, now=NOW)

    from intent_packages.operations import do_revise

    do_revise(standing, emitter=StubEmitter(), now=NOW)
    text = (standing / "package.yaml").read_text().replace("to_version: 4.4.3", "to_version: 4.5.0")
    (standing / "package.yaml").write_text(text)
    do_transition(standing, "ready_for_review", emitter=StubEmitter(), now=NOW)
    do_approve(standing, emitter=StubEmitter(), approver=POLICY_APPROVER, commit=COMMIT, now=NOW)

    lineage = ln.read(standing)
    assert [a["revision"] for a in lineage["approvals"]] == [1, 2]
    assert verify_approval(standing, ledger_only=True) is True
