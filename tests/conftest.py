"""Shared pytest fixtures for intent_packages tests (fixtures added in later tasks)."""

from pathlib import Path

import pytest
import yaml

# A complete, valid universal intent package (schema_version 1), matching
# .superpowers/sdd/task-7-valid-package-reference.yaml. package_id is set to
# "sample-valid-package" to match the valid_package fixture's directory name.
_VALID_PACKAGE_YAML = """\
schema_version: 1
package_id: sample-valid-package
title: "A sample valid intent package"
revision: 1
status: draft
reach: ["source_repository"]
created_by: claude-code-interactive
owner: devon
created_at: "2026-07-03T00:00:00Z"
supersedes: null
outcome:
  what: "The universal envelope validates end to end."
  why: "To prove the schema and validator work."
  beneficiary: "The software factory."
  success_signal: "validate returns no errors."
scope:
  included: ["the universal envelope"]
  excluded: ["domain profiles"]
  non_goals: ["building the orchestrator"]
  assumptions: ["python 3.12 available"]
  open_questions: []
sources:
  - location: "companion §4"
    authority_level: authoritative
    required_version: "2026-06-30"
    trust: trusted_instruction
    sensitivity: internal
constraints:
  time_budget: null
  technology: "Python 3.12+"
  policy_legal: null
  privacy_security: null
  compatibility: null
  quality_accessibility: null
  operational: null
  other: []
acceptance:
  - id: AC-001
    condition: "validate returns zero errors on this package"
    evidence_type: automated_test
    evidence: "pytest test_validate_structure.py::test_valid_package_has_no_errors passes"
    approver: policy
deliverables:
  artifacts: ["the validated package"]
  destination: "packages/"
  recipient: "devon"
  definition_of_done: "validate passes"
  operator_responsibilities: []
dependencies:
  predecessor_packages: []
  external_decisions: []
  required_people_systems: []
  required_capabilities: []
  blocking_conditions: []
authority:
  allowed: [repository_read, repository_write, test_execution]
  requires_approval: [merge_to_main]
  prohibited: [secret_write]
  budgets:
    max_attempts: null
    max_llm_calls: null
risk:
  failure_modes: ["schema drift"]
  max_impact: "low"
  stop_conditions: ["validate errors"]
  rollback: "revert the package file"
  escalation_target: "devon"
verification:
  independent_review: []
  non_mechanical: []
follow_up:
  required: false
  revisit_when: null
  signals: []
  owner: null
applicable_standards:
  project: "1.0"
"""


# A complete, valid software-delivery-profile package. Mirrors _VALID_PACKAGE_YAML's
# shape but declares `profile: software-delivery` + a valid `profile_fields`, and
# every acceptance item's evidence carries a recognized producer tag with a matching
# evidence_type (WS-2.2 spec §3).
_SOFTWARE_DELIVERY_PACKAGE_YAML = """\
schema_version: 1
package_id: sample-software-delivery-package
title: "A sample software-delivery profile package"
revision: 1
status: draft
reach: ["source_repository"]
created_by: claude-code-interactive
owner: devon
created_at: "2026-07-03T00:00:00Z"
supersedes: null
profile: software-delivery
profile_fields:
  repo: "AlobarQuest/intent-packages"
  branch: "feat/ws22-domain-profiles"
  deploy_target: "coolify:intent-packages-prod"
  required_checks:
    - "ci:validate.yml"
    - "ci:pytest"
  rollback_plan: "git revert; redeploy prior image"
outcome:
  what: "The software-delivery profile validates end to end."
  why: "To prove the profile validator works."
  beneficiary: "The software factory."
  success_signal: "validate returns no errors."
scope:
  included: ["the software-delivery profile"]
  excluded: ["other profiles"]
  non_goals: ["building the orchestrator"]
  assumptions: ["python 3.12 available"]
  open_questions: []
sources:
  - location: "WS-2.2 design spec"
    authority_level: authoritative
    required_version: "2026-07-04"
    trust: trusted_instruction
    sensitivity: internal
constraints:
  time_budget: null
  technology: "Python 3.12+"
  policy_legal: null
  privacy_security: null
  compatibility: null
  quality_accessibility: null
  operational: null
  other: []
acceptance:
  - id: AC-001
    condition: "CI validates the profile module"
    evidence_type: automated_test
    evidence: "ci: validate.yml passes on PR"
    approver: policy
deliverables:
  artifacts: ["the validated package"]
  destination: "packages/"
  recipient: "devon"
  definition_of_done: "validate passes"
  operator_responsibilities: []
dependencies:
  predecessor_packages: []
  external_decisions: []
  required_people_systems: []
  required_capabilities: []
  blocking_conditions: []
authority:
  allowed: [repository_read, repository_write, test_execution]
  requires_approval: [merge_to_main]
  prohibited: [secret_write]
  budgets:
    max_attempts: null
    max_llm_calls: null
risk:
  failure_modes: ["schema drift"]
  max_impact: "low"
  stop_conditions: ["validate errors"]
  rollback: "revert the package file"
  escalation_target: "devon"
verification:
  independent_review: []
  non_mechanical: []
follow_up:
  required: false
  revisit_when: null
  signals: []
  owner: null
applicable_standards:
  project: "1.0"
"""


