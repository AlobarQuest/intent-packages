"""Task 8: cross-file semantic checks (S/H/T/L) + the O/registry warnings.

`valid_package` already covers the passing case for every check below (it
stays `== []` through `test_validate_structure.test_valid_package_has_no_errors`);
each test here mutates one specific thing and asserts the resulting error
(or, for O/registry, the warning) names the right fields/wording.
"""

from intent_packages.validate import validate_package, validate_warnings

# ---------------------------------------------------------------------------
# check S — status mirror
# ---------------------------------------------------------------------------


def test_status_lineage_mismatch_is_rejected(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("status", "ready_for_review"))
    # lineage.yaml current_state is left at "draft" (the fixture default).
    errs = validate_package(valid_package)
    assert any("status" in e and "current_state" in e for e in errs)


# ---------------------------------------------------------------------------
# check H — hash drift
# ---------------------------------------------------------------------------


def test_hash_drift_pre_execution_says_revise(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("status", "ready_for_review"))
    edit_yaml(valid_package, "lineage.yaml", set_key=("current_state", "ready_for_review"))
    # Change intent content (not status) so the live hash no longer matches
    # the recorded revision-1 hash.
    edit_yaml(valid_package, "package.yaml", set_key=("title", "A drifted title"))

    errs = validate_package(valid_package)
    assert any("revise" in e for e in errs)


def test_hash_drift_post_execution_says_superseding(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("status", "in_execution"))
    edit_yaml(valid_package, "lineage.yaml", set_key=("current_state", "in_execution"))
    edit_yaml(valid_package, "package.yaml", set_key=("title", "A drifted title"))

    errs = validate_package(valid_package)
    assert any("superseding" in e for e in errs)


def test_no_drift_error_when_hash_matches_recorded_revision(valid_package, edit_yaml):
    # status alone is excluded from the hash, so moving into a drift-locked
    # state without touching any other field must NOT trigger check H.
    edit_yaml(valid_package, "package.yaml", set_key=("status", "ready_for_review"))
    edit_yaml(valid_package, "lineage.yaml", set_key=("current_state", "ready_for_review"))

    errs = validate_package(valid_package)
    assert not any("revise" in e or "superseding" in e for e in errs)


# ---------------------------------------------------------------------------
# check T — authority envelope
# ---------------------------------------------------------------------------


def test_authority_term_in_two_lists_is_rejected(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("authority", "prohibited"), ["secret_write", "merge_to_main"]),
    )
    errs = validate_package(valid_package)
    assert any("merge_to_main" in e and "more than one" in e for e in errs)


def test_authority_term_duplicated_within_one_list_is_rejected(valid_package, edit_yaml):
    # Same term twice in the SAME list (and nowhere else — merge_to_main is
    # deliberately avoided since the fixture default already has it in
    # requires_approval, which would make this a cross-list case instead)
    # must get its own accurate, non-misleading message — not the cross-list
    # "more than one list" wording, since only one list is involved.
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("authority", "requires_approval"), ["merge_to_main", "merge_to_main"]),
    )
    errs = validate_package(valid_package)
    assert any(
        "authority.requires_approval" in e
        and "merge_to_main" in e
        and "listed more than once" in e
        and "more than one" not in e
        for e in errs
    )


def test_authority_out_of_vocab_term_is_rejected(
    valid_package, edit_yaml, fake_registry, monkeypatch
):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(
            ("authority", "allowed"),
            ["repository_read", "repository_write", "test_execution", "not_a_real_term"],
        ),
    )
    errs = validate_package(valid_package)
    assert any("not_a_real_term" in e and "registry PR" in e for e in errs)


def test_authority_unknown_term_skipped_when_registry_absent(
    valid_package, edit_yaml, monkeypatch, tmp_path
):
    # Force the registry to be absent regardless of the host machine's
    # checkout state, so this test is deterministic everywhere.
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path / "no-such-checkout"))
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(
            ("authority", "allowed"),
            ["repository_read", "repository_write", "test_execution", "not_a_real_term"],
        ),
    )
    errs = validate_package(valid_package)
    assert not any("not_a_real_term" in e for e in errs)


def test_valid_package_authority_terms_pass_with_fake_registry(
    valid_package, fake_registry, monkeypatch
):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    assert validate_package(valid_package) == []


# ---------------------------------------------------------------------------
# check L — lineage consistency
# ---------------------------------------------------------------------------


def test_lineage_illegal_transition_edge_is_rejected(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "lineage.yaml",
        set_key=(
            "transitions",
            [
                {
                    "kind": "transition",
                    "from": "in_execution",
                    "to": "draft",
                    "at": "2026-07-03T00:05:00Z",
                    "actor": "claude-code-interactive",
                    "event_id": None,
                }
            ],
        ),
    )
    errs = validate_package(valid_package)
    assert any("not a legal transition" in e for e in errs)


