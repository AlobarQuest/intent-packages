# WS-2.2 Domain Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `software-delivery` and `infrastructure-change` domain profiles to the intent-packages
validator, extending the WS-2.1 universal envelope via `profile`/`profile_fields` without modifying it.

**Architecture:** A new `intent_packages.profiles` package holds an in-repo registry
(`PROFILES: dict[str, Callable]`) dispatched from `validate_package()` as one more check ("check P").
Each profile module validates its own `profile_fields` sub-schema (reusing the existing `schema.py`
`MapSpec`/`_walk` machinery) and a shared evidence-tag helper that checks every `acceptance[].evidence`
string starts with one of the profile's recognized producer-tag prefixes and that the tag agrees with
the item's `evidence_type`.

**Tech Stack:** Python 3.12+, pytest, ruff (line-length 100). Zero new dependencies.

## Global Constraints

- Never modify `src/intent_packages/schema.py`'s `TOP_SCHEMA`, `canonical.py`, or `lifecycle.py` — the
  universal envelope, hash, and lifecycle must be provably unchanged (AC-002).
- No new top-level `package.yaml` keys. Every profile addition lives under `profile_fields` (already
  reserved and opaque to universal validation) or is a validation rule over the existing
  `acceptance[].evidence`/`evidence_type` fields.
- Evidence tags, exact prefixes (case-sensitive, colon required, optional space after):
  software-delivery = `ci:`, `gate:`, `scan:`, `review:`, `health:`, `human:`;
  infrastructure-change = `health:`, `backup:`, `change-log:`, `human:`.
- Tag → required `evidence_type`: `human:` → `human_review`; every other tag → `automated_test`.
- Ruff line-length 100; match existing module docstring/comment style (see `checks_semantic.py` for the
  house style this codebase already uses for a "layered on top" module).
- Every new test file follows the existing `valid_package` + `edit_yaml`/`drop_key` conftest pattern —
  see **Plan-level note** below.

