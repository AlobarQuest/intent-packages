import pytest

from intent_packages import lineage as ln
from intent_packages.canonical import package_hash
from intent_packages.emitter import EmitError
from intent_packages.loader import load_package
from intent_packages.operations import OperationError, do_approve, do_transition

NOW = "2026-07-03T03:00:00Z"
COMMIT = "abc1234"


class StubEmitter:
    """Returns a fixed event_id; records calls so tests can assert no re-emit."""

    def __init__(self, event_id="evt-approve-1"):
        self.event_id = event_id
        self.calls = []

    def emit(self, action, ref, evidence):
        self.calls.append((action, ref, evidence))
        return self.event_id


class RaisingEmitter:
    def emit(self, action, ref, evidence):
        raise EmitError("boom")


def _ready_for_review(pkg_dir):
    do_transition(pkg_dir, "ready_for_review", emitter=StubEmitter(), now=NOW)


def _use_fake_registry(monkeypatch, fake_registry):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))


def test_approve_records_approval_and_sets_status(valid_package, monkeypatch, fake_registry):
    _use_fake_registry(monkeypatch, fake_registry)
    _ready_for_review(valid_package)
    emitter = StubEmitter(event_id="evt-approve-1")

    do_approve(valid_package, emitter=emitter, approver="devon", commit=COMMIT, now=NOW)

    package = load_package(valid_package)
    assert package["status"] == "approved"

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "approved"
    assert len(lineage["approvals"]) == 1
    approval = lineage["approvals"][0]
    assert approval["approved_hash"] == package_hash(package)
    assert approval["approver"] == "devon"
    assert approval["approved_at"] == NOW
    assert approval["commit"] == COMMIT
    assert approval["event_id"] == "evt-approve-1"
    assert len(emitter.calls) == 1
    assert emitter.calls[0][0] == "package.approved"


def test_approve_with_open_questions_raises(valid_package, monkeypatch, fake_registry, edit_yaml):
    _use_fake_registry(monkeypatch, fake_registry)
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("scope", "open_questions"), ["what about X?"]),
    )
    _ready_for_review(valid_package)

    with pytest.raises(OperationError):
        do_approve(
            valid_package, emitter=StubEmitter(), approver="devon", commit=COMMIT, now=NOW
        )

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "ready_for_review"
    assert lineage["approvals"] == []


def test_approve_with_non_human_approver_raises(valid_package, monkeypatch, fake_registry):
    _use_fake_registry(monkeypatch, fake_registry)
    _ready_for_review(valid_package)

    with pytest.raises(OperationError):
        do_approve(
            valid_package,
            emitter=StubEmitter(),
            approver="claude-code-interactive",
            commit=COMMIT,
            now=NOW,
        )

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "ready_for_review"
    assert lineage["approvals"] == []
    package = load_package(valid_package)
    assert package["status"] == "ready_for_review"


def test_approve_fatal_emit_failure_writes_no_approval(valid_package, monkeypatch, fake_registry):
    _use_fake_registry(monkeypatch, fake_registry)
    _ready_for_review(valid_package)

    with pytest.raises(OperationError):
        do_approve(
            valid_package, emitter=RaisingEmitter(), approver="devon", commit=COMMIT, now=NOW
        )

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "ready_for_review"
    assert lineage["approvals"] == []
    package = load_package(valid_package)
    assert package["status"] == "ready_for_review"


def test_approve_is_idempotent_on_repeat_call(valid_package, monkeypatch, fake_registry):
    _use_fake_registry(monkeypatch, fake_registry)
    _ready_for_review(valid_package)
    emitter = StubEmitter(event_id="evt-approve-1")

    do_approve(valid_package, emitter=emitter, approver="devon", commit=COMMIT, now=NOW)
    assert len(emitter.calls) == 1

    # Second call: current_state is now "approved", same package hash. Must
    # not re-emit and must not double-append an approval entry.
    do_approve(valid_package, emitter=emitter, approver="devon", commit=COMMIT, now=NOW)

    assert len(emitter.calls) == 1  # no re-emit
    lineage = ln.read(valid_package)
    assert len(lineage["approvals"]) == 1  # no double-append
    assert lineage["current_state"] == "approved"
    package = load_package(valid_package)
    assert package["status"] == "approved"


def test_approve_illegal_from_draft_raises(valid_package, monkeypatch, fake_registry):
    _use_fake_registry(monkeypatch, fake_registry)

    with pytest.raises(OperationError):
        do_approve(
            valid_package, emitter=StubEmitter(), approver="devon", commit=COMMIT, now=NOW
        )

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "draft"
    assert lineage["approvals"] == []