# A complete, valid infrastructure-change-profile package (WS-2.2 spec §4).
_INFRASTRUCTURE_CHANGE_PACKAGE_YAML = """\
schema_version: 1
package_id: sample-infrastructure-change-package
title: "A sample infrastructure-change profile package"
revision: 1
status: draft
reach: ["source_repository"]
created_by: claude-code-interactive
owner: devon
created_at: "2026-07-03T00:00:00Z"
supersedes: null
profile: infrastructure-change
profile_fields:
  blast_radius: single-app
  change_window: null
  backup_evidence: "vps-backup recipe D run 2026-07-04"
  rollback_plan: "restore from pre-change snapshot"
outcome:
  what: "The infrastructure-change profile validates end to end."
  why: "To prove the profile validator works."
  beneficiary: "The software factory."
  success_signal: "validate returns no errors."
scope:
  included: ["the infrastructure-change profile"]
  excluded: ["other profiles"]
  non_goals: ["building the orchestrator"]
  assumptions: ["python 3.12 available"]
  open_questions: []
sources:
  - location: "WS-2.2 design spec"
    authority_level: authoritative
    required_version: "2026-07-04"
    trust: trusted_instruction
    sensitivity: internal
constraints:
  time_budget: null
  technology: "Python 3.12+"
  policy_legal: null
  privacy_security: null
  compatibility: null
  quality_accessibility: null
  operational: null
  other: []
acceptance:
  - id: AC-001
    condition: "the change is healthy after applying"
    evidence_type: automated_test
    evidence: "health: /api/health 200 after change"
    approver: policy
deliverables:
  artifacts: ["the validated package"]
  destination: "packages/"
  recipient: "devon"
  definition_of_done: "validate passes"
  operator_responsibilities: []
dependencies:
  predecessor_packages: []
  external_decisions: []
  required_people_systems: []
  required_capabilities: []
  blocking_conditions: []
authority:
  allowed: [repository_read, infra_mutation, test_execution]
  requires_approval: [merge_to_main]
  prohibited: [secret_write]
  budgets:
    max_attempts: null
    max_llm_calls: null
risk:
  failure_modes: ["change breaks a dependent service"]
  max_impact: "low"
  stop_conditions: ["health check fails post-change"]
  rollback: "restore from pre-change snapshot"
  escalation_target: "devon"
verification:
  independent_review: []
  non_mechanical: []
follow_up:
  required: false
  revisit_when: null
  signals: []
  owner: null
applicable_standards:
  project: "1.0"
"""


