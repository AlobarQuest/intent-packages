import pytest

from intent_packages import canonical
from intent_packages import lineage as ln
from intent_packages.emitter import EmitError, NullEmitter
from intent_packages.loader import load_package
from intent_packages.operations import OperationError, do_transition

NOW = "2026-07-03T03:00:00Z"


def _completed_package(pkg_dir, edit_yaml, *, follow_up_required):
    """Hand-build a `completed`-state fixture: package.yaml status +
    follow_up.required set directly, lineage current_state set to match, and
    the recorded revision hash updated so hash-drift check H doesn't fire
    (follow_up.required is part of the hashed intent core)."""
    edit_yaml(pkg_dir, "package.yaml", set_nested=(("follow_up", "required"), follow_up_required))
    edit_yaml(pkg_dir, "package.yaml", set_key=("status", "completed"))
    new_hash = canonical.package_hash(load_package(pkg_dir))
    lin = ln.read(pkg_dir)
    lin["current_state"] = "completed"
    lin["revisions"][0]["hash"] = new_hash
    ln.write(pkg_dir, lin)
    return pkg_dir


def test_legal_transition_flips_status_in_both_files_and_snapshots_hash(valid_package):
    do_transition(valid_package, "ready_for_review", emitter=NullEmitter(), now=NOW)

    package = load_package(valid_package)
    assert package["status"] == "ready_for_review"

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "ready_for_review"

    # revision 1 was re-snapshotted at `now` without rewriting its creation time
    rev1 = next(r for r in lineage["revisions"] if r["revision"] == 1)
    assert rev1["created_at"] == "2026-07-03T00:00:00Z"
    assert rev1["snapshotted_at"] == NOW
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
        do_transition(valid_package, "ready_for_review", emitter=NullEmitter(), now=NOW)

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

    do_transition(valid_package, "ready_for_review", emitter=NullEmitter(), now=NOW)

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

    do_transition(valid_package, "ready_for_review", emitter=RaisingEmitter(), now=NOW)

    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "ready_for_review"
    assert len(lineage["transitions"]) == 1
    assert lineage["transitions"][0]["event_id"] is None


def test_follow_up_required_refuses_completed_to_closed(valid_package, edit_yaml):
    _completed_package(valid_package, edit_yaml, follow_up_required=True)

    with pytest.raises(OperationError, match="follow_up.required"):
        do_transition(valid_package, "closed", emitter=NullEmitter(), now=NOW)

    # nothing was mutated
    package = load_package(valid_package)
    assert package["status"] == "completed"
    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "completed"
    assert lineage["transitions"] == []


def test_follow_up_required_allows_completed_to_follow_up_due(valid_package, edit_yaml):
    _completed_package(valid_package, edit_yaml, follow_up_required=True)

    do_transition(valid_package, "follow_up_due", emitter=NullEmitter(), now=NOW)

    package = load_package(valid_package)
    assert package["status"] == "follow_up_due"
    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "follow_up_due"


def test_follow_up_not_required_allows_completed_to_closed(valid_package, edit_yaml):
    _completed_package(valid_package, edit_yaml, follow_up_required=False)

    do_transition(valid_package, "closed", emitter=NullEmitter(), now=NOW)

    package = load_package(valid_package)
    assert package["status"] == "closed"
    lineage = ln.read(valid_package)
    assert lineage["current_state"] == "closed"