**Plan-level note (deviation from the design spec's illustrative file layout):** The design spec (§8)
sketched example packages as static YAML files under `tests/fixtures/packages/`. Reading the existing
test suite (`tests/conftest.py`'s `valid_package` fixture + `test_validate_semantic.py`'s use of
`edit_yaml`/`drop_key`) shows the repo's actual, already-established convention is programmatically
generated `tmp_path` packages mutated per-test, not static fixture directories. This plan follows that
convention instead: two new conftest fixtures (`software_delivery_package`, `infrastructure_change_package`)
built the same way as `valid_package`, and every "broken" variant is a one-line `edit_yaml`/`drop_key`
mutation in the test body, exactly like the rest of the suite. This preserves everything the spec's
decision actually required — examples live outside `packages/`, are not real intents, and pytest calls
`validate_package()` directly — it only changes *how* the example YAML is materialized. Flag this to
Devon when handing off the plan for review.

---

### Task 1: Profile dispatch scaffold + wiring into `validate_package`

**Files:**
- Create: `src/intent_packages/profiles/__init__.py`
- Modify: `src/intent_packages/validate.py` (add the check-P call inside `validate_package`)
- Test: `tests/test_profiles_dispatch.py`

**Interfaces:**
- Produces: `intent_packages.profiles.PROFILES: dict[str, Callable[[dict], list[str]]]` (registry, keyed
  by profile name; empty until Tasks 2/3 register real profiles).
- Produces: `intent_packages.profiles.validate_profile(package: dict) -> list[str]` — returns `[]` when
  `package.get("profile")` is `None`; returns a single "unknown profile" error when `package["profile"]`
  is set but not a key in `PROFILES`; otherwise delegates to `PROFILES[name](package)`.
- Consumes (Task 1 only): nothing from other profile modules yet — tests use `monkeypatch.setitem` on
  `profiles.PROFILES` to inject a fake validator function, so this task is testable in total isolation
  from Tasks 2/3.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profiles_dispatch.py`:

```python
"""Task 1: profiles.validate_profile dispatch — unknown-profile error, no-profile
passthrough, and delegation to a registered profile's validate() function.

Uses monkeypatch.setitem on profiles.PROFILES to inject a fake validator, so this
test file has zero dependency on the real software-delivery/infrastructure-change
profiles built in Tasks 2/3.
"""

from intent_packages import profiles
from intent_packages.validate import validate_package


def test_no_profile_key_returns_no_errors():
    assert profiles.validate_profile({"title": "no profile here"}) == []


def test_profile_none_returns_no_errors():
    assert profiles.validate_profile({"profile": None}) == []


def test_unknown_profile_name_is_a_hard_error():
    errs = profiles.validate_profile({"profile": "not-a-real-profile"})
    assert len(errs) == 1
    assert "not-a-real-profile" in errs[0]
    assert "profile" in errs[0]


def test_known_profile_delegates_to_its_validator(monkeypatch):
    calls = []

    def fake_validate(package):
        calls.append(package)
        return ["fake error from the profile validator"]

    monkeypatch.setitem(profiles.PROFILES, "fake-profile", fake_validate)
    pkg = {"profile": "fake-profile", "title": "x"}

    errs = profiles.validate_profile(pkg)

    assert errs == ["fake error from the profile validator"]
    assert calls == [pkg]


def test_validate_package_still_passes_for_universal_only_package(valid_package):
    # valid_package (conftest) has no `profile` key at all — check P must be a
    # complete no-op for it (AC-003's "unaffected" guarantee, proven early).
    assert validate_package(valid_package) == []


def test_validate_package_surfaces_unknown_profile_error(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("profile", "not-a-real-profile"))
    errs = validate_package(valid_package)
    assert any("not-a-real-profile" in e for e in errs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest tests/test_profiles_dispatch.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'intent_packages.profiles'` (or ImportError).

- [ ] **Step 3: Create the profiles package**

Create `src/intent_packages/profiles/__init__.py`:

```python
"""Domain-profile registry and dispatch (WS-2.2 spec §2).

A profile extends the universal intent-package envelope (WS-2.1) via the reserved
`profile`/`profile_fields` keys — it never adds a new top-level `package.yaml` key.
`validate_profile()` is called from `validate.validate_package()` as one more check
(check P) after the universal checks pass.
"""

from __future__ import annotations

from typing import Callable

PROFILES: dict[str, Callable[[dict], list[str]]] = {}


def validate_profile(package: dict) -> list[str]:
    """Check P: dispatch to the named profile's validator, if any.

    Returns [] when `profile` is absent/null (a universal-only package is
    unaffected, per AC-003). Returns a single actionable error naming the
    valid choices when `profile` is set to an unregistered name. Otherwise
    delegates to that profile's own `validate(package) -> list[str]`.
    """
    name = package.get("profile")
    if name is None:
        return []
    if name not in PROFILES:
        return [f"profile: unknown profile {name!r}; valid: {sorted(PROFILES)}"]
    return PROFILES[name](package)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest tests/test_profiles_dispatch.py -v`
Expected: 6 passed.

- [ ] **Step 5: Wire check P into `validate_package`**

In `src/intent_packages/validate.py`, add the import and the check-P call. Add to the imports at the top:

```python
from intent_packages import checks_semantic, profiles, registry
```
(replacing the existing `from intent_packages import checks_semantic, registry` line at line 35).

Then in `validate_package`, add the check-P call right after the existing `_check_acceptance(pkg, errors)`
line:

```python
    errors: list[str] = []
    _check_k_and_j(pkg, errors)
    _scan_forbidden_types(pkg, "", errors)
    if isinstance(pkg, dict):
        _check_package_id(pkg, pkg_dir, errors)
        _check_trust(pkg, errors)
        _check_acceptance(pkg, errors)
        errors.extend(profiles.validate_profile(pkg))
```

- [ ] **Step 6: Run the full test suite to verify nothing broke**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest -q`
Expected: all prior 123 tests plus the 6 new ones pass (129 passed), 0 failed.

- [ ] **Step 7: Lint**

Run: `cd ~/Projects/intent-packages && ruff check .`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
cd ~/Projects/intent-packages
git add src/intent_packages/profiles/__init__.py src/intent_packages/validate.py tests/test_profiles_dispatch.py
git commit -m "feat(ws22): add profile dispatch registry, wire into validate_package as check P"
```

---

### Task 2: Software-delivery profile

**Files:**
- Create: `src/intent_packages/profiles/_evidence_tags.py`
- Create: `src/intent_packages/profiles/software_delivery.py`
- Modify: `src/intent_packages/profiles/__init__.py` (register the profile)
- Modify: `tests/conftest.py` (add `software_delivery_package` fixture)
- Test: `tests/test_profile_software_delivery.py`

**Interfaces:**
- Consumes (from Task 1): `intent_packages.profiles.PROFILES` (registers `"software-delivery"` into it).
- Consumes (from `schema.py`, already exists): `MapSpec`, `ScalarSpec`, `ListSpec`, `_s`, `_l`, `_walk`.
- Produces: `intent_packages.profiles._evidence_tags.check_evidence_tags(package: dict, tag_to_type:
  dict[str, str]) -> list[str]` — shared by both profiles (Task 3 reuses this unchanged).
- Produces: `intent_packages.profiles.software_delivery.validate(package: dict) -> list[str]`.
- Produces (test fixture, consumed by Task 4): `software_delivery_package(tmp_path)` pytest fixture in
  `tests/conftest.py`, returning a package dir path exactly like `valid_package` does, but with
  `profile: software-delivery`, a valid `profile_fields`, and all `acceptance[]` evidence tagged/typed
  correctly.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_software_delivery.py`:

```python
"""Task 2: the software-delivery profile — profile_fields schema + evidence-tag/
evidence_type consistency checks (WS-2.2 spec §3)."""

from intent_packages.validate import validate_package


def test_valid_software_delivery_package_has_no_errors(software_delivery_package):
    assert validate_package(software_delivery_package) == []


def test_missing_profile_fields_is_rejected(software_delivery_package, drop_key):
    drop_key(software_delivery_package, "package.yaml", "profile_fields")
    errs = validate_package(software_delivery_package)
    assert any("profile_fields" in e and "missing" in e for e in errs)


def test_profile_fields_unknown_key_is_rejected(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("profile_fields", "bogus_key"), "x"),
    )
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.bogus_key" in e and "unknown key" in e for e in errs)


def test_profile_fields_missing_repo_is_rejected(software_delivery_package, drop_key):
    drop_key(software_delivery_package, "package.yaml", "profile_fields", "repo")
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.repo" in e and "missing" in e for e in errs)


def test_profile_fields_repo_must_be_non_empty(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package, "package.yaml", set_nested=(("profile_fields", "repo"), "")
    )
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.repo" in e and "non-empty" in e for e in errs)


def test_profile_fields_deploy_target_may_be_null(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("profile_fields", "deploy_target"), None),
    )
    assert validate_package(software_delivery_package) == []


def test_profile_fields_required_checks_must_be_non_empty_list(
    software_delivery_package, edit_yaml
):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("profile_fields", "required_checks"), []),
    )
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.required_checks" in e and "non-empty" in e for e in errs)


def test_profile_fields_rollback_plan_must_be_non_empty(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("profile_fields", "rollback_plan"), ""),
    )
    errs = validate_package(software_delivery_package)
    assert any("profile_fields.rollback_plan" in e and "non-empty" in e for e in errs)


def test_evidence_without_a_recognized_tag_is_rejected(software_delivery_package, edit_yaml):
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence"), "no tag here at all"),
    )
    errs = validate_package(software_delivery_package)
    assert any("acceptance[0].evidence" in e and "recognized producer tag" in e for e in errs)


def test_each_valid_tag_is_accepted(software_delivery_package, edit_yaml):
    # One acceptance item per tag, each evidence_type matched correctly.
    tags_and_types = [
        ("ci: validate.yml passes", "automated_test"),
        ("gate: Gate A passed", "automated_test"),
        ("scan: no BLOCK findings", "automated_test"),
        ("review: /code-review approved", "automated_test"),
        ("health: /api/health 200 after deploy", "automated_test"),
        ("human: devon reviews and approves", "human_review"),
    ]
    items = [
        {
            "id": f"AC-{i + 1:03d}",
            "condition": "x",
            "evidence_type": etype,
            "evidence": evidence,
            "approver": "policy" if etype == "automated_test" else "devon",
        }
        for i, (evidence, etype) in enumerate(tags_and_types)
    ]
    edit_yaml(software_delivery_package, "package.yaml", set_key=("acceptance", items))
    assert validate_package(software_delivery_package) == []


def test_tag_evidence_type_mismatch_is_rejected(software_delivery_package, edit_yaml):
    # "ci:" requires automated_test, not human_review. approver stays "policy"
    # (legal regardless of evidence_type per check A) so this test isolates
    # the tag/evidence_type check alone.
    edit_yaml(
        software_delivery_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence_type"), "human_review"),
    )
    errs = validate_package(software_delivery_package)
    assert any(
        "acceptance[0].evidence_type" in e and "ci:" in e and "human_review" in e for e in errs
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest tests/test_profile_software_delivery.py -v`
Expected: FAIL/ERROR — `fixture 'software_delivery_package' not found`.

- [ ] **Step 3: Add the `software_delivery_package` conftest fixture**

In `tests/conftest.py`, add a new template string right after `_VALID_PACKAGE_YAML` (before `_read_yaml`):

```python
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
```

Then add the fixture function right after the `valid_package` fixture:

```python
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
```

- [ ] **Step 4: Run tests to verify they still fail (now on the real missing module)**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest tests/test_profile_software_delivery.py -v`
Expected: FAIL — `test_valid_software_delivery_package_has_no_errors` fails because `profile_fields:
unknown key`-style errors don't yet exist (check P is a no-op for `"software-delivery"` until it's
registered) — actually since profile `"software-delivery"` is not yet in `PROFILES`, `validate_profile`
returns `["profile: unknown profile 'software-delivery'; valid: []"]`, so this test fails with that
error present. Confirms the fixture loads correctly and exercises the real dispatch path.

- [ ] **Step 5: Write the shared evidence-tag helper**

Create `src/intent_packages/profiles/_evidence_tags.py`:

```python
"""Shared evidence-tag check (WS-2.2 spec §5), used by every profile.

Each profile owns a fixed `tag -> required evidence_type` mapping. Every
`acceptance[].evidence` string must start with one of that profile's tags
(case-sensitive prefix, colon required); the item's `evidence_type` must
match the tag's required value. This is deliberately an enum-of-producers
check, not an evidence-payload framework (see spec §5).
"""

from __future__ import annotations


def check_evidence_tags(package: dict, tag_to_type: dict[str, str]) -> list[str]:
    acceptance = package.get("acceptance")
    if not isinstance(acceptance, list):
        return []

    valid_prefixes = sorted(tag_to_type)
    errors: list[str] = []

    for i, item in enumerate(acceptance):
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, str):
            continue  # universal check A already flags a non-str/empty evidence

        matched_tag = next((tag for tag in tag_to_type if evidence.startswith(tag)), None)
        if matched_tag is None:
            errors.append(
                f"acceptance[{i}].evidence: {evidence!r} does not start with a "
                f"recognized producer tag (valid: {valid_prefixes})"
            )
            continue

        expected_type = tag_to_type[matched_tag]
        actual_type = item.get("evidence_type")
        if actual_type != expected_type:
            errors.append(
                f"acceptance[{i}].evidence_type: tag {matched_tag!r} requires "
                f"evidence_type {expected_type!r}, got {actual_type!r}"
            )

    return errors
```

- [ ] **Step 6: Write the software-delivery profile module**

Create `src/intent_packages/profiles/software_delivery.py`:

```python
"""Software-delivery domain profile (WS-2.2 spec §3): profile_fields schema +
evidence-tag/evidence_type consistency checks layered on the universal envelope."""

from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.schema import MapSpec, _l, _s, _walk

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "repo": _s(str),
        "branch": _s(str),
        "deploy_target": _s(str, nullable=True),
        "required_checks": _l(str),
        "rollback_plan": _s(str),
    }
)