# A complete, valid dependency-update-profile package (WS-P2.10 task 6/9).
_DEPENDENCY_UPDATE_PACKAGE_YAML = """\
schema_version: 1
package_id: sample-dependency-update-package
title: "A sample dependency-update profile package"
revision: 1
status: draft
reach: ["source_repository"]
created_by: claude-code-interactive
owner: devon
created_at: "2026-07-03T00:00:00Z"
supersedes: null
profile: dependency-update
profile_fields:
  target_repo: "AlobarQuest/intent-packages"
  package: "requests"
  from_version: "2.31.0"
  to_version: "2.32.0"
outcome:
  what: "The dependency-update profile validates end to end."
  why: "To prove the profile validator works."
  beneficiary: "The software factory."
  success_signal: "validate returns no errors."
scope:
  included: ["the dependency-update profile"]
  excluded: ["other profiles"]
  non_goals: ["building the orchestrator"]
  assumptions: ["python 3.12 available"]
  open_questions: []
sources:
  - location: "WS-P2.10 design spec"
    authority_level: authoritative
    required_version: "2026-07-04"
    trust: trusted_instruction
    sensitivity: internal
constraints:
  time_budget: null
  technology: "Python 3.12+"
  policy_legal: null
  privacy_security: null
  compatibility: null
  quality_accessibility: null
  operational: null
  other: []
acceptance:
  - id: AC-001
    condition: "the target repo's named check passes on the PR head"
    evidence_type: automated_check
    evidence: "ci: named check passes on the PR head"
    approver: policy
  - id: AC-002
    condition: "a human confirms the version bump is safe to ship"
    evidence_type: human_review
    evidence: "human: reviewed changelog and confirmed no breaking changes"
    approver: policy
deliverables:
  artifacts: ["the validated package"]
  destination: "packages/"
  recipient: "devon"
  definition_of_done: "validate passes"
  operator_responsibilities: []
dependencies:
  predecessor_packages: []
  external_decisions: []
  required_people_systems: []
  required_capabilities: []
  blocking_conditions: []
authority:
  allowed: [repository_read, repository_write, test_execution]
  requires_approval: [merge_to_main]
  prohibited: [secret_write]
  budgets:
    max_attempts: null
    max_llm_calls: null
risk:
  failure_modes: ["schema drift"]
  max_impact: "low"
  stop_conditions: ["validate errors"]
  rollback: "revert the package file"
  escalation_target: "devon"
verification:
  independent_review: []
  non_mechanical: []
follow_up:
  required: false
  revisit_when: null
  signals: []
  owner: null
applicable_standards:
  project: "1.0"
"""


# A complete, valid maintenance-remediation-profile package (WS-P2.10 task 7).
_MAINTENANCE_REMEDIATION_PACKAGE_YAML = """\
schema_version: 1
package_id: sample-maintenance-remediation-package
title: "A sample maintenance-remediation profile package"
revision: 1
status: draft
reach: ["source_repository"]
created_by: claude-code-interactive
owner: devon
created_at: "2026-07-03T00:00:00Z"
supersedes: null
profile: maintenance-remediation
profile_fields:
  repo: "AlobarQuest/intent-packages"
  remediation_source: "backlog item WS-P3.2-drift-7"
  rollback_plan: "git revert the remediation commit"
outcome:
  what: "The maintenance-remediation profile validates end to end."
  why: "To prove the profile validator works."
  beneficiary: "The software factory."
  success_signal: "validate returns no errors."
scope:
  included: ["the maintenance-remediation profile"]
  excluded: ["other profiles"]
  non_goals: ["building the orchestrator"]
  assumptions: ["python 3.12 available"]
  open_questions: []
sources:
  - location: "WS-P2.10 design spec"
    authority_level: authoritative
    required_version: "2026-07-04"
    trust: trusted_instruction
    sensitivity: internal
constraints:
  time_budget: null
  technology: "Python 3.12+"
  policy_legal: null
  privacy_security: null
  compatibility: null
  quality_accessibility: null
  operational: null
  other: []
acceptance:
  - id: AC-001
    condition: "the target repo's named check passes on the PR head"
    evidence_type: automated_check
    evidence: "ci: named check passes on the PR head"
    approver: policy
  - id: AC-002
    condition: "a human confirms the handoff item is closed"
    evidence_type: human_review
    evidence: "human: confirmed the remediation closes the handoff item"
    approver: policy
deliverables:
  artifacts: ["the validated package"]
  destination: "packages/"
  recipient: "devon"
  definition_of_done: "validate passes"
  operator_responsibilities: []
dependencies:
  predecessor_packages: []
  external_decisions: []
  required_people_systems: []
  required_capabilities: []
  blocking_conditions: []
authority:
  allowed: [repository_read, repository_write, test_execution]
  requires_approval: [merge_to_main]
  prohibited: [secret_write]
  budgets:
    max_attempts: null
    max_llm_calls: null
risk:
  failure_modes: ["schema drift"]
  max_impact: "low"
  stop_conditions: ["validate errors"]
  rollback: "revert the package file"
  escalation_target: "devon"
verification:
  independent_review: []
  non_mechanical: []
follow_up:
  required: false
  revisit_when: null
  signals: []
  owner: null
applicable_standards:
  project: "1.0"
"""


