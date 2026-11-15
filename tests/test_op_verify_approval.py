import json
import subprocess

import pytest

from intent_packages import canonical, lineage, loader
from intent_packages.operations import (
    ChainUnavailable,
    default_chain_checker,
    do_approve,
    do_transition,
    verify_approval,
)

NOW = "2026-07-03T03:00:00Z"
COMMIT = "abc1234"


class StubEmitter:
    def __init__(self, event_id="evt-approve-1"):
        self.event_id = event_id

    def emit(self, action, ref, evidence):
        return self.event_id


def _ready_for_review(pkg_dir):
    do_transition(pkg_dir, "ready_for_review", emitter=StubEmitter(), now=NOW)


def _approve(pkg_dir, monkeypatch, fake_registry):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    _ready_for_review(pkg_dir)
    do_approve(pkg_dir, emitter=StubEmitter(), approver="devon", commit=COMMIT, now=NOW)


def test_verify_approval_true_when_ledger_and_chain_agree(
    valid_package, monkeypatch, fake_registry
):
    _approve(valid_package, monkeypatch, fake_registry)

    assert verify_approval(valid_package, chain_checker=lambda h, r: True) is True


def test_verify_approval_forged_ledger_chain_disagrees_but_ledger_only_passes(
    valid_package, monkeypatch, fake_registry
):
    _approve(valid_package, monkeypatch, fake_registry)

    # Ledger has a real matching entry, but the chain says no such event
    # exists -- the mechanical gate must not trust the ledger alone.
    assert verify_approval(valid_package, chain_checker=lambda h, r: False) is False

    # ledger_only bypasses the chain check entirely.
    assert verify_approval(valid_package, ledger_only=True) is True


def test_verify_approval_fails_closed_when_chain_unavailable(
    valid_package, monkeypatch, fake_registry
):
    _approve(valid_package, monkeypatch, fake_registry)

    def _raiser(h, r):
        raise ChainUnavailable("chain store unreachable")

    # A raising chain_checker must never bubble up -- verify_approval fails
    # closed (False), it does not propagate the exception.
    assert verify_approval(valid_package, chain_checker=_raiser) is False


def test_verify_approval_false_when_never_approved(valid_package, monkeypatch, fake_registry):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    _ready_for_review(valid_package)

    assert verify_approval(valid_package, chain_checker=lambda h, r: True) is False


def test_verify_approval_rejects_forged_non_human_approver(
    valid_package, monkeypatch, fake_registry
):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))

    # Forge a lineage.yaml approvals entry directly (bypassing do_approve)
    # with a registered but NON-human approver (interactive-dev-v1 profile
    # per fake_registry). Hash matches, so only the approver-humanity check
    # is under test.
    h = canonical.package_hash(loader.load_package(valid_package))
    lin = lineage.read(valid_package)
    lineage.append_approval(lin, 1, h, "claude-code-interactive", NOW, COMMIT, "evt-forged-1")
    lin["current_state"] = "approved"
    lineage.write(valid_package, lin)

    assert verify_approval(valid_package, ledger_only=True) is False


def test_verify_approval_false_on_hash_mismatch_after_edit(
    valid_package, monkeypatch, fake_registry, edit_yaml
):
    _approve(valid_package, monkeypatch, fake_registry)

    # Material edit after approval: the ledger's recorded approved_hash no
    # longer matches the live package hash.
    edit_yaml(
        valid_package,
        "package.yaml",
        set_key=("title", "A materially edited title (post-approval)"),
    )

    assert verify_approval(valid_package, ledger_only=True) is False


def _stub_database_chain(monkeypatch, fake_registry, answer) -> list[tuple]:
    """Read-password mode with `_database_chain_has_matching_approval` stubbed: the real
    reader's subprocess is covered in test_chain_checker_database_mode.py and its database in
    test_chain_db_integration.py."""
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    monkeypatch.setenv("FACTORY_EVENTS_READ_PASSWORD", "READ-PW-placeholder")
    calls: list[tuple] = []

    def stub(sec_std_dir, approved_hash, revision):
        calls.append((sec_std_dir, approved_hash, revision))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr("intent_packages.operations._database_chain_has_matching_approval", stub)
    return calls


@pytest.mark.parametrize("answer", [True, False])
def test_default_chain_checker_returns_the_database_answer(monkeypatch, fake_registry, answer):
    calls = _stub_database_chain(monkeypatch, fake_registry, answer)

    assert default_chain_checker("deadbeef", 1) is answer
    assert calls == [(fake_registry, "deadbeef", 1)]


def test_default_chain_checker_database_failure_raises(monkeypatch, fake_registry):
    _stub_database_chain(monkeypatch, fake_registry, ChainUnavailable("chain tampered"))

    with pytest.raises(ChainUnavailable, match="chain tampered"):
        default_chain_checker("deadbeef", 1)


def test_verify_approval_default_checker_false_with_no_chain_variable(
    valid_package, tmp_path, monkeypatch, fake_registry
):
    # A matching approval in an events file is never consulted (FE-5 R-IP).
    _approve(valid_package, monkeypatch, fake_registry)
    home = tmp_path / "factory-home"
    home.mkdir()
    h = canonical.package_hash(loader.load_package(valid_package))
    event = {"action": "package.approved", "evidence": [{"approved_hash": h, "revision": 1}]}
    (home / "events.jsonl").write_text(json.dumps({"seq": 1, "event": event}) + "\n")
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(home))
    monkeypatch.delenv("FACTORY_EVENTS_READ_PASSWORD", raising=False)
    monkeypatch.setattr(
        "intent_packages.operations.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(args=a, returncode=0, stdout="", stderr=""),
    )

    assert verify_approval(valid_package) is False


def test_default_chain_checker_no_registry_raises(tmp_path, monkeypatch):
    # _hermetic_registry_env (autouse) already points SECURITY_STANDARDS_DIR
    # at a nonexistent registry, so no override is needed here.
    with pytest.raises(ChainUnavailable):
        default_chain_checker("deadbeef", 1)