def test_lineage_revision_kind_exempt_from_edge_check(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "lineage.yaml",
        set_key=(
            "transitions",
            [
                {
                    "kind": "revision",
                    "from": "in_execution",
                    "to": "draft",
                    "at": "2026-07-03T00:05:00Z",
                    "actor": "claude-code-interactive",
                    "event_id": None,
                }
            ],
        ),
    )
    assert validate_package(valid_package) == []


def test_lineage_zero_revisions_is_rejected(valid_package, edit_yaml):
    edit_yaml(valid_package, "lineage.yaml", set_key=("revisions", []))
    errs = validate_package(valid_package)
    assert any("revisions" in e and "non-empty" in e for e in errs)


def test_lineage_duplicate_revision_is_rejected(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "lineage.yaml",
        set_key=(
            "revisions",
            [
                {
                    "revision": 1,
                    "hash": "a" * 64,
                    "created_at": "2026-07-03T00:00:00Z",
                    "author": "claude-code-interactive",
                },
                {
                    "revision": 1,
                    "hash": "b" * 64,
                    "created_at": "2026-07-03T00:01:00Z",
                    "author": "claude-code-interactive",
                },
            ],
        ),
    )
    errs = validate_package(valid_package)
    assert any("duplicate" in e for e in errs)


def test_lineage_bad_current_state_is_rejected(valid_package, edit_yaml):
    edit_yaml(valid_package, "lineage.yaml", set_key=("current_state", "not_a_real_state"))
    errs = validate_package(valid_package)
    assert any("not_a_real_state" in e and "legal lifecycle state" in e for e in errs)


def test_lineage_approval_references_missing_revision(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "lineage.yaml",
        set_key=(
            "approvals",
            [
                {
                    "revision": 7,
                    "approved_hash": "c" * 64,
                    "approver": "devon",
                    "approved_at": "2026-07-03T00:10:00Z",
                    "commit": "deadbeef",
                    "event_id": None,
                }
            ],
        ),
    )
    errs = validate_package(valid_package)
    assert any("does not reference an existing revision" in e for e in errs)


def test_lineage_approval_hash_mismatch_is_rejected(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "lineage.yaml",
        set_key=(
            "approvals",
            [
                {
                    "revision": 1,
                    "approved_hash": "c" * 64,
                    "approver": "devon",
                    "approved_at": "2026-07-03T00:10:00Z",
                    "commit": "deadbeef",
                    "event_id": None,
                }
            ],
        ),
    )
    errs = validate_package(valid_package)
    assert any("approved_hash does not match" in e for e in errs)


def test_lineage_grants_must_be_a_list(valid_package, edit_yaml):
    edit_yaml(valid_package, "lineage.yaml", set_key=("grants", "not-a-list"))
    errs = validate_package(valid_package)
    assert any("grants" in e and "must be a list" in e for e in errs)


# ---------------------------------------------------------------------------
# cross_file_errors plumbing — missing/unreadable lineage.yaml
# ---------------------------------------------------------------------------


def test_missing_lineage_yaml_is_reported_as_a_lineage_error(valid_package):
    # No lineage.yaml at all: cross_file_errors' `except (LoadError, OSError)`
    # branch must catch the read failure and surface a single, sensible
    # lineage.yaml-prefixed error rather than raising or silently passing.
    (valid_package / "lineage.yaml").unlink()

    errs = validate_package(valid_package)
    assert any(e.startswith("lineage.yaml:") for e in errs)
    # Check T (registry-independent, no lineage needed) still runs — the
    # valid package's authority envelope has no duplicate/cross-list terms,
    # so no package.yaml errors should appear here.
    assert not any(e.startswith("package.yaml:") for e in errs)


# ---------------------------------------------------------------------------
# check O + registry-absence — warnings, NOT errors
# ---------------------------------------------------------------------------


def test_open_questions_is_a_warning_not_an_error(valid_package, edit_yaml):
    edit_yaml(
        valid_package,
        "package.yaml",
        set_nested=(("scope", "open_questions"), ["what about X?"]),
    )
    assert validate_package(valid_package) == []
    warnings = validate_warnings(valid_package)
    assert any("open question" in w and "approve will refuse" in w for w in warnings)


def test_no_open_questions_warning_when_list_is_empty(valid_package):
    warnings = validate_warnings(valid_package)
    assert not any("open question" in w for w in warnings)


def test_registry_absent_note_is_a_warning(valid_package, monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path / "no-such-checkout"))
    assert validate_package(valid_package) == []
    warnings = validate_warnings(valid_package)
    assert any("registry not found" in w for w in warnings)


def test_registry_present_no_absence_note(valid_package, fake_registry, monkeypatch):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    warnings = validate_warnings(valid_package)
    assert not any("registry not found" in w for w in warnings)