# A complete, valid non-software-operational-profile package (WS-P2.10 task 8).
_NON_SOFTWARE_OPERATIONAL_PACKAGE_YAML = """\
schema_version: 1
package_id: sample-non-software-operational-package
title: "A sample non-software-operational profile package"
revision: 1
status: draft
reach: ["source_repository"]
created_by: claude-code-interactive
owner: devon
created_at: "2026-07-03T00:00:00Z"
supersedes: null
profile: non-software-operational
profile_fields:
  owner: "devon"
  operating_procedure: "listing launch checklist v1"
  external_systems: ["mls", "zillow"]
outcome:
  what: "The non-software-operational profile validates end to end."
  why: "To prove the profile validator works."
  beneficiary: "The software factory."
  success_signal: "validate returns no errors."
scope:
  included: ["the non-software-operational profile"]
  excluded: ["other profiles"]
  non_goals: ["building the orchestrator"]
  assumptions: ["python 3.12 available"]
  open_questions: []
sources:
  - location: "WS-P2.10 design spec"
    authority_level: authoritative
    required_version: "2026-07-04"
    trust: trusted_instruction
    sensitivity: internal
constraints:
  time_budget: null
  technology: "Python 3.12+"
  policy_legal: null
  privacy_security: null
  compatibility: null
  quality_accessibility: null
  operational: null
  other: []
acceptance:
  - id: AC-001
    condition: "a human confirms the operating procedure was followed"
    evidence_type: human_review
    evidence: "human: confirmed the operating procedure was followed"
    approver: policy
  - id: AC-002
    condition: "the external system confirms the listing is live"
    evidence_type: external_attestation
    evidence: "external: MLS confirms the listing is live"
    approver: "external:mls-vendor"
  - id: AC-003
    condition: "days-on-market signal is observed post-launch"
    evidence_type: observation
    evidence: "observation: days-on-market tracked for 30 days"
    approver: policy
deliverables:
  artifacts: ["the validated package"]
  destination: "packages/"
  recipient: "devon"
  definition_of_done: "validate passes"
  operator_responsibilities: []
dependencies:
  predecessor_packages: []
  external_decisions: []
  required_people_systems: []
  required_capabilities: []
  blocking_conditions: []
authority:
  allowed: [repository_read, repository_write, test_execution]
  requires_approval: [merge_to_main]
  prohibited: [secret_write]
  budgets:
    max_attempts: null
    max_llm_calls: null
risk:
  failure_modes: ["schema drift"]
  max_impact: "low"
  stop_conditions: ["validate errors"]
  rollback: "revert the package file"
  escalation_target: "devon"
verification:
  independent_review: []
  non_mechanical: []
follow_up:
  required: false
  revisit_when: null
  signals: []
  owner: null
applicable_standards:
  project: "1.0"
"""


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, data) -> None:
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _hermetic_registry_env(monkeypatch, tmp_path):
    """Force `registry.registry_dir()` to resolve to None by default, so the
    suite never depends on whatever security-standards checkout (or lack of
    one) happens to exist on the host running the tests.

    Points SECURITY_STANDARDS_DIR at a guaranteed-absent path (a
    `registry/`-less subdir of this test's own tmp_path). Per
    `registry.registry_dir()`, a set SECURITY_STANDARDS_DIR is authoritative
    with no fallback, so this reliably yields a `None` registry everywhere.

    Tests that want the registry present opt in via the `fake_registry`
    fixture plus their own `monkeypatch.setenv("SECURITY_STANDARDS_DIR", ...)`
    call in the test body — that call runs after fixture setup and so wins
    over this default.
    """
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path / "no-registry-here"))