TAG_TO_EVIDENCE_TYPE = {
    "ci:": "automated_test",
    "gate:": "automated_test",
    "scan:": "automated_test",
    "review:": "automated_test",
    "health:": "automated_test",
    "human:": "human_review",
}

_NON_EMPTY_STRING_FIELDS = ("repo", "branch", "rollback_plan")


def _check_profile_fields(package: dict) -> list[str]:
    errors: list[str] = []
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        errors.append("profile_fields: missing required key")
        return errors

    _walk(fields, PROFILE_FIELDS_SCHEMA, "profile_fields", errors)
    if errors:
        return errors

    for key in _NON_EMPTY_STRING_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and not value.strip():
            errors.append(f"profile_fields.{key}: must be a non-empty string")

    required_checks = fields.get("required_checks")
    if isinstance(required_checks, list) and not required_checks:
        errors.append("profile_fields.required_checks: must be a non-empty list")

    return errors


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors
```

- [ ] **Step 7: Register the profile**

In `src/intent_packages/profiles/__init__.py`, add the import and registration. Replace the file's
`PROFILES: dict[str, Callable[[dict], list[str]]] = {}` line with:

```python
from intent_packages.profiles import software_delivery

PROFILES: dict[str, Callable[[dict], list[str]]] = {
    "software-delivery": software_delivery.validate,
}
```

(Add the `from intent_packages.profiles import software_delivery` import after the existing `from
typing import Callable` line.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest tests/test_profile_software_delivery.py -v`
Expected: 11 passed.

