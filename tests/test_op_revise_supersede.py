import pytest

from intent_packages import lineage as ln
from intent_packages.canonical import package_hash
from intent_packages.emitter import EmitError
from intent_packages.loader import load_package
from intent_packages.operations import (
    OperationError,
    do_approve,
    do_revise,
    do_supersede,
    do_transition,
)

NOW = "2026-07-03T03:00:00Z"
LATER = "2026-07-03T04:00:00Z"
COMMIT = "abc1234"


class StubEmitter:
    def __init__(self, event_id="evt-1"):
        self.event_id = event_id
        self.calls = []

    def emit(self, action, ref, evidence):
        self.calls.append((action, ref, evidence))
        return self.event_id


class RaisingEmitter:
    def emit(self, action, ref, evidence):
        raise EmitError("boom")


def _approve(pkg_dir, monkeypatch, fake_registry):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    do_transition(pkg_dir, "ready_for_review", emitter=StubEmitter(), now=NOW)
    do_approve(pkg_dir, emitter=StubEmitter(), approver="devon", commit=COMMIT, now=NOW)


# ---- revise ----------------------------------------------------------


def test_revise_from_approved_bumps_revision_and_resets_to_draft(
    valid_package, monkeypatch, fake_registry
):
    _approve(valid_package, monkeypatch, fake_registry)
    lineage_before = ln.read(valid_package)
    old_approval = lineage_before["approvals"][0]

    do_revise(valid_package, emitter=StubEmitter(event_id="evt-revise"), actor="devon", now=LATER)

    package = load_package(valid_package)
    assert package["revision"] == 2
    assert package["status"] == "draft"

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "draft"

    rev2 = next(r for r in lineage["revisions"] if r["revision"] == 2)
    assert rev2["created_at"] == LATER
    assert rev2["hash"] == package_hash(package)
    assert rev2["hash"] != old_approval["approved_hash"]

    # the old approval, bound to revision 1, is untouched
    assert lineage["approvals"] == [old_approval]

    revision_entries = [t for t in lineage["transitions"] if t["kind"] == "revision"]
    assert len(revision_entries) == 1
    assert revision_entries[0]["from"] == "approved"
    assert revision_entries[0]["to"] == "draft"
    assert revision_entries[0]["event_id"] == "evt-revise"


def test_revise_from_execution_state_raises_pointing_to_supersede(valid_package):
    lin = ln.read(valid_package)
    lin["current_state"] = "in_execution"
    ln.write(valid_package, lin)

    with pytest.raises(OperationError, match="supersede"):
        do_revise(valid_package, emitter=StubEmitter(), actor="devon", now=LATER)

    lineage_after = ln.read(valid_package)
    assert lineage_after["current_state"] == "in_execution"
    package = load_package(valid_package)
    assert package["revision"] == 1


def test_revise_emit_failure_is_best_effort(valid_package):
    do_revise(valid_package, emitter=RaisingEmitter(), actor="devon", now=LATER)

    package = load_package(valid_package)
    assert package["revision"] == 2
    assert package["status"] == "draft"

    lineage = ln.read(valid_package)
    revision_entries = [t for t in lineage["transitions"] if t["kind"] == "revision"]
    assert revision_entries[0]["event_id"] is None


# ---- supersede ---------------------------------------------------------


def test_supersede_from_approved_sets_superseded_and_backref(
    valid_package, replacement_package, monkeypatch, fake_registry
):
    _approve(valid_package, monkeypatch, fake_registry)

    do_supersede(
        valid_package,
        "sample-replacement-package",
        emitter=StubEmitter(event_id="evt-supersede"),
        actor="devon",
        now=LATER,
    )

    package = load_package(valid_package)
    assert package["status"] == "superseded"

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "superseded"

    supersession_entries = [t for t in lineage["transitions"] if t["kind"] == "supersession"]
    assert len(supersession_entries) == 1
    entry = supersession_entries[0]
    assert entry["from"] == "approved"
    assert entry["to"] == "superseded"
    assert entry["superseded_by"] == "sample-replacement-package"
    assert entry["event_id"] == "evt-supersede"


def test_supersede_illegal_from_draft_raises(valid_package):
    with pytest.raises(OperationError):
        do_supersede(
            valid_package,
            "sample-replacement-package",
            emitter=StubEmitter(),
            actor="devon",
            now=LATER,
        )

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "draft"


def test_supersede_emit_failure_is_best_effort(
    valid_package, replacement_package, monkeypatch, fake_registry
):
    _approve(valid_package, monkeypatch, fake_registry)

    do_supersede(
        valid_package,
        "sample-replacement-package",
        emitter=RaisingEmitter(),
        actor="devon",
        now=LATER,
    )

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "superseded"
    supersession_entries = [t for t in lineage["transitions"] if t["kind"] == "supersession"]
    assert supersession_entries[0]["event_id"] is None