@pytest.fixture
def valid_package(tmp_path):
    """Write a complete, valid packages/sample-valid-package/ dir (package.yaml
    + a matching lineage.yaml whose revision-1 hash is the package's real
    hash). Returns the package dir path."""
    from intent_packages import canonical, loader

    pkg_dir = tmp_path / "packages" / "sample-valid-package"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(_VALID_PACKAGE_YAML, encoding="utf-8")

    package_hash = canonical.package_hash(loader.load_package(pkg_dir))
    lineage = {
        "package_id": "sample-valid-package",
        "current_state": "draft",
        "revisions": [
            {
                "revision": 1,
                "hash": package_hash,
                "created_at": "2026-07-03T00:00:00Z",
                "author": "claude-code-interactive",
            }
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }
    _write_yaml(pkg_dir / "lineage.yaml", lineage)

    return pkg_dir


@pytest.fixture
def replacement_package(valid_package):
    """Create a package that correctly points back to valid_package."""
    pkg_dir = valid_package.parent / "sample-replacement-package"
    pkg_dir.mkdir()
    package = _read_yaml(valid_package / "package.yaml")
    package["package_id"] = "sample-replacement-package"
    package["supersedes"] = "sample-valid-package"
    _write_yaml(pkg_dir / "package.yaml", package)
    return pkg_dir


@pytest.fixture
def software_delivery_package(tmp_path):
    """Write a complete, valid packages/sample-software-delivery-package/ dir
    (profile: software-delivery), mirroring the `valid_package` fixture."""
    from intent_packages import canonical, loader

    pkg_dir = tmp_path / "packages" / "sample-software-delivery-package"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(_SOFTWARE_DELIVERY_PACKAGE_YAML, encoding="utf-8")

    package_hash = canonical.package_hash(loader.load_package(pkg_dir))
    lineage = {
        "package_id": "sample-software-delivery-package",
        "current_state": "draft",
        "revisions": [
            {
                "revision": 1,
                "hash": package_hash,
                "created_at": "2026-07-03T00:00:00Z",
                "author": "claude-code-interactive",
            }
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }
    _write_yaml(pkg_dir / "lineage.yaml", lineage)

    return pkg_dir


@pytest.fixture
def infrastructure_change_package(tmp_path):
    """Write a complete, valid packages/sample-infrastructure-change-package/ dir
    (profile: infrastructure-change), mirroring the `valid_package` fixture."""
    from intent_packages import canonical, loader

    pkg_dir = tmp_path / "packages" / "sample-infrastructure-change-package"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(_INFRASTRUCTURE_CHANGE_PACKAGE_YAML, encoding="utf-8")

    package_hash = canonical.package_hash(loader.load_package(pkg_dir))
    lineage = {
        "package_id": "sample-infrastructure-change-package",
        "current_state": "draft",
        "revisions": [
            {
                "revision": 1,
                "hash": package_hash,
                "created_at": "2026-07-03T00:00:00Z",
                "author": "claude-code-interactive",
            }
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }
    _write_yaml(pkg_dir / "lineage.yaml", lineage)

    return pkg_dir


@pytest.fixture
def dependency_update_package(tmp_path):
    """Write a complete, valid packages/sample-dependency-update-package/ dir
    (profile: dependency-update), mirroring the `valid_package` fixture."""
    from intent_packages import canonical, loader

    pkg_dir = tmp_path / "packages" / "sample-dependency-update-package"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(_DEPENDENCY_UPDATE_PACKAGE_YAML, encoding="utf-8")

    package_hash = canonical.package_hash(loader.load_package(pkg_dir))
    lineage = {
        "package_id": "sample-dependency-update-package",
        "current_state": "draft",
        "revisions": [
            {
                "revision": 1,
                "hash": package_hash,
                "created_at": "2026-07-03T00:00:00Z",
                "author": "claude-code-interactive",
            }
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }
    _write_yaml(pkg_dir / "lineage.yaml", lineage)

    return pkg_dir


@pytest.fixture
def maintenance_remediation_package(tmp_path):
    """Write a complete, valid packages/sample-maintenance-remediation-package/
    dir (profile: maintenance-remediation), mirroring the `valid_package`
    fixture."""
    from intent_packages import canonical, loader

    pkg_dir = tmp_path / "packages" / "sample-maintenance-remediation-package"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(_MAINTENANCE_REMEDIATION_PACKAGE_YAML, encoding="utf-8")

    package_hash = canonical.package_hash(loader.load_package(pkg_dir))
    lineage = {
        "package_id": "sample-maintenance-remediation-package",
        "current_state": "draft",
        "revisions": [
            {
                "revision": 1,
                "hash": package_hash,
                "created_at": "2026-07-03T00:00:00Z",
                "author": "claude-code-interactive",
            }
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }
    _write_yaml(pkg_dir / "lineage.yaml", lineage)

    return pkg_dir


@pytest.fixture
def non_software_operational_package(tmp_path):
    """Write a complete, valid
    packages/sample-non-software-operational-package/ dir (profile:
    non-software-operational), mirroring the `valid_package` fixture."""
    from intent_packages import canonical, loader

    pkg_dir = tmp_path / "packages" / "sample-non-software-operational-package"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(_NON_SOFTWARE_OPERATIONAL_PACKAGE_YAML, encoding="utf-8")

    package_hash = canonical.package_hash(loader.load_package(pkg_dir))
    lineage = {
        "package_id": "sample-non-software-operational-package",
        "current_state": "draft",
        "revisions": [
            {
                "revision": 1,
                "hash": package_hash,
                "created_at": "2026-07-03T00:00:00Z",
                "author": "claude-code-interactive",
            }
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }
    _write_yaml(pkg_dir / "lineage.yaml", lineage)

    return pkg_dir


@pytest.fixture
def edit_yaml():
    """Mutate a copy of a package's YAML file for negative tests.

    edit_yaml(pkg_dir, filename, set_raw="bogus_key: 1")
        Appends a raw YAML line to the file (e.g. to introduce an unknown
        top-level key, or a bare float at the top level).

    edit_yaml(pkg_dir, filename, set_key=("package_id", "wrong"))
        Loads the YAML, sets a top-level key to a value, re-dumps.

    edit_yaml(pkg_dir, filename, set_nested=(("acceptance", 0, "approver"), "external:seller"))
        Loads the YAML, walks a path of dict-keys/list-indices, sets the
        final key to a value, re-dumps.
    """

    def _edit(pkg_dir, filename, *, set_raw=None, set_key=None, set_nested=None):
        path = Path(pkg_dir) / filename

        if set_raw is not None:
            with path.open("a", encoding="utf-8") as f:
                f.write("\n" + set_raw + "\n")
            return

        data = _read_yaml(path)

        if set_key is not None:
            key, value = set_key
            data[key] = value

        if set_nested is not None:
            key_path, value = set_nested
            node = data
            for part in key_path[:-1]:
                node = node[part]
            node[key_path[-1]] = value

        _write_yaml(path, data)

    return _edit


@pytest.fixture
def drop_key():
    """Delete a (possibly nested) key from a package's YAML file.

    drop_key(pkg_dir, filename, "acceptance", 0, "approver")
        Deletes acceptance[0].approver.
    """

    def _drop(pkg_dir, filename, *key_path):
        path = Path(pkg_dir) / filename
        data = _read_yaml(path)
        node = data
        for part in key_path[:-1]:
            node = node[part]
        del node[key_path[-1]]
        _write_yaml(path, data)

    return _drop


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
        '  repository_write: "write code/files in a repo working tree"\n'
        '  test_execution: "run a test suite"\n'
        '  merge_to_main: "merge PRs / push to a default branch"\n'
        '  secret_write: "write/rotate a secret"\n',
        encoding="utf-8",
    )
    (agents_path / "devon.yaml").write_text(
        "schema: agent-identity/v1\nagent_id: devon\nauthority_profile: human-operator-v1\n",
        encoding="utf-8",
    )
    (agents_path / "claude-code-interactive.yaml").write_text(
        "schema: agent-identity/v1\n"
        "agent_id: claude-code-interactive\n"
        "authority_profile: interactive-dev-v1\n",
        encoding="utf-8",
    )
    return root