- [ ] **Step 9: Run the full test suite + lint**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest -q && ruff check .`
Expected: 140 passed (129 + 11), `All checks passed!`.

- [ ] **Step 10: Commit**

```bash
cd ~/Projects/intent-packages
git add src/intent_packages/profiles/ tests/conftest.py tests/test_profile_software_delivery.py
git commit -m "feat(ws22): add software-delivery profile (fields + evidence-tag checks)"
```

---

### Task 3: Infrastructure-change profile

**Files:**
- Create: `src/intent_packages/profiles/infrastructure_change.py`
- Modify: `src/intent_packages/profiles/__init__.py` (register the second profile)
- Modify: `tests/conftest.py` (add `infrastructure_change_package` fixture)
- Test: `tests/test_profile_infrastructure_change.py`

**Interfaces:**
- Consumes (from Task 2): `intent_packages.profiles._evidence_tags.check_evidence_tags` (reused
  unchanged — same shared helper, different `tag_to_type` mapping).
- Consumes (from `schema.py`): `MapSpec`, `_s`, `_walk` (no `_l` needed — no list fields here).
- Produces: `intent_packages.profiles.infrastructure_change.validate(package: dict) -> list[str]`.
- Produces (test fixture): `infrastructure_change_package(tmp_path)` in `tests/conftest.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_infrastructure_change.py`:

```python
"""Task 3: the infrastructure-change profile — profile_fields schema + evidence-tag/
evidence_type consistency checks (WS-2.2 spec §4)."""

