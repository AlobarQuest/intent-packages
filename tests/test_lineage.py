from intent_packages import lineage as ln
from intent_packages.loader import load_yaml_strict


def _sample_lineage() -> dict:
    return {
        "package_id": "ws-2.2-domain-profiles",
        "current_state": "approved",
        "revisions": [
            {
                "revision": 1,
                "hash": "a" * 64,
                "created_at": "2026-07-03T00:00:00Z",
                "author": "claude-code-interactive",
            }
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }


def test_write_then_read_round_trips(tmp_path):
    lineage = _sample_lineage()
    ln.write(tmp_path, lineage)
    result = ln.read(tmp_path)
    assert result == lineage


def test_write_output_reparses_under_load_yaml_strict_with_string_timestamps(tmp_path):
    lineage = _sample_lineage()
    ln.append_transition(
        lineage,
        kind="transition",
        src="draft",
        dst="ready_for_review",
        at="2026-07-03T00:05:00Z",
        actor="claude-code-interactive",
        event_id="evt-1",
    )
    ln.append_approval(
        lineage,
        revision=1,
        approved_hash="b" * 64,
        approver="devon",
        at="2026-07-03T00:10:00Z",
        commit="deadbeef",
        event_id="evt-2",
    )
    ln.write(tmp_path, lineage)

    raw = (tmp_path / "lineage.yaml").read_text(encoding="utf-8")
    reparsed = load_yaml_strict(raw)

    assert isinstance(reparsed["revisions"][0]["created_at"], str)
    assert isinstance(reparsed["transitions"][0]["at"], str)
    assert isinstance(reparsed["approvals"][0]["approved_at"], str)
    assert reparsed == lineage


def test_current_revision_hash_returns_top_revision():
    lineage = _sample_lineage()
    ln.snapshot_revision(
        lineage,
        revision=2,
        hash_hex="c" * 64,
        at="2026-07-03T01:00:00Z",
        author="claude-code-interactive",
    )
    assert ln.current_revision_hash(lineage) == "c" * 64


def test_current_revision_hash_ignores_list_order():
    lineage = {
        "package_id": "ws-2.2-domain-profiles",
        "current_state": "approved",
        "revisions": [
            {
                "revision": 1,
                "hash": "a" * 64,
                "created_at": "2026-07-03T00:00:00Z",
                "author": "claude-code-interactive",
            },
            {
                "revision": 5,
                "hash": "e" * 64,
                "created_at": "2026-07-03T01:00:00Z",
                "author": "claude-code-interactive",
            },
            {
                "revision": 3,
                "hash": "c" * 64,
                "created_at": "2026-07-03T02:00:00Z",
                "author": "claude-code-interactive",
            },
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }
    assert ln.current_revision_hash(lineage) == "e" * 64


def test_append_transition_uses_from_key_and_grows_list():
    lineage = _sample_lineage()
    ln.append_transition(
        lineage,
        kind="transition",
        src="draft",
        dst="ready_for_review",
        at="2026-07-03T00:05:00Z",
        actor="claude-code-interactive",
        event_id=None,
    )
    assert len(lineage["transitions"]) == 1
    t = lineage["transitions"][0]
    assert t == {
        "kind": "transition",
        "from": "draft",
        "to": "ready_for_review",
        "at": "2026-07-03T00:05:00Z",
        "actor": "claude-code-interactive",
        "event_id": None,
    }


def test_snapshot_revision_appends_when_new():
    lineage = _sample_lineage()
    ln.snapshot_revision(
        lineage,
        revision=2,
        hash_hex="c" * 64,
        at="2026-07-03T01:00:00Z",
        author="claude-code-interactive",
    )
    assert len(lineage["revisions"]) == 2
    assert lineage["revisions"][1] == {
        "revision": 2,
        "hash": "c" * 64,
        "created_at": "2026-07-03T01:00:00Z",
        "author": "claude-code-interactive",
    }


def test_snapshot_revision_replaces_existing_revision_in_place():
    lineage = _sample_lineage()
    ln.snapshot_revision(
        lineage,
        revision=1,
        hash_hex="f" * 64,
        at="2026-07-03T02:00:00Z",
        author="devon",
    )
    assert len(lineage["revisions"]) == 1
    assert lineage["revisions"][0] == {
        "revision": 1,
        "hash": "f" * 64,
        "created_at": "2026-07-03T00:00:00Z",
        "snapshotted_at": "2026-07-03T02:00:00Z",
        "author": "devon",
    }


def test_append_approval_grows_list_with_correct_shape():
    lineage = _sample_lineage()
    ln.append_approval(
        lineage,
        revision=1,
        approved_hash="a" * 64,
        approver="devon",
        at="2026-07-03T00:10:00Z",
        commit="deadbeef",
        event_id="evt-9",
    )
    assert len(lineage["approvals"]) == 1
    assert lineage["approvals"][0] == {
        "revision": 1,
        "approved_hash": "a" * 64,
        "approver": "devon",
        "approved_at": "2026-07-03T00:10:00Z",
        "commit": "deadbeef",
        "event_id": "evt-9",
    }
