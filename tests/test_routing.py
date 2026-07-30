"""Routing policy loader (WS-P2.10): shape validation, seed-content pins, and
fail-closed lookups. The repo-root routing-policy.toml is the sole source of
model selection (program exit criterion #11)."""

import pytest

from intent_packages import routing

EXPECTED_SURFACE_IDS = {
    "intent-authoring",
    "decomposition-proposals",
    "runner-implementation",
    "local-heavy",
    "judgment-ac-verification",
    "guarded-infra-agent",
    "lesson-proposals",
    "high-volume-text",
}


def test_default_path_is_repo_root_file():
    path = routing.default_policy_path()
    assert path.name == "routing-policy.toml"
    assert path.is_file()


def test_load_policy_parses_the_seed():
    """Pins the live policy. The version and the class set move together, deliberately:
    every tier change is a versioned edit to that file, so a class added without a
    version bump reds here rather than passing quietly."""
    policy = routing.load_policy()
    assert policy.version == 2
    assert set(policy.surfaces) == EXPECTED_SURFACE_IDS
    assert set(policy.change_classes) == {
        "dependency-update",
        "maintenance-remediation",
        "software-delivery",
    }
    assert len(policy.no_llm) == 10


def test_every_model_slug_resolves_to_an_api_id():
    policy = routing.load_policy()
    for row in list(policy.surfaces.values()) + list(policy.change_classes.values()):
        assert len(row.models) == len(row.model_ids) >= 1
        for slug, model_id in zip(row.models, row.model_ids, strict=True):
            assert policy.models[slug] == model_id


def test_dual_model_row_carries_both():
    row = routing.resolve_surface(routing.load_policy(), "judgment-ac-verification")
    assert row.models == ("fable-5", "opus-4-8")
    assert row.model_ids == ("claude-fable-5", "claude-opus-4-8")


def test_dependency_update_routes_to_sonnet():
    row = routing.resolve_change_class(routing.load_policy(), "dependency-update")
    assert row.model_ids == ("claude-sonnet-5",)


def test_unknown_surface_fails_closed():
    with pytest.raises(routing.RoutingPolicyError, match="unknown surface"):
        routing.resolve_surface(routing.load_policy(), "nope")


def test_unknown_change_class_fails_closed():
    with pytest.raises(routing.RoutingPolicyError, match="unknown change-class"):
        routing.resolve_change_class(routing.load_policy(), "docs-only")


def test_missing_file_fails_closed(tmp_path):
    with pytest.raises(routing.RoutingPolicyError, match="not found"):
        routing.load_policy(tmp_path / "absent.toml")


def test_unknown_model_slug_fails_at_load(tmp_path):
    bad = tmp_path / "p.toml"
    bad.write_text(
        'version = 1\n[models]\nsonnet-5 = "claude-sonnet-5"\n'
        "[no_llm]\nitems = []\n"
        '[[surface]]\nid = "s"\nmodels = ["mystery-9"]\nwhere = "w"\n'
        'rationale = "r"\ndecided = "2026-07-29"\n',
        encoding="utf-8",
    )
    with pytest.raises(routing.RoutingPolicyError, match="mystery-9"):
        routing.load_policy(bad)


def test_change_class_must_reference_known_surface(tmp_path):
    bad = tmp_path / "p.toml"
    bad.write_text(
        'version = 1\n[models]\nsonnet-5 = "claude-sonnet-5"\n'
        "[no_llm]\nitems = []\n"
        '[[surface]]\nid = "s"\nmodels = ["sonnet-5"]\nwhere = "w"\n'
        'rationale = "r"\ndecided = "2026-07-29"\n'
        '[change_class.x]\nsurface = "ghost"\nmodels = ["sonnet-5"]\n'
        'rationale = "r"\ndecided = "2026-07-29"\n',
        encoding="utf-8",
    )
    with pytest.raises(routing.RoutingPolicyError, match="ghost"):
        routing.load_policy(bad)
