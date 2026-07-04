import pytest

from intent_packages import lineage as ln
from intent_packages.emitter import EmitError, NullEmitter
from intent_packages.loader import load_package
from intent_packages.operations import OperationError, do_transition

NOW = "2026-07-03T03:00:00Z"


def test_legal_transition_flips_status_in_both_files_and_snapshots_hash(valid_package):
    do_transition(
        valid_package, "ready_for_review", emitter=NullEmitter(), now=NOW
    )

    package = load_package(valid_package)
    assert package["status"] == "ready_for_review"

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "ready_for_review"

    # revision 1 was re-snapshotted at `now` with the recomputed hash
    rev1 = next(r for r in lineage["revisions"] if r["revision"] == 1)
    assert rev1["created_at"] == NOW
    assert len(rev1["hash"]) == 64

    # a transition entry was appended
    assert len(lineage["transitions"]) == 1
    t = lineage["transitions"][0]
    assert t["kind"] == "transition"
    assert t["from"] == "draft"
    assert t["to"] == "ready_for_review"
    assert t["at"] == NOW
    assert t["event_id"] is None


def test_illegal_transition_raises_operation_error(valid_package):
    with pytest.raises(OperationError):
        do_transition(valid_package, "approved", emitter=NullEmitter(), now=NOW)

    # nothing was mutated
    package = load_package(valid_package)
    assert package["status"] == "draft"
    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "draft"
    assert lineage["transitions"] == []


def test_invalid_package_refuses_to_transition(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("owner", None))

    with pytest.raises(OperationError):
        do_transition(
            valid_package, "ready_for_review", emitter=NullEmitter(), now=NOW
        )

    lineage_before = ln.read(valid_package)
    assert lineage_before["current_state"] == "draft"
    assert lineage_before["transitions"] == []


def test_set_status_in_file_preserves_comments_and_other_lines(valid_package):
    path = valid_package / "package.yaml"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "status: draft\n",
        "status: draft\n# a hand-authored comment\n",
    )
    path.write_text(text, encoding="utf-8")

    do_transition(
        valid_package, "ready_for_review", emitter=NullEmitter(), now=NOW
    )

    new_text = path.read_text(encoding="utf-8")
    assert "# a hand-authored comment" in new_text
    assert "status: ready_for_review" in new_text
    # every other line of the original file survives untouched
    for line in text.splitlines():
        if line.startswith("status:"):
            continue
        assert line in new_text.splitlines()


def test_best_effort_emit_failure_still_completes_transition_with_null_event_id(
    valid_package,
):
    class RaisingEmitter:
        def emit(self, action, ref, evidence):
            raise EmitError("boom")

    do_transition(
        valid_package, "ready_for_review", emitter=RaisingEmitter(), now=NOW
    )

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "ready_for_review"
    assert len(lineage["transitions"]) == 1
    assert lineage["transitions"][0]["event_id"] is None
