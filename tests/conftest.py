"""Shared pytest fixtures for intent_packages tests (fixtures added in later tasks)."""

import pytest


@pytest.fixture
def fake_registry(tmp_path):
    """A fake security-standards checkout containing a registry/ dir.

    Layout matches the real registry repo:
        <root>/registry/capabilities.yaml
        <root>/registry/agents/<id>.yaml

    Returns the ROOT (the security-standards checkout dir), i.e. the parent
    of registry/ — this is what SECURITY_STANDARDS_DIR should point at, per
    registry.registry_dir()'s `$SECURITY_STANDARDS_DIR/registry` resolution.
    """
    root = tmp_path / "security-standards"
    registry_path = root / "registry"
    agents_path = registry_path / "agents"
    agents_path.mkdir(parents=True)

    (registry_path / "capabilities.yaml").write_text(
        "schema: capability-vocabulary/v1\n"
        "terms:\n"
        '  repository_read: "read code/files in a repo working tree"\n'
        '  merge_to_main: "merge PRs / push to a default branch"\n',
        encoding="utf-8",
    )
    (agents_path / "devon.yaml").write_text(
        "schema: agent-identity/v1\n"
        "agent_id: devon\n"
        "authority_profile: human-operator-v1\n",
        encoding="utf-8",
    )
    (agents_path / "claude-code-interactive.yaml").write_text(
        "schema: agent-identity/v1\n"
        "agent_id: claude-code-interactive\n"
        "authority_profile: interactive-dev-v1\n",
        encoding="utf-8",
    )
    return root
