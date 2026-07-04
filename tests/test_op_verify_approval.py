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
    lineage.append_approval(
        lin, 1, h, "claude-code-interactive", NOW, COMMIT, "evt-forged-1"
    )
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


def test_default_chain_checker_true_when_event_matches(tmp_path, monkeypatch, fake_registry):
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps(
            {
                "event": {
                    "action": "package.approved",
                    "actor": "devon",
                    "evidence": [
                        {
                            "approved_hash": "deadbeef",
                            "approver": "devon",
                            "commit": "abc1234",
                            "revision": 1,
                        }
                    ],
                    "source": {"ref": "ws-2.2-domain-profiles", "system": "direct"},
                    "schema": "factory-event/v1",
                    "event_id": "evt-1",
                },
                "hash": "hash1",
                "prev_hash": "hash0",
                "seq": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    monkeypatch.setenv("FACTORY_EVENTS_FILE", str(events_file))
    monkeypatch.setattr(
        "intent_packages.operations.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(args=a, returncode=0, stdout="", stderr=""),
    )

    assert default_chain_checker("deadbeef", 1) is True


def test_default_chain_checker_no_matching_event_returns_false(
    tmp_path, monkeypatch, fake_registry
):
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps(
            {
                "event": {
                    "action": "package.approved",
                    "actor": "devon",
                    "evidence": [
                        {
                            "approved_hash": "some-other-hash",
                            "approver": "devon",
                            "commit": "abc1234",
                            "revision": 1,
                        }
                    ],
                    "source": {"ref": "ws-2.2-domain-profiles", "system": "direct"},
                    "schema": "factory-event/v1",
                    "event_id": "evt-2",
                },
                "hash": "hash2",
                "prev_hash": "hash1",
                "seq": 2,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    monkeypatch.setenv("FACTORY_EVENTS_FILE", str(events_file))
    monkeypatch.setattr(
        "intent_packages.operations.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(args=a, returncode=0, stdout="", stderr=""),
    )

    assert default_chain_checker("deadbeef", 1) is False


def test_default_chain_checker_missing_events_file_raises(tmp_path, monkeypatch, fake_registry):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    monkeypatch.setenv("FACTORY_EVENTS_FILE", str(tmp_path / "nope.jsonl"))
    monkeypatch.setattr(
        "intent_packages.operations.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(args=a, returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(ChainUnavailable):
        default_chain_checker("deadbeef", 1)


def test_default_chain_checker_chain_verify_failure_raises(tmp_path, monkeypatch, fake_registry):
    events_file = tmp_path / "events.jsonl"
    events_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    monkeypatch.setenv("FACTORY_EVENTS_FILE", str(events_file))
    monkeypatch.setattr(
        "intent_packages.operations.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a, returncode=1, stdout="", stderr="chain tampered"
        ),
    )

    with pytest.raises(ChainUnavailable):
        default_chain_checker("deadbeef", 1)


def test_default_chain_checker_no_registry_raises(tmp_path, monkeypatch):
    # _hermetic_registry_env (autouse) already points SECURITY_STANDARDS_DIR
    # at a nonexistent registry, so no override is needed here.
    with pytest.raises(ChainUnavailable):
        default_chain_checker("deadbeef", 1)