from intent_packages.validate import validate_package


def test_valid_infrastructure_change_package_has_no_errors(infrastructure_change_package):
    assert validate_package(infrastructure_change_package) == []


def test_missing_profile_fields_is_rejected(infrastructure_change_package, drop_key):
    drop_key(infrastructure_change_package, "package.yaml", "profile_fields")
    errs = validate_package(infrastructure_change_package)
    assert any("profile_fields" in e and "missing" in e for e in errs)


def test_blast_radius_must_be_a_legal_enum_value(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("profile_fields", "blast_radius"), "the-whole-internet"),
    )
    errs = validate_package(infrastructure_change_package)
    assert any("profile_fields.blast_radius" in e and "the-whole-internet" in e for e in errs)


def test_change_window_may_be_null(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("profile_fields", "change_window"), None),
    )
    assert validate_package(infrastructure_change_package) == []


def test_backup_evidence_may_be_null(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("profile_fields", "backup_evidence"), None),
    )
    assert validate_package(infrastructure_change_package) == []


def test_rollback_plan_must_be_non_empty(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("profile_fields", "rollback_plan"), ""),
    )
    errs = validate_package(infrastructure_change_package)
    assert any("profile_fields.rollback_plan" in e and "non-empty" in e for e in errs)


def test_evidence_without_a_recognized_tag_is_rejected(infrastructure_change_package, edit_yaml):
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence"), "no tag here at all"),
    )
    errs = validate_package(infrastructure_change_package)
    assert any("acceptance[0].evidence" in e and "recognized producer tag" in e for e in errs)


def test_each_valid_tag_is_accepted(infrastructure_change_package, edit_yaml):
    tags_and_types = [
        ("health: /api/health 200 after change", "automated_test"),
        ("backup: vps-backup recipe D run 2026-07-04", "automated_test"),
        ("change-log: infra change log entry 2026-07-04", "automated_test"),
        ("human: devon reviews and approves", "human_review"),
    ]
    items = [
        {
            "id": f"AC-{i + 1:03d}",
            "condition": "x",
            "evidence_type": etype,
            "evidence": evidence,
            "approver": "policy" if etype == "automated_test" else "devon",
        }
        for i, (evidence, etype) in enumerate(tags_and_types)
    ]
    edit_yaml(infrastructure_change_package, "package.yaml", set_key=("acceptance", items))
    assert validate_package(infrastructure_change_package) == []


