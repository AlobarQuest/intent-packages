"""Adapter for the agent registry maintained in the (separate) security-standards repo.

The registry provides two things this package needs for authority-envelope
validation:
  - a capability vocabulary (registry/capabilities.yaml) — the valid terms a
    package's authority envelope may reference.
  - agent identities (registry/agents/<id>.yaml) — used to check whether an
    approver is a known agent, and whether it is a human operator.

The registry lives in a separate repo/checkout and is not guaranteed to be
present (e.g. other machines, CI). Every function here must tolerate that:
absence degrades to None/False, never an exception.
"""

from __future__ import annotations

import os
from pathlib import Path

from intent_packages.loader import LoadError, load_yaml_strict

_HUMAN_OPERATOR_PROFILE = "human-operator-v1"


def registry_dir() -> Path | None:
    """Locate the registry/ dir.

    If SECURITY_STANDARDS_DIR is set, it is authoritative: use
    $SECURITY_STANDARDS_DIR/registry if that dir exists, else None (no
    fallback — an explicit override that doesn't resolve should not silently
    pick up whatever happens to be checked out at the default location).

    If SECURITY_STANDARDS_DIR is unset, fall back to
    ~/Projects/security-standards/registry if it exists, else None.
    """
    env_dir = os.environ.get("SECURITY_STANDARDS_DIR")
    if env_dir:
        candidate = Path(env_dir) / "registry"
        return candidate if candidate.is_dir() else None

    default_candidate = Path.home() / "Projects" / "security-standards" / "registry"
    return default_candidate if default_candidate.is_dir() else None


def capability_vocabulary() -> set[str] | None:
    """Return the set of valid capability terms, or None if the registry is absent."""
    directory = registry_dir()
    if directory is None:
        return None

    capabilities_file = directory / "capabilities.yaml"
    if not capabilities_file.is_file():
        return None

    try:
        data = load_yaml_strict(capabilities_file.read_text(encoding="utf-8"))
    except LoadError:
        return None

    terms = data.get("terms")
    if not isinstance(terms, dict):
        return None
    return set(terms.keys())


def _agent_file(agent_id: str) -> Path | None:
    directory = registry_dir()
    if directory is None:
        return None
    agent_path = directory / "agents" / f"{agent_id}.yaml"
    return agent_path if agent_path.is_file() else None


def is_registered_agent(agent_id: str) -> bool:
    """True if registry/agents/<agent_id>.yaml exists."""
    return _agent_file(agent_id) is not None


def is_human_operator(agent_id: str) -> bool:
    """True if the agent's identity file declares authority_profile == human-operator-v1."""
    agent_path = _agent_file(agent_id)
    if agent_path is None:
        return False

    try:
        data = load_yaml_strict(agent_path.read_text(encoding="utf-8"))
    except LoadError:
        return False

    return data.get("authority_profile") == _HUMAN_OPERATOR_PROFILE