def test_tag_evidence_type_mismatch_is_rejected(infrastructure_change_package, edit_yaml):
    # "health:" requires automated_test, not human_review. approver stays
    # "policy" (legal regardless of evidence_type per check A) so this test
    # isolates the tag/evidence_type check alone.
    edit_yaml(
        infrastructure_change_package,
        "package.yaml",
        set_nested=(("acceptance", 0, "evidence_type"), "human_review"),
    )
    errs = validate_package(infrastructure_change_package)
    assert any(
        "acceptance[0].evidence_type" in e and "health:" in e and "human_review" in e for e in errs
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest tests/test_profile_infrastructure_change.py -v`
Expected: FAIL/ERROR — `fixture 'infrastructure_change_package' not found`.

- [ ] **Step 3: Add the `infrastructure_change_package` conftest fixture**

In `tests/conftest.py`, add another template string after `_SOFTWARE_DELIVERY_PACKAGE_YAML`:

```python
# A complete, valid infrastructure-change-profile package (WS-2.2 spec §4).
_INFRASTRUCTURE_CHANGE_PACKAGE_YAML = """\
schema_version: 1
package_id: sample-infrastructure-change-package
title: "A sample infrastructure-change profile package"
revision: 1
status: draft
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
```

Then add the fixture function right after `software_delivery_package`:

```python
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
```

- [ ] **Step 4: Run tests to verify they still fail on the real missing profile**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest tests/test_profile_infrastructure_change.py -v`
Expected: FAIL — `test_valid_infrastructure_change_package_has_no_errors` fails with `profile: unknown
profile 'infrastructure-change'; valid: ['software-delivery']`.

- [ ] **Step 5: Write the infrastructure-change profile module**

Create `src/intent_packages/profiles/infrastructure_change.py`:

```python
"""Infrastructure-change domain profile (WS-2.2 spec §4): profile_fields schema +
evidence-tag/evidence_type consistency checks layered on the universal envelope."""

from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.schema import MapSpec, _s, _walk

BLAST_RADIUS_VALUES = {"single-app", "shared-service", "portfolio-wide"}

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "blast_radius": _s(str, enum=BLAST_RADIUS_VALUES),
        "change_window": _s(str, nullable=True),
        "backup_evidence": _s(str, nullable=True),
        "rollback_plan": _s(str),
    }
)


def _check_profile_fields(package: dict) -> list[str]:
    errors: list[str] = []
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        errors.append("profile_fields: missing required key")
        return errors

    _walk(fields, PROFILE_FIELDS_SCHEMA, "profile_fields", errors)
    if errors:
        return errors

    rollback_plan = fields.get("rollback_plan")
    if isinstance(rollback_plan, str) and not rollback_plan.strip():
        errors.append("profile_fields.rollback_plan: must be a non-empty string")

    return errors


TAG_TO_EVIDENCE_TYPE = {
    "health:": "automated_test",
    "backup:": "automated_test",
    "change-log:": "automated_test",
    "human:": "human_review",
}


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors
```

- [ ] **Step 6: Register the profile**

In `src/intent_packages/profiles/__init__.py`, add the second import and registry entry:

```python
from intent_packages.profiles import infrastructure_change, software_delivery

PROFILES: dict[str, Callable[[dict], list[str]]] = {
    "software-delivery": software_delivery.validate,
    "infrastructure-change": infrastructure_change.validate,
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest tests/test_profile_infrastructure_change.py -v`
Expected: 9 passed.

- [ ] **Step 8: Run the full test suite + lint**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest -q && ruff check .`
Expected: 149 passed (140 + 9), `All checks passed!`.

- [ ] **Step 9: Commit**

```bash
cd ~/Projects/intent-packages
git add src/intent_packages/profiles/ tests/conftest.py tests/test_profile_infrastructure_change.py
git commit -m "feat(ws22): add infrastructure-change profile (fields + evidence-tag checks)"
```

---

### Task 4: AC-002 compatibility proof

**Files:**
- Test: `tests/test_profiles_compat.py`

**Interfaces:**
- Consumes: `valid_package` (conftest, existing, universal-only — no `profile` key),
  `intent_packages.canonical.package_hash`, `intent_packages.validate.validate_package`,
  `intent_packages.profiles.validate_profile`.
- Produces: nothing new for later tasks — this task is a pure verification leaf.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profiles_compat.py`:

```python
"""Task 4: AC-002 — the universal envelope is provably unchanged by the profiles
module. A universal-only package (no `profile` key) must validate identically and
hash identically to how it did before WS-2.2 landed."""

from intent_packages import canonical, loader, profiles
from intent_packages.validate import validate_package

# Locked regression value: the sha256(JCS(intent_core)) of the exact
# `_VALID_PACKAGE_YAML` fixture in conftest.py, computed before any WS-2.2 code
# existed (verified 2026-07-04, pre-Task-1). If this ever changes, something
# touched the universal envelope, the hash algorithm, or the fixture — all
# three are AC-002 violations.
_LOCKED_VALID_PACKAGE_HASH = "d49794b97c1b930de2150fa7258f0a806df586d9d4c73ed401069d9ba65e7c77"


def test_universal_only_package_is_unaffected_by_check_p(valid_package):
    pkg = loader.load_package(valid_package)
    assert profiles.validate_profile(pkg) == []


def test_universal_only_package_still_validates_clean(valid_package):
    assert validate_package(valid_package) == []


def test_universal_only_package_hash_is_locked(valid_package):
    pkg = loader.load_package(valid_package)
    assert canonical.package_hash(pkg) == _LOCKED_VALID_PACKAGE_HASH
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest tests/test_profiles_compat.py -v`
Expected: 3 passed. (If `test_universal_only_package_hash_is_locked` fails, something in Tasks 1–3
touched the universal envelope, the canonical hash algorithm, or the `_VALID_PACKAGE_YAML` fixture
itself — stop and investigate before proceeding; do not adjust the locked constant to make it pass.)

- [ ] **Step 3: Run the FULL suite unmodified and confirm the exact WS-2.1 count is untouched**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest -q`
Expected: 152 passed (149 + 3), 0 failed — and critically, `git diff` on every test file that existed
before this workstream (everything except the 5 new `test_profile*`/`test_profiles_*` files) is empty:

```bash
git diff --stat -- tests/test_canonical.py tests/test_cli_hash.py tests/test_cli_smoke.py \
  tests/test_emitter.py tests/test_lifecycle.py tests/test_lineage.py tests/test_loader.py \
  tests/test_op_approve.py tests/test_op_revise_supersede.py tests/test_op_transition.py \
  tests/test_op_verify_approval.py tests/test_registry.py tests/test_validate_semantic.py \
  tests/test_validate_structure.py
```
Expected: no output (empty diff) — proves no pre-existing test was edited to make this pass.

- [ ] **Step 4: Lint**

Run: `cd ~/Projects/intent-packages && ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/intent-packages
git add tests/test_profiles_compat.py
git commit -m "test(ws22): lock AC-002 compatibility — universal envelope provably unchanged"
```

---

### Task 5: End-to-end CLI verification + docs wrap-up

**Files:**
- Modify: `PROJECT.md` (repo root — mark WS-2.2 done in Future plans)
- No new source/test files — this task is manual verification + documentation.

**Interfaces:** none (leaf task; nothing later depends on this).

- [ ] **Step 1: Manually exercise the real CLI against a profiled package on disk**

This proves the profile machinery works through the actual `validate` entrypoint a human/agent would
run — not just pytest. Use a throwaway scratch directory (`mktemp -d`), not `packages/` — these are not
real intents:

```bash
cd ~/Projects/intent-packages
SCRATCH=$(mktemp -d)
mkdir -p "$SCRATCH/packages/manual-check-software-delivery"
cat > "$SCRATCH/packages/manual-check-software-delivery/package.yaml" <<'YAML'
schema_version: 1
package_id: manual-check-software-delivery
title: "Manual CLI check"
revision: 1
status: draft
created_by: claude-code-interactive
owner: devon
created_at: "2026-07-04T00:00:00Z"
supersedes: null
profile: software-delivery
profile_fields:
  repo: "AlobarQuest/intent-packages"
  branch: "main"
  deploy_target: null
  required_checks: ["ci:validate.yml"]
  rollback_plan: "git revert"
outcome:
  what: "manual check"
  why: "manual check"
  beneficiary: "manual check"
  success_signal: "manual check"
scope:
  included: []
  excluded: []
  non_goals: []
  assumptions: []
  open_questions: []
sources: []
constraints:
  time_budget: null
  technology: null
  policy_legal: null
  privacy_security: null
  compatibility: null
  quality_accessibility: null
  operational: null
  other: []
acceptance:
  - id: AC-001
    condition: "manual check"
    evidence_type: automated_test
    evidence: "ci: manual check"
    approver: policy
deliverables:
  artifacts: []
  destination: "manual check"
  recipient: "devon"
  definition_of_done: "manual check"
  operator_responsibilities: []
dependencies:
  predecessor_packages: []
  external_decisions: []
  required_people_systems: []
  required_capabilities: []
  blocking_conditions: []
authority:
  allowed: []
  requires_approval: []
  prohibited: []
  budgets:
    max_attempts: null
    max_llm_calls: null
risk:
  failure_modes: []
  max_impact: "low"
  stop_conditions: []
  rollback: "n/a"
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
YAML
PKG_HASH=$(PYTHONPATH=src python3 -m intent_packages hash "$SCRATCH/packages/manual-check-software-delivery")
cat > "$SCRATCH/packages/manual-check-software-delivery/lineage.yaml" <<YAML
package_id: manual-check-software-delivery
current_state: draft
revisions:
  - revision: 1
    hash: "${PKG_HASH}"
    created_at: "2026-07-04T00:00:00Z"
    author: claude-code-interactive
transitions: []
approvals: []
grants: []
YAML
PYTHONPATH=src python3 -m intent_packages validate "$SCRATCH/packages/manual-check-software-delivery"
echo "EXIT: $?"
```
Expected: `EXIT: 0`, no error output at all — a genuinely clean pass through the real CLI (both the
universal checks and the software-delivery profile checks), not just pytest.

- [ ] **Step 2: Demonstrate a deliberately-broken profiled package fails with an actionable error**

```bash
python3 -c "
content = open('$SCRATCH/packages/manual-check-software-delivery/package.yaml').read()
content = content.replace('evidence: \"ci: manual check\"', 'evidence: \"no tag here\"')
open('$SCRATCH/packages/manual-check-software-delivery/package.yaml', 'w').write(content)
"
PYTHONPATH=src python3 -m intent_packages validate "$SCRATCH/packages/manual-check-software-delivery"
echo "EXIT: $?"
```
Expected: `EXIT: 1` (non-zero), and the error output includes a line containing
`acceptance[0].evidence` and `recognized producer tag`.

- [ ] **Step 3: Clean up the scratch directory**

```bash
rm -rf "$SCRATCH"
```

- [ ] **Step 4: Update `PROJECT.md`'s Future plans section**

Read the current `## Future plans` section of `~/Projects/intent-packages/PROJECT.md` and replace the
WS-2.2 line. It currently reads:
```markdown
- WS-2.2 (next): domain profiles (software-delivery + infrastructure-change) extending the universal envelope via `profile_fields` — the first real intent package `packages/ws-2.2-domain-profiles` is authored and Approved (dogfood ladder input).
```
Replace it with:
```markdown
- WS-2.2 (done): domain profiles (software-delivery + infrastructure-change) shipped in `src/intent_packages/profiles/` — dispatch registry (check P), per-profile `profile_fields` schemas, and a shared tag-prefix evidence-vocabulary check (AC-004). Universal envelope proven unchanged (`tests/test_profiles_compat.py`). Next: WS-2.3, authored as the next intent package under `profile: software-delivery` (dogfood ladder).
```

- [ ] **Step 5: Final full-suite + lint check**

Run: `cd ~/Projects/intent-packages && PYTHONPATH=src python3 -m pytest -q && ruff check .`
Expected: 152 passed, `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/intent-packages
git add PROJECT.md
git commit -m "docs(ws22): mark domain profiles shipped in PROJECT.md"
```

---

## Post-plan: exit criteria checklist (from the design spec §10)

- [ ] Both profiles validate their own valid example fixture with zero errors, and their broken variants
      (via `edit_yaml`/`drop_key` mutation, per the plan-level note) fail with actionable errors (AC-001)
      — Tasks 2–3.
- [ ] The universal envelope is provably unchanged (AC-002) — Task 4.
- [ ] Devon confirms no software/infra assumption leaked into the universal envelope (AC-003) — requires
      Devon's review of the merged branch; not a task an implementer can self-certify.
- [ ] Each profile's evidence-tag check rejects an unrecognized tag and a tag/`evidence_type` mismatch
      (AC-004) — Tasks 2–3.
- [ ] Repo stays standards-conformant; no CI file changes needed — confirmed by Task 4/5's full-suite
      runs using the existing `validate.yml` invocation pattern.
- [ ] Dogfood ladder continues: author WS-2.3 as the next intent package under `profile:
      software-delivery` — separate, later workstream, not part of this plan.

Per repo convention (`CLAUDE.md`: "Never merge — PRs wait for Devon"), open a PR after Task 5 and stop.
Do not merge.
