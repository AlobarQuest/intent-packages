# WS-P2.10 — Delivery Profiles + Model-Routing Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the versioned model-routing policy file with three real consumers, unify the two ungoverned profile kinds under a `DeliveryProfile` dataclass, add the maintenance-remediation and non-software-operational profiles, formalize dependency-update as declarable, and add optional-key support to the schema walker — all without changing the validation outcome or `package_hash` of any existing package.

**Architecture:** Approved design at `docs/superpowers/specs/2026-07-29-wsp210-profiles-routing-policy-design.md` — read it first; it is authoritative on every decision. `routing-policy.toml` (repo root, stdlib `tomllib`) is loaded by a new `routing.py`; `factory route` and `factory decompose` consume it. `profiles/base.py` defines frozen `DeliveryProfile`/`AuthorityDefaults`; the registry in `profiles/__init__.py` becomes `dict[str, DeliveryProfile]` with existing profiles wrapped unchanged.

**Tech Stack:** Python 3.12+, pyyaml (only runtime dep — routing uses stdlib `tomllib`), pytest, ruff (line 100, `E,F,I,UP,B,C90`), pyright.

## Global Constraints

- Repo: `~/Projects/intent-packages`. Run all commands from the repo root. Tools: `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/pyright` (never global).
- `make check` = ruff check + ruff format --check + pyright + pytest. Baseline collection is **197 tests** — after each task, read the `collected N items` line; exit 0 with fewer collected than expected is a failure, not a pass.
- **All 19 real packages under `packages/` must validate with byte-identical output and unchanged `package_hash` throughout.** Task 1's regression harness enforces this; never edit any `packages/*/package.yaml` (editing changes `package_hash` and invalidates lineage approvals).
- The locked-hash constant in `tests/test_profiles_compat.py` (`d49794b9…`) must stay green. If it reddens, your change broke the universal envelope — revert, don't update the constant.
- **No orchestrator or factory-runner changes.** The authority envelope's key set is a byte-pinned cross-repo contract: `build_envelope` output keys must remain exactly `{budgets, capabilities, change_class, conformance, constraints}` with `constraints` keys exactly `{allowed_commands, mutation_commands, target_repository}`.
- Model slug → API id mapping (verified 2026-07-29 against the claude-api reference): `fable-5 = "claude-fable-5"`, `sonnet-5 = "claude-sonnet-5"`, `opus-4-8 = "claude-opus-4-8"`, `haiku-4-5 = "claude-haiku-4-5"`.
- Never run `ruff format` on a `.json` file (it corrupts JSON). Run `ruff format` on changed `.py` files before every commit — full-repo format debt is invisible to per-task checks.
- CLI behavior is tested through the real entrypoint (`factory_cli.main(argv)`), not by calling internals.
- Commit after every task with a conventional-commit message. Work on branch `wsp210-profiles-routing` (create from `main` in Task 1).

---

### Task 1: Regression harness — real packages validate clean + hash snapshot

Locks current behavior BEFORE any change. Every later task must keep this green.

**Files:**
- Create: `tests/test_packages_regression.py`
- Create: `tests/fixtures/package_hashes.json` (generated)

**Interfaces:**
- Consumes: `intent_packages.validate.validate_package(pkg_dir: Path) -> list[str]`, `intent_packages.canonical.package_hash(package: dict) -> str`
- Produces: nothing imported by later tasks; the harness itself is the deliverable.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b wsp210-profiles-routing main
```

- [ ] **Step 2: Write the test file**

```python
"""WS-P2.10 regression harness: every real package in packages/ must validate
with zero errors, and its package_hash must match the committed snapshot.

Written BEFORE any WS-P2.10 change lands, so drift introduced by the registry
unification or the walker change fails here first. If a hash mismatches, the
fix is to revert the change that caused it — never to regenerate the snapshot
(editing an approved package's YAML invalidates its lineage approvals).
"""

import json
from pathlib import Path

import pytest
import yaml

from intent_packages.canonical import package_hash
from intent_packages.validate import validate_package

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = REPO_ROOT / "packages"
SNAPSHOT_PATH = REPO_ROOT / "tests" / "fixtures" / "package_hashes.json"


def _package_dirs() -> list[Path]:
    return sorted(p for p in PACKAGES_DIR.iterdir() if (p / "package.yaml").is_file())


def _snapshot() -> dict[str, str]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_snapshot_covers_every_package_exactly():
    assert sorted(_snapshot()) == [p.name for p in _package_dirs()]


@pytest.mark.parametrize("pkg_dir", _package_dirs(), ids=lambda p: p.name)
def test_real_package_validates_clean(pkg_dir):
    assert validate_package(pkg_dir) == []


@pytest.mark.parametrize("pkg_dir", _package_dirs(), ids=lambda p: p.name)
def test_real_package_hash_matches_snapshot(pkg_dir):
    pkg = yaml.safe_load((pkg_dir / "package.yaml").read_text(encoding="utf-8"))
    assert package_hash(pkg) == _snapshot()[pkg_dir.name]
```

Note: `conftest.py`'s autouse `_hermetic_registry_env` fixture applies, so these tests do not depend on a security-standards checkout — same as CI's pytest job.

If `validate_package`'s signature is not `(pkg_dir: Path)`, check `tests/test_profiles_dispatch.py:44` for the real call shape (it passes a directory path fixture) and match it.

- [ ] **Step 3: Run the validation tests to verify they fail (no snapshot yet)**

Run: `.venv/bin/pytest tests/test_packages_regression.py -v`
Expected: `test_real_package_validates_clean` items PASS (19 of them — if any FAILS, STOP: the current tree has a validation regression; report it rather than proceeding); snapshot tests ERROR/FAIL with `FileNotFoundError`.

- [ ] **Step 4: Generate the snapshot**

```bash
PYTHONPATH=src .venv/bin/python - <<'EOF'
import json
from pathlib import Path

import yaml

from intent_packages.canonical import package_hash

out = {
    p.name: package_hash(yaml.safe_load((p / "package.yaml").read_text(encoding="utf-8")))
    for p in sorted(Path("packages").iterdir())
    if (p / "package.yaml").is_file()
}
Path("tests/fixtures").mkdir(parents=True, exist_ok=True)
path = Path("tests/fixtures/package_hashes.json")
path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"{len(out)} hashes written to {path}")
EOF
```

Expected: `19 hashes written …` (if the count differs, list `packages/` and confirm — the design says 19 as of 2026-07-29).

- [ ] **Step 5: Run the full file to verify it passes**

Run: `.venv/bin/pytest tests/test_packages_regression.py -v`
Expected: all PASS (1 + 19 + 19 = 39 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_packages_regression.py tests/fixtures/package_hashes.json
git commit -m "test: regression harness pinning real-package validation + hashes (WS-P2.10 task 1)"
```

---

### Task 2: `OptionalKey` in the schema walker

**Files:**
- Modify: `src/intent_packages/schema.py` (add dataclass after `OpenMapSpec` ~line 40; change `_walk_map` ~line 221; widen `MapSpec.fields` annotation ~line 32)
- Create: `tests/test_schema_optional_key.py`

**Interfaces:**
- Consumes: existing `ScalarSpec`/`ListSpec`/`MapSpec`/`OpenMapSpec`, `_walk`, `_walk_map`.
- Produces: `intent_packages.schema.OptionalKey` — frozen dataclass, `OptionalKey(spec)` where `spec: ScalarSpec | ListSpec | MapSpec | OpenMapSpec`. Used by Tasks 7 and 8 inside `profile_fields` MapSpecs.

- [ ] **Step 1: Write the failing tests**

```python
"""OptionalKey (WS-P2.10): a MapSpec field whose KEY may be absent. Present
values are checked against the wrapped spec; schemas stay closed (unknown
keys are still errors); required keys are unaffected."""

from intent_packages.schema import ListSpec, MapSpec, OptionalKey, _s, _walk

SPEC = MapSpec(
    {
        "required_field": _s(str),
        "optional_scalar": OptionalKey(_s(str)),
        "optional_list": OptionalKey(ListSpec(_s(str))),
    }
)


def _errors(value: dict) -> list[str]:
    errors: list[str] = []
    _walk(value, SPEC, "root", errors)
    return errors


def test_absent_optional_key_is_not_an_error():
    assert _errors({"required_field": "x"}) == []


def test_present_optional_key_is_checked_against_wrapped_spec():
    errs = _errors({"required_field": "x", "optional_scalar": 7})
    assert errs == ["root.optional_scalar: expected str, got int"]


def test_present_valid_optional_key_passes():
    assert _errors({"required_field": "x", "optional_scalar": "y", "optional_list": ["a"]}) == []


def test_optional_list_items_are_checked():
    errs = _errors({"required_field": "x", "optional_list": ["a", 3]})
    assert errs == ["root.optional_list[1]: expected str, got int"]


def test_required_keys_still_required():
    assert _errors({"optional_scalar": "y"}) == ["root.required_field: missing required key"]


def test_unknown_keys_still_rejected():
    errs = _errors({"required_field": "x", "mystery": "y"})
    assert errs == ["root.mystery: unknown key"]


def test_null_optional_value_is_checked_not_skipped():
    # OptionalKey affects key PRESENCE only; a present null hits the wrapped
    # spec's nullability rules like any other value.
    errs = _errors({"required_field": "x", "optional_scalar": None})
    assert errs == ["root.optional_scalar: null is not allowed here"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_schema_optional_key.py -v`
Expected: FAIL with `ImportError: cannot import name 'OptionalKey'`.

- [ ] **Step 3: Implement**

In `src/intent_packages/schema.py`, after the `OpenMapSpec` dataclass:

```python
@dataclass(frozen=True)
class OptionalKey:
    """A MapSpec field whose KEY may be absent (WS-P2.10).

    When the key is present, the value is checked against the wrapped spec.
    Schemas stay closed: unknown keys are still errors. This is optional-KEY
    support; nullable=True on a ScalarSpec remains optional-VALUE support.
    """

    spec: ScalarSpec | ListSpec | MapSpec | OpenMapSpec
```

Widen the `MapSpec.fields` annotation:

```python
@dataclass(frozen=True)
class MapSpec:
    fields: dict[str, ScalarSpec | ListSpec | MapSpec | OpenMapSpec | OptionalKey]
```

(`OptionalKey` is defined after `MapSpec`; the module already has `from __future__ import annotations`, so the forward reference is fine.)

In `_walk_map`, replace the second loop:

```python
    for key, subspec in spec.fields.items():
        if isinstance(subspec, OptionalKey):
            if key in value:
                _walk(value[key], subspec.spec, _join(path, key), errors)
            continue
        if key not in value:
            errors.append(f"{_join(path, key)}: missing required key")
            continue
        _walk(value[key], subspec, _join(path, key), errors)
```

Do NOT touch `validate.py`'s duplicated top-level check (`_check_k_and_j`) — no top-level key is optional.

- [ ] **Step 4: Run new tests + full suite**

Run: `.venv/bin/pytest tests/test_schema_optional_key.py -v` → all PASS.
Run: `.venv/bin/pytest` → expect `236 passed` (197 + 39 from Task 1... plus these 7 = 243 total collected; read the actual count and confirm no prior test broke).

- [ ] **Step 5: Lint, type-check, commit**

```bash
.venv/bin/ruff format src/intent_packages/schema.py tests/test_schema_optional_key.py
.venv/bin/ruff check src/intent_packages/schema.py tests/test_schema_optional_key.py
.venv/bin/pyright src/intent_packages/schema.py
git add src/intent_packages/schema.py tests/test_schema_optional_key.py
git commit -m "feat: OptionalKey optional-key support in the schema walker (WS-P2.10 task 2)"
```

---

### Task 3: `routing-policy.toml` + the `routing` module

**Files:**
- Create: `routing-policy.toml` (repo root)
- Create: `src/intent_packages/routing.py`
- Test: `tests/test_routing.py`

**Interfaces:**
- Produces (used by Tasks 4 and 9):
  - `routing.RoutingPolicyError(Exception)`
  - `routing.RoutingRow` — frozen dataclass: `id: str`, `models: tuple[str, ...]` (slugs), `model_ids: tuple[str, ...]` (API ids, same order), `rationale: str`, `decided: str`
  - `routing.RoutingPolicy` — frozen dataclass: `version: int`, `models: dict[str, str]`, `surfaces: dict[str, RoutingRow]`, `change_classes: dict[str, RoutingRow]`, `no_llm: tuple[str, ...]`
  - `routing.default_policy_path() -> Path` (repo-root anchored: `Path(__file__).resolve().parents[2] / "routing-policy.toml"`)
  - `routing.load_policy(path: Path | None = None) -> RoutingPolicy` — raises `RoutingPolicyError` on missing file, bad shape, unknown slug, or a change-class row referencing an unknown surface
  - `routing.resolve_surface(policy, surface_id) -> RoutingRow` / `routing.resolve_change_class(policy, change_class) -> RoutingRow` — raise `RoutingPolicyError` with the sorted list of valid keys on an unknown lookup

- [ ] **Step 1: Write the policy file** — content is TRANSCRIPTION of the decided 2026-07-08 seed (post-MVP doc §11); do not editorialize.

Create `routing-policy.toml`:

```toml
# routing-policy.toml — the SOLE SOURCE of model selection for the software
# delivery system (program exit criterion #11).
#
# Seeded verbatim from the decided 2026-07-08 table:
# ~/docs/software-delivery-system/2026-07-04-codex-post-mvp-recommendations.md §11.
# Governing principle: spend top-tier where errors are expensive and volume is
# low (intent, verification); economize where deterministic gates catch
# failures cheaply (implementation — a wrong PR fails verification, it never
# ships). The verifier tier must never drop below the implementer tier it is
# checking.
#
# GRADUATION EDITING CONTRACT (decided 2026-07-08; WS-P2.14 supplies the data):
# - Demotions are suggested by data: a change-class with N consecutive clean
#   runs (start N=15) on its current tier triggers a SUGGEST to demote one
#   tier. Devon decides.
# - Promotions are manual and immediate: a class producing repeated
#   revision_required outcomes is promoted one tier BEFORE it is granted more
#   retries — never burn attempts on an underpowered model.
# - Every tier change is a versioned edit to THIS FILE: update the row's
#   `models`, `decided`, and `rationale`, and bump `version`. Never an inline
#   override anywhere else.

version = 1

[models]
fable-5 = "claude-fable-5"
sonnet-5 = "claude-sonnet-5"
opus-4-8 = "claude-opus-4-8"
haiku-4-5 = "claude-haiku-4-5"

[no_llm]
# Restated from the seed so this file inherits it: these subsystems are
# deterministic BY DESIGN and never call a model.
items = [
  "state machine and transitions",
  "leases/claims",
  "dispatch + circuit breaker + kill switch",
  "conformance admission gate",
  "deterministic AC verification",
  "budget enforcement",
  "traceability queries",
  "graduation counters",
  "the 4am executor",
  "claim-time context enrichment",
]

[[surface]]
id = "intent-authoring"
models = ["fable-5"]
where = "WS-2.3 front door"
rationale = "Highest-leverage words in the system; low volume, judgment-dense. Never economize."
decided = "2026-07-08"

[[surface]]
id = "decomposition-proposals"
models = ["fable-5"]
where = "WS-3.2"
rationale = "One bad decomposition wastes a package's whole execution run; human approval misses subtle scoping errors. Seed table allows Opus 4.8 as alternate."
decided = "2026-07-08"

[[surface]]
id = "runner-implementation"
models = ["sonnet-5"]
where = "WS-4.1/4.2"
rationale = "Sonnet 5 default; Opus 4.8 for complex change-classes. Verifier + CI are the backstop, so a failure costs one cheap retry. Per-class routing; budgets bite hardest here."
decided = "2026-07-08"

[[surface]]
id = "local-heavy"
models = ["fable-5"]
where = "WS-4.3"
rationale = "Work routes here because it is the hard kind (multi-repo, deep context)."
decided = "2026-07-08"

[[surface]]
id = "judgment-ac-verification"
models = ["fable-5", "opus-4-8"]
where = "WS-5.1"
rationale = "At least 2 independent isolated-context reviews + cross-critique (one of each model); Anthropic-only diversity comes from tier + prompt. This backstop is what lets runner-implementation run cheap."
decided = "2026-07-08"

[[surface]]
id = "guarded-infra-agent"
models = ["sonnet-5"]
where = "Existing; WS-4.4 linkage"
rationale = "Proven at Sonnet; guardrails are structural (pre-validate, post-verify-or-revert)."
decided = "2026-07-08"

[[surface]]
id = "lesson-proposals"
models = ["sonnet-5"]
where = "WS-6.2"
rationale = "Outputs are propose-only (human approval is the QC), but lesson quality compounds — Sonnet is the floor."
decided = "2026-07-08"

[[surface]]
id = "high-volume-text"
models = ["haiku-4-5"]
where = "Phase 6 + secondary"
rationale = "Classification/summarization of advisory or projection text; provenance discipline does the safety work, not the model."
decided = "2026-07-08"

# Change-class lookup: the table `factory decompose` consults. NO implicit
# default — a change-class absent here is a hard error, so shipping a new
# factory-executable profile requires adding its row in the same change.

[change_class.dependency-update]
surface = "runner-implementation"
models = ["sonnet-5"]
rationale = "runner-implementation row default (Sonnet 5). Production-proven by GAP-4 (2026-07-29)."
decided = "2026-07-08"

[change_class.maintenance-remediation]
surface = "runner-implementation"
models = ["sonnet-5"]
rationale = "Derived from runner-implementation's Sonnet 5 default; not literally in the 2026-07-08 seed table. Phase-3 WS-P3.2 authoring target."
decided = "2026-07-29"
```

- [ ] **Step 2: Write the failing tests**

```python
"""Routing policy loader (WS-P2.10): shape validation, seed-content pins, and
fail-closed lookups. The repo-root routing-policy.toml is the sole source of
model selection (program exit criterion #11)."""

from pathlib import Path

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
    policy = routing.load_policy()
    assert policy.version == 1
    assert set(policy.surfaces) == EXPECTED_SURFACE_IDS
    assert set(policy.change_classes) == {"dependency-update", "maintenance-remediation"}
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
        '[no_llm]\nitems = []\n'
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
        '[no_llm]\nitems = []\n'
        '[[surface]]\nid = "s"\nmodels = ["sonnet-5"]\nwhere = "w"\n'
        'rationale = "r"\ndecided = "2026-07-29"\n'
        '[change_class.x]\nsurface = "ghost"\nmodels = ["sonnet-5"]\n'
        'rationale = "r"\ndecided = "2026-07-29"\n',
        encoding="utf-8",
    )
    with pytest.raises(routing.RoutingPolicyError, match="ghost"):
        routing.load_policy(bad)
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/pytest tests/test_routing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'intent_packages.routing'` (or ImportError).

- [ ] **Step 4: Implement `src/intent_packages/routing.py`**

```python
"""Model-routing policy loader (WS-P2.10).

The versioned routing-policy.toml at the repo root is the sole source of model
selection (program exit criterion #11). Consumers: `factory route` (query) and
`factory decompose` (fail-closed change-class lookup). There is deliberately
no implicit default: an unknown surface or change-class is an error, so a new
factory-executable profile cannot ship without its routing row.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class RoutingPolicyError(Exception):
    """Raised when the policy file is missing/malformed or a lookup fails."""


@dataclass(frozen=True)
class RoutingRow:
    id: str
    models: tuple[str, ...]
    model_ids: tuple[str, ...]
    rationale: str
    decided: str


@dataclass(frozen=True)
class RoutingPolicy:
    version: int
    models: dict[str, str]
    surfaces: dict[str, RoutingRow]
    change_classes: dict[str, RoutingRow]
    no_llm: tuple[str, ...]


def default_policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "routing-policy.toml"


def _require_str(table: dict, key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RoutingPolicyError(f"{where}: {key} must be a non-empty string")
    return value


def _build_row(table: dict, row_id: str, models: dict[str, str], where: str) -> RoutingRow:
    slugs = table.get("models")
    if not isinstance(slugs, list) or not slugs:
        raise RoutingPolicyError(f"{where}: models must be a non-empty list")
    for slug in slugs:
        if slug not in models:
            raise RoutingPolicyError(
                f"{where}: unknown model slug {slug!r}; valid: {sorted(models)}"
            )
    return RoutingRow(
        id=row_id,
        models=tuple(slugs),
        model_ids=tuple(models[s] for s in slugs),
        rationale=_require_str(table, "rationale", where),
        decided=_require_str(table, "decided", where),
    )


def load_policy(path: Path | None = None) -> RoutingPolicy:
    path = path or default_policy_path()
    if not path.is_file():
        raise RoutingPolicyError(f"routing policy not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise RoutingPolicyError(f"routing policy is not valid TOML: {error}") from error

    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise RoutingPolicyError("version must be a positive integer")

    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise RoutingPolicyError("[models] must be a non-empty table")
    for slug, model_id in models.items():
        if not isinstance(model_id, str) or not model_id.strip():
            raise RoutingPolicyError(f"[models].{slug}: model id must be a non-empty string")

    surfaces: dict[str, RoutingRow] = {}
    for table in data.get("surface") or []:
        row_id = _require_str(table, "id", "[[surface]]")
        if row_id in surfaces:
            raise RoutingPolicyError(f"duplicate surface id: {row_id}")
        _require_str(table, "where", f"surface {row_id}")
        surfaces[row_id] = _build_row(table, row_id, models, f"surface {row_id}")
    if not surfaces:
        raise RoutingPolicyError("policy declares no [[surface]] rows")

    change_classes: dict[str, RoutingRow] = {}
    for name, table in (data.get("change_class") or {}).items():
        surface_ref = _require_str(table, "surface", f"change_class {name}")
        if surface_ref not in surfaces:
            raise RoutingPolicyError(
                f"change_class {name}: unknown surface {surface_ref!r}; "
                f"valid: {sorted(surfaces)}"
            )
        change_classes[name] = _build_row(table, name, models, f"change_class {name}")

    no_llm_table = data.get("no_llm") or {}
    items = no_llm_table.get("items")
    if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
        raise RoutingPolicyError("[no_llm].items must be a list of strings")

    return RoutingPolicy(
        version=version,
        models=dict(models),
        surfaces=surfaces,
        change_classes=change_classes,
        no_llm=tuple(items),
    )


def resolve_surface(policy: RoutingPolicy, surface_id: str) -> RoutingRow:
    row = policy.surfaces.get(surface_id)
    if row is None:
        raise RoutingPolicyError(
            f"unknown surface {surface_id!r}; valid: {sorted(policy.surfaces)}"
        )
    return row


def resolve_change_class(policy: RoutingPolicy, change_class: str) -> RoutingRow:
    row = policy.change_classes.get(change_class)
    if row is None:
        raise RoutingPolicyError(
            f"unknown change-class {change_class!r}; valid: {sorted(policy.change_classes)}"
        )
    return row
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/test_routing.py -v` → all PASS. Then full suite; confirm collected count grew by exactly this file's tests and nothing else changed.

- [ ] **Step 6: Lint, type-check, commit**

```bash
.venv/bin/ruff format src/intent_packages/routing.py tests/test_routing.py
.venv/bin/ruff check src/intent_packages/routing.py tests/test_routing.py
.venv/bin/pyright src/intent_packages/routing.py
git add routing-policy.toml src/intent_packages/routing.py tests/test_routing.py
git commit -m "feat: routing-policy.toml (2026-07-08 seed) + fail-closed loader (WS-P2.10 task 3)"
```

---

### Task 4: `factory route` subcommand

**Files:**
- Modify: `src/intent_packages/factory_cli.py`
- Test: `tests/factory/test_route_cli.py`

**Interfaces:**
- Consumes: `routing.load_policy`, `routing.resolve_surface`, `routing.resolve_change_class`, `routing.RoutingPolicyError` (Task 3).
- Produces: `factory route --surface <id> | --change-class <name> [--policy <path>]`. Output: one `"{row.id}: {slug} ({model_id})"` line per model, then one `"  decided {decided} — {rationale}"` line. Exit 0 on success, 1 on lookup/parse failure (message `route failed: …` on stderr), 2 on argparse misuse (argparse default).

- [ ] **Step 1: Write the failing tests** — through the real entrypoint (`main(argv)`), per repo convention (see `tests/factory/test_factory_cli.py` for the idiom).

```python
"""`factory route` (WS-P2.10): the query consumer of routing-policy.toml.
Session-model choices and handoff "Suggested model" lines cite this command."""

import pytest

from intent_packages.factory_cli import main


def test_route_surface_prints_model_and_rationale(capsys):
    assert main(["route", "--surface", "runner-implementation"]) == 0
    out = capsys.readouterr().out
    assert "runner-implementation: sonnet-5 (claude-sonnet-5)" in out
    assert "decided 2026-07-08" in out


def test_route_change_class_resolves(capsys):
    assert main(["route", "--change-class", "dependency-update"]) == 0
    assert "dependency-update: sonnet-5 (claude-sonnet-5)" in capsys.readouterr().out


def test_route_dual_model_surface_prints_both(capsys):
    assert main(["route", "--surface", "judgment-ac-verification"]) == 0
    out = capsys.readouterr().out
    assert "judgment-ac-verification: fable-5 (claude-fable-5)" in out
    assert "judgment-ac-verification: opus-4-8 (claude-opus-4-8)" in out


def test_route_unknown_surface_exits_1(capsys):
    assert main(["route", "--surface", "nope"]) == 1
    err = capsys.readouterr().err
    assert "route failed:" in err
    assert "nope" in err


def test_route_unknown_change_class_exits_1(capsys):
    assert main(["route", "--change-class", "docs-only"]) == 1
    assert "route failed:" in capsys.readouterr().err


def test_route_requires_exactly_one_selector():
    with pytest.raises(SystemExit) as excinfo:
        main(["route"])
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        main(["route", "--surface", "a", "--change-class", "b"])
    assert excinfo.value.code == 2


def test_route_explicit_policy_path(tmp_path, capsys):
    policy = tmp_path / "p.toml"
    policy.write_text(
        'version = 7\n[models]\nsonnet-5 = "claude-sonnet-5"\n'
        '[no_llm]\nitems = []\n'
        '[[surface]]\nid = "s"\nmodels = ["sonnet-5"]\nwhere = "w"\n'
        'rationale = "r"\ndecided = "2026-07-29"\n',
        encoding="utf-8",
    )
    assert main(["route", "--surface", "s", "--policy", str(policy)]) == 0
    assert "s: sonnet-5 (claude-sonnet-5)" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/factory/test_route_cli.py -v`
Expected: FAIL — argparse `SystemExit: 2` (`invalid choice: 'route'`).

- [ ] **Step 3: Implement**

In `factory_cli.py`, add to module imports: `import sys` and `from pathlib import Path`. In `_build_parser()`, after the `decompose` subparser block:

```python
    r = sub.add_parser(
        "route", help="resolve a model from routing-policy.toml (the sole source of selection)"
    )
    selector = r.add_mutually_exclusive_group(required=True)
    selector.add_argument("--surface", default="", help="surface id, e.g. runner-implementation")
    selector.add_argument(
        "--change-class", dest="change_class", default="", help="change-class name"
    )
    r.add_argument("--policy", default="", help="policy file path (default: repo root)")
```

In `main()`, before the final `return 0`:

```python
    if args.cmd == "route":
        from intent_packages import routing

        try:
            policy = routing.load_policy(Path(args.policy) if args.policy else None)
            row = (
                routing.resolve_surface(policy, args.surface)
                if args.surface
                else routing.resolve_change_class(policy, args.change_class)
            )
        except routing.RoutingPolicyError as error:
            print(f"route failed: {error}", file=sys.stderr)
            return 1
        for slug, model_id in zip(row.models, row.model_ids, strict=True):
            print(f"{row.id}: {slug} ({model_id})")
        print(f"  decided {row.decided} — {row.rationale}")
        return 0
```

Update the module docstring's first line to mention both subcommands (`decompose`, `route`) — it currently says "First subcommand: decompose."

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/factory/test_route_cli.py tests/factory/test_factory_cli.py -v` → all PASS (existing factory_cli tests must stay green).

- [ ] **Step 5: Lint, type-check, commit**

```bash
.venv/bin/ruff format src/intent_packages/factory_cli.py tests/factory/test_route_cli.py
.venv/bin/ruff check src/intent_packages/factory_cli.py tests/factory/test_route_cli.py
.venv/bin/pyright src/intent_packages/factory_cli.py
git add src/intent_packages/factory_cli.py tests/factory/test_route_cli.py
git commit -m "feat: factory route subcommand — query consumer of the routing policy (WS-P2.10 task 4)"
```

---

### Task 5: `DeliveryProfile` base + registry unification (wrap the two existing profiles)

**Files:**
- Create: `src/intent_packages/profiles/base.py`
- Modify: `src/intent_packages/profiles/__init__.py` (registry becomes `dict[str, DeliveryProfile]`)
- Modify: `src/intent_packages/profiles/software_delivery.py`, `src/intent_packages/profiles/infrastructure_change.py` (append a `DELIVERY_PROFILE` instance each; nothing else changes)
- Modify: `tests/test_profiles_dispatch.py` (monkeypatch test injects a `DeliveryProfile`, not a bare function)
- Test: `tests/test_profiles_registry.py`

**Interfaces:**
- Produces (used by Tasks 6–8):
  - `base.AuthorityDefaults` — frozen dataclass: `budgets: Mapping[str, int]`, `capabilities: Mapping[str, str]`, `command_ordering: str`
  - `base.DeliveryProfile` — frozen dataclass, only `name` required; other fields default: `change_class: str | None = None`, `profile_fields_schema: MapSpec | None = None`, `tag_to_evidence_type: Mapping[str, str] = {}`, `forbidden_evidence_types: frozenset[str] = frozenset()`, `required_checks: tuple[str, ...] = ()`, `default_authority: AuthorityDefaults | None = None`, `evidence_expectations: str = ""`, `observation_window: str = ""`, `validate: Callable[[dict], list[str]] | None = None`, `tooling: Mapping[str, ToolingProfile] | None = None`
  - `base.check_forbidden_evidence_types(package: dict, forbidden: frozenset[str]) -> list[str]`
  - `profiles.PROFILES: dict[str, DeliveryProfile]`; `profiles.DeliveryProfile` re-exported; `validate_profile()` signature/no-profile/unknown-profile behavior UNCHANGED
  - Each profile module exports `DELIVERY_PROFILE: DeliveryProfile`

- [ ] **Step 1: Write the failing tests** (`tests/test_profiles_registry.py`)

```python
"""WS-P2.10: the unified DeliveryProfile registry. Existing profiles are
wrapped, not changed — their validation output must be byte-identical (the
Task-1 regression harness enforces that against all 19 real packages; this
file covers the registry mechanics and the shared forbidden-type check)."""

from intent_packages import profiles
from intent_packages.profiles import base


def test_registry_values_are_delivery_profiles():
    assert set(profiles.PROFILES) >= {"software-delivery", "infrastructure-change"}
    for name, profile in profiles.PROFILES.items():
        assert isinstance(profile, base.DeliveryProfile)
        assert profile.name == name


def test_wrapped_existing_profiles_forbid_nothing():
    assert profiles.PROFILES["software-delivery"].forbidden_evidence_types == frozenset()
    assert profiles.PROFILES["infrastructure-change"].forbidden_evidence_types == frozenset()


def test_wrapped_profile_delegates_to_original_validator():
    # A software-delivery package missing profile_fields must produce the same
    # error the pre-unification validator produced.
    errs = profiles.validate_profile({"profile": "software-delivery"})
    assert "profile_fields: missing required key" in errs


def test_forbidden_check_rejects_named_types():
    pkg = {
        "acceptance": [
            {"id": "AC-001", "evidence_type": "automated_test", "evidence": "ci: x"},
            {"id": "AC-002", "evidence_type": "automated_check", "evidence": "ci: y"},
        ]
    }
    errs = base.check_forbidden_evidence_types(pkg, frozenset({"automated_test"}))
    assert len(errs) == 1
    assert errs[0].startswith("acceptance[0].evidence_type:")
    assert "judgment_required" in errs[0]


def test_forbidden_check_empty_set_is_noop():
    pkg = {"acceptance": [{"evidence_type": "automated_test"}]}
    assert base.check_forbidden_evidence_types(pkg, frozenset()) == []


def test_validate_profile_applies_profile_forbid_set(monkeypatch):
    strict = base.DeliveryProfile(
        name="strict-profile", forbidden_evidence_types=frozenset({"automated_test"})
    )
    monkeypatch.setitem(profiles.PROFILES, "strict-profile", strict)
    pkg = {
        "profile": "strict-profile",
        "acceptance": [{"id": "AC-001", "evidence_type": "automated_test", "evidence": "e"}],
    }
    errs = profiles.validate_profile(pkg)
    assert any("forbidden by this profile" in e for e in errs)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_profiles_registry.py -v`
Expected: FAIL with `ImportError` (no `profiles.base`).

- [ ] **Step 3: Implement `profiles/base.py`**

```python
"""DeliveryProfile: the one governed shape for every delivery profile (WS-P2.10).

Profiles layer ABOVE the authority envelope and never modify its shape — the
envelope is a byte-pinned cross-repo contract, and a profile that needs a new
envelope key is out of scope by definition. `default_authority` carries
envelope template PARAMETERS only: defaults, never grants. Every unit still
gets its own fingerprint-bound human authority approval.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from intent_packages.schema import MapSpec

if TYPE_CHECKING:
    from intent_packages.profiles.dependency_update import ToolingProfile


@dataclass(frozen=True)
class AuthorityDefaults:
    """Envelope template parameters for a factory-executable profile.

    budgets.max_llm_calls gates RE-CLAIM ELIGIBILITY, not spend-in-run —
    GAP-4 declared 4 and recorded 15 in one attempt, completing normally.
    The per-attempt cap is factory-runner's max_turns literal, a separate
    number this repo does not control.
    """

    budgets: Mapping[str, int]
    capabilities: Mapping[str, str]
    command_ordering: str


@dataclass(frozen=True)
class DeliveryProfile:
    name: str
    change_class: str | None = None  # non-None => factory-executable => routing row required
    profile_fields_schema: MapSpec | None = None
    tag_to_evidence_type: Mapping[str, str] = field(default_factory=dict)
    forbidden_evidence_types: frozenset[str] = frozenset()
    required_checks: tuple[str, ...] = ()
    default_authority: AuthorityDefaults | None = None
    evidence_expectations: str = ""
    observation_window: str = ""
    validate: Callable[[dict], list[str]] | None = None
    tooling: Mapping[str, ToolingProfile] | None = None


def check_forbidden_evidence_types(package: dict, forbidden: frozenset[str]) -> list[str]:
    """Shared check: reject acceptance items whose evidence_type a profile forbids.

    Scoped per profile so the 14 pre-WS-P2.10 packages (whose profiles forbid
    nothing) stay valid — their YAML cannot be edited without invalidating
    lineage approvals.
    """
    if not forbidden:
        return []
    acceptance = package.get("acceptance")
    if not isinstance(acceptance, list):
        return []
    errors: list[str] = []
    for i, item in enumerate(acceptance):
        if not isinstance(item, dict):
            continue
        evidence_type = item.get("evidence_type")
        if evidence_type in forbidden:
            errors.append(
                f"acceptance[{i}].evidence_type: {evidence_type!r} is forbidden by this "
                f"profile (it resolves to judgment_required in the verifier; use "
                f"'automated_check' backed by a named check, until orchestrator "
                f"remediation 2.1/2.2/2.3 ship together)"
            )
    return errors
```

- [ ] **Step 4: Append `DELIVERY_PROFILE` to the two existing profile modules**

`software_delivery.py` (bottom of file; add `from intent_packages.profiles.base import DeliveryProfile` to imports):

```python
DELIVERY_PROFILE = DeliveryProfile(
    name="software-delivery",
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    evidence_expectations="Tag-mapped producers per TAG_TO_EVIDENCE_TYPE; declared per package.",
    observation_window="Declared per package (follow_up); no profile default.",
    validate=validate,
)
```

`infrastructure_change.py` (same import; bottom of file):

```python
DELIVERY_PROFILE = DeliveryProfile(
    name="infrastructure-change",
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    evidence_expectations="Tag-mapped producers per TAG_TO_EVIDENCE_TYPE; declared per package.",
    observation_window="Declared per package (follow_up); no profile default.",
    validate=validate,
)
```

- [ ] **Step 5: Rework `profiles/__init__.py`**

```python
"""Delivery-profile registry and dispatch (WS-2.2 spec §2; unified WS-P2.10).

A profile extends the universal intent-package envelope via the reserved
`profile`/`profile_fields` keys — it never adds a new top-level `package.yaml`
key. `validate_profile()` is called from `validate.validate_package()` as
check P after the universal checks pass.
"""

from __future__ import annotations

from intent_packages.profiles import base, infrastructure_change, software_delivery
from intent_packages.profiles.base import AuthorityDefaults, DeliveryProfile

__all__ = [
    "PROFILES",
    "KNOWN_EVIDENCE_PREFIXES",
    "AuthorityDefaults",
    "DeliveryProfile",
    "validate_profile",
]

PROFILES: dict[str, DeliveryProfile] = {
    p.name: p
    for p in (
        software_delivery.DELIVERY_PROFILE,
        infrastructure_change.DELIVERY_PROFILE,
    )
}
KNOWN_EVIDENCE_PREFIXES = frozenset(
    {"ci:", "gate:", "scan:", "review:", "health:", "human:", "plan:", "backup:"}
)


def validate_profile(package: dict) -> list[str]:
    """Check P: dispatch to the named profile, if any.

    Returns [] when `profile` is absent/null (a universal-only package is
    unaffected). Returns a single actionable error naming the valid choices
    when `profile` is set to an unregistered name. Otherwise runs the
    profile's validator plus the shared forbidden-evidence-type check.
    """
    name = package.get("profile")
    if name is None:
        errors = []
        if "profile_fields" in package:
            errors.append("profile_fields: requires a declared profile")
        return errors
    if not isinstance(name, str):
        return []  # _check_k_and_j already reports "profile: expected str"
    if name not in PROFILES:
        return [f"profile: unknown profile {name!r}; valid: {sorted(PROFILES)}"]
    profile = PROFILES[name]
    errors = list(profile.validate(package)) if profile.validate else []
    errors.extend(base.check_forbidden_evidence_types(package, profile.forbidden_evidence_types))
    return errors
```

- [ ] **Step 6: Fix the monkeypatch test in `tests/test_profiles_dispatch.py`**

Replace the body of `test_known_profile_delegates_to_its_validator` — the injection becomes a `DeliveryProfile` (behavioral contract unchanged; only the registry value type changed):

```python
def test_known_profile_delegates_to_its_validator(monkeypatch):
    calls = []

    def fake_validate(package):
        calls.append(package)
        return ["fake error from the profile validator"]

    fake = profiles.DeliveryProfile(name="fake-profile", validate=fake_validate)
    monkeypatch.setitem(profiles.PROFILES, "fake-profile", fake)
    pkg = {"profile": "fake-profile", "title": "x"}

    errs = profiles.validate_profile(pkg)

    assert errs == ["fake error from the profile validator"]
    assert calls == [pkg]
```

No other test in that file changes.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest`
Expected: everything green, including `tests/test_packages_regression.py` (proves the 19 real packages validate identically) and `tests/test_profiles_compat.py` (locked hash). Read the collected count.

- [ ] **Step 8: Lint, type-check, commit**

```bash
.venv/bin/ruff format src/intent_packages/profiles/ tests/test_profiles_registry.py tests/test_profiles_dispatch.py
.venv/bin/ruff check src/intent_packages/profiles/ tests/test_profiles_registry.py tests/test_profiles_dispatch.py
.venv/bin/pyright src/intent_packages/profiles/
git add -A src/intent_packages/profiles tests/test_profiles_registry.py tests/test_profiles_dispatch.py
git commit -m "feat: DeliveryProfile dataclass + unified registry; wrap existing profiles unchanged (WS-P2.10 task 5)"
```

---

### Task 6: dependency-update becomes a declarable profile; tooling registry renamed

**Files:**
- Modify: `src/intent_packages/profiles/dependency_update.py` — rename module-level `PROFILES` → `TOOLING_PROFILES` (ends the name collision with the domain registry); add `PROFILE_FIELDS_SCHEMA`, `TAG_TO_EVIDENCE_TYPE`, `validate`, `DELIVERY_PROFILE`
- Modify: `src/intent_packages/factory/decompose.py` — two import sites (`from intent_packages.profiles.dependency_update import PROFILES` at line ~113 and the `PROFILES[tooling]` uses in `run()`; `build_envelope` in `dependency_update.py` also references the dict at lines ~223-225)
- Modify: `src/intent_packages/profiles/__init__.py` — register `dependency_update.DELIVERY_PROFILE`
- Modify: any test importing `PROFILES` from `dependency_update` — run `grep -rn "dependency_update import\|dependency_update\." tests/` and update each hit (expected: `tests/factory/test_profiles_dependency_update.py`, possibly `tests/factory/test_decompose.py`)
- Test: `tests/test_profile_dependency_update.py` (new)

**Interfaces:**
- Consumes: `base.DeliveryProfile`, `base.AuthorityDefaults`, `schema.MapSpec/_s/_walk`, `_evidence_tags.check_evidence_tags`.
- Produces: `dependency_update.TOOLING_PROFILES: dict[str, ToolingProfile]` (was `PROFILES`; same keys `npm|pip|uv`, same values); `dependency_update.DELIVERY_PROFILE` registered as `"dependency-update"` with `change_class="dependency-update"` and `tooling=TOOLING_PROFILES`. `build_envelope` behavior and output byte-identical.

- [ ] **Step 1: Write the failing tests** (`tests/test_profile_dependency_update.py`)

```python
"""dependency-update as a declarable delivery profile (WS-P2.10): formalizes
what GAP-4 proved in production. The tooling half (pin discovery, mutators,
envelope) is unchanged and covered by tests/factory/."""

import pytest

from intent_packages import profiles
from intent_packages.profiles import dependency_update
from intent_packages.profiles.dependency_update import PinSite, build_envelope


def test_registered_with_change_class_and_tooling():
    profile = profiles.PROFILES["dependency-update"]
    assert profile.change_class == "dependency-update"
    assert profile.tooling is dependency_update.TOOLING_PROFILES
    assert set(profile.tooling) == {"npm", "pip", "uv"}
    assert profile.forbidden_evidence_types == frozenset({"automated_test"})
    assert profile.default_authority is not None
    assert profile.default_authority.budgets["max_attempts"] == 3


def _pkg(profile_fields: dict, acceptance: list) -> dict:
    return {"profile": "dependency-update", "profile_fields": profile_fields, "acceptance": acceptance}


VALID_FIELDS = {
    "target_repo": "AlobarQuest/change-manager",
    "package": "httpx2",
    "from_version": "2.8.0",
    "to_version": "2.9.1",
}
VALID_AC = [
    {
        "id": "AC-001",
        "condition": "pin moved and named check passes",
        "evidence_type": "automated_check",
        "evidence": "ci: named check on the PR head",
        "approver": "role:verifier",
    }
]


def test_valid_package_passes():
    assert profiles.validate_profile(_pkg(VALID_FIELDS, VALID_AC)) == []


def test_missing_profile_field_fails():
    fields = {k: v for k, v in VALID_FIELDS.items() if k != "to_version"}
    errs = profiles.validate_profile(_pkg(fields, VALID_AC))
    assert "profile_fields.to_version: missing required key" in errs


def test_automated_test_is_a_validation_failure():
    bad_ac = [dict(VALID_AC[0], evidence_type="automated_test")]
    errs = profiles.validate_profile(_pkg(VALID_FIELDS, bad_ac))
    # Rejected twice, deliberately: the tag map pins ci: -> automated_check,
    # and the forbid set names automated_test explicitly.
    assert any("forbidden by this profile" in e for e in errs)


def test_unrecognized_evidence_tag_fails():
    bad_ac = [dict(VALID_AC[0], evidence="scan: not in this profile's tag map")]
    errs = profiles.validate_profile(_pkg(VALID_FIELDS, bad_ac))
    assert any("does not start with a recognized producer tag" in e for e in errs)


def test_empty_string_field_fails():
    errs = profiles.validate_profile(_pkg(dict(VALID_FIELDS, package="  "), VALID_AC))
    assert "profile_fields.package: must be a non-empty string" in errs


def test_envelope_key_set_is_the_pinned_contract():
    envelope = build_envelope(
        "AlobarQuest/x",
        "uv",
        "httpx2",
        "2.8.0",
        "2.9.1",
        {"scanner": "real"},
        [PinSite("pyproject.toml", "dependency-groups.dev", "2.8.0")],
    )
    assert set(envelope) == {"budgets", "capabilities", "change_class", "conformance", "constraints"}
    assert set(envelope["constraints"]) == {
        "allowed_commands",
        "mutation_commands",
        "target_repository",
    }
    assert envelope["constraints"]["allowed_commands"][-1] == "uv lock --check"


def test_old_registry_name_is_gone():
    with pytest.raises(AttributeError):
        dependency_update.PROFILES  # noqa: B018
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_profile_dependency_update.py -v`
Expected: FAIL — `KeyError: 'dependency-update'` / `AttributeError: TOOLING_PROFILES`.

- [ ] **Step 3: Implement the rename** — in `dependency_update.py` change `PROFILES: dict[str, ToolingProfile] = {` to `TOOLING_PROFILES: dict[str, ToolingProfile] = {` and update its two uses in `build_envelope` (`if tooling not in TOOLING_PROFILES` / `TOOLING_PROFILES[tooling]`). In `factory/decompose.py`, update the lazy import inside `run()`: `from intent_packages.profiles.dependency_update import TOOLING_PROFILES` and its two uses (`if tooling not in TOOLING_PROFILES` / `TOOLING_PROFILES[tooling].discover_pin_sites`). Then `grep -rn "import PROFILES\|dependency_update.PROFILES" src/ tests/` — zero hits may remain except the domain registry in `profiles/__init__.py`.

- [ ] **Step 4: Implement the declarable profile** — append to `dependency_update.py` (new imports at top: `from intent_packages.profiles._evidence_tags import check_evidence_tags`, `from intent_packages.profiles.base import AuthorityDefaults, DeliveryProfile`, `from intent_packages.schema import MapSpec, _s, _walk`):

```python
# ----- declarable delivery profile (WS-P2.10) -----

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "target_repo": _s(str),
        "package": _s(str),
        "from_version": _s(str),
        "to_version": _s(str),
    }
)

# Never automated_test: it resolves to judgment_required in the verifier.
# ci:/gate: evidence for this profile is verifier-owned named-check evidence,
# which is exactly what automated_check evaluates deterministically against.
TAG_TO_EVIDENCE_TYPE = {
    "ci:": "automated_check",
    "gate:": "automated_check",
    "human:": "human_review",
}

_NON_EMPTY_STRING_FIELDS = ("target_repo", "package", "from_version", "to_version")


def _check_profile_fields(package: dict) -> list[str]:
    errors: list[str] = []
    if "profile_fields" not in package:
        errors.append("profile_fields: missing required key")
        return errors
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        return errors
    _walk(fields, PROFILE_FIELDS_SCHEMA, "profile_fields", errors)
    if errors:
        return errors
    for key in _NON_EMPTY_STRING_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and not value.strip():
            errors.append(f"profile_fields.{key}: must be a non-empty string")
    return errors


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors


DELIVERY_PROFILE = DeliveryProfile(
    name="dependency-update",
    change_class="dependency-update",
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    forbidden_evidence_types=frozenset({"automated_test"}),
    required_checks=("target repo's own named check on the PR head",),
    default_authority=AuthorityDefaults(
        budgets=BUDGETS,
        capabilities=CAPABILITIES,
        command_ordering="mutators first, verifier last; make check never in an envelope",
    ),
    evidence_expectations=(
        "Runner-opened PR; verifier-owned named-check evidence "
        "(verifier.github.named_check) on the PR head; adjudication via "
        "evidence_type automated_check. budgets.max_attempts bounds claims; "
        "budgets.max_llm_calls bounds re-claim eligibility, not spend-in-run."
    ),
    observation_window=(
        "None beyond the named check: a pin move ships no runtime change of its "
        "own, so observation rides the target repo's ordinary release lane."
    ),
    validate=validate,
    tooling=TOOLING_PROFILES,
)
```

Register in `profiles/__init__.py`: add `dependency_update` to the module import line and `dependency_update.DELIVERY_PROFILE,` to the registry tuple.

- [ ] **Step 5: Fix broken imports in existing tests** — from the Step 3 grep, update `tests/factory/test_profiles_dependency_update.py` (and any other hit) to import/reference `TOOLING_PROFILES`. Do not weaken any assertion.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest`
Expected: green, including all of `tests/factory/` and the Task-1 regression harness. Read the collected count.

- [ ] **Step 7: Lint, type-check, commit**

```bash
.venv/bin/ruff format src/intent_packages/profiles/dependency_update.py src/intent_packages/factory/decompose.py src/intent_packages/profiles/__init__.py tests/
.venv/bin/ruff check src/ tests/
.venv/bin/pyright src/intent_packages/profiles/ src/intent_packages/factory/
git add -A src tests
git commit -m "feat: dependency-update declarable profile; TOOLING_PROFILES rename ends registry collision (WS-P2.10 task 6)"
```

---

### Task 7: `maintenance-remediation` profile

**Files:**
- Create: `src/intent_packages/profiles/maintenance_remediation.py`
- Modify: `src/intent_packages/profiles/__init__.py` (register)
- Test: `tests/test_profile_maintenance_remediation.py`

**Interfaces:**
- Consumes: `OptionalKey` (Task 2), `base` (Task 5), `dependency_update.BUDGETS/CAPABILITIES` (single source for the shared envelope defaults — do not copy the dicts).
- Produces: registry entry `"maintenance-remediation"`, `change_class="maintenance-remediation"` (routing row already seeded in Task 3).

- [ ] **Step 1: Write the failing tests**

```python
"""maintenance-remediation profile (WS-P2.10): Phase-3 WS-P3.2's authoring
target — a bounded fix in an existing repo from an approved handoff item.
First consumer of OptionalKey (pr_url)."""

from intent_packages import profiles

VALID_FIELDS = {
    "repo": "AlobarQuest/change-manager",
    "remediation_source": "change-manager item 4711 (app-conformance lane)",
    "rollback_plan": "revert the PR; no data migration involved",
}
VALID_AC = [
    {
        "id": "AC-001",
        "condition": "fix lands and named check passes",
        "evidence_type": "automated_check",
        "evidence": "ci: named check on the PR head",
        "approver": "role:verifier",
    },
    {
        "id": "AC-002",
        "condition": "human confirms the remediation closes the handoff item",
        "evidence_type": "human_review",
        "evidence": "human: Devon reviews the closed item",
        "approver": "human:devon",
    },
]


def _pkg(fields: dict, acceptance: list) -> dict:
    return {"profile": "maintenance-remediation", "profile_fields": fields, "acceptance": acceptance}


def test_registered_factory_executable():
    profile = profiles.PROFILES["maintenance-remediation"]
    assert profile.change_class == "maintenance-remediation"
    assert profile.forbidden_evidence_types == frozenset({"automated_test"})
    assert profile.tooling is None  # no decompose lane yet; authoring-time only


def test_valid_package_without_pr_url_passes():
    assert profiles.validate_profile(_pkg(VALID_FIELDS, VALID_AC)) == []


def test_valid_package_with_pr_url_passes():
    fields = dict(VALID_FIELDS, pr_url="https://github.com/AlobarQuest/change-manager/pull/34")
    assert profiles.validate_profile(_pkg(fields, VALID_AC)) == []


def test_pr_url_wrong_type_fails():
    errs = profiles.validate_profile(_pkg(dict(VALID_FIELDS, pr_url=34), VALID_AC))
    assert "profile_fields.pr_url: expected str, got int" in errs


def test_missing_required_field_fails():
    fields = {k: v for k, v in VALID_FIELDS.items() if k != "rollback_plan"}
    errs = profiles.validate_profile(_pkg(fields, VALID_AC))
    assert "profile_fields.rollback_plan: missing required key" in errs


def test_automated_test_forbidden():
    bad = [dict(VALID_AC[0], evidence_type="automated_test")]
    errs = profiles.validate_profile(_pkg(VALID_FIELDS, bad))
    assert any("forbidden by this profile" in e for e in errs)


def test_unknown_key_in_profile_fields_fails():
    errs = profiles.validate_profile(_pkg(dict(VALID_FIELDS, branch="main"), VALID_AC))
    assert "profile_fields.branch: unknown key" in errs
```

(That last test is deliberate: `branch` was the decoration field remediation 6.1 flagged in software-delivery — this profile does not carry it.)

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_profile_maintenance_remediation.py -v` → `KeyError`/unknown-profile errors.

- [ ] **Step 3: Implement `profiles/maintenance_remediation.py`**

```python
"""Maintenance-remediation delivery profile (WS-P2.10): a bounded fix in an
existing repository, authored from an approved handoff item. Phase-3 WS-P3.2
emits proposed packages against this profile; every proposal still terminates
at the four human gates."""

from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.profiles.base import AuthorityDefaults, DeliveryProfile
from intent_packages.profiles.dependency_update import BUDGETS, CAPABILITIES
from intent_packages.schema import MapSpec, OptionalKey, _s, _walk

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "repo": _s(str),
        "remediation_source": _s(str),
        "rollback_plan": _s(str),
        "pr_url": OptionalKey(_s(str)),
    }
)

TAG_TO_EVIDENCE_TYPE = {
    "ci:": "automated_check",
    "gate:": "automated_check",
    "human:": "human_review",
}

_NON_EMPTY_STRING_FIELDS = ("repo", "remediation_source", "rollback_plan")


def _check_profile_fields(package: dict) -> list[str]:
    errors: list[str] = []
    if "profile_fields" not in package:
        errors.append("profile_fields: missing required key")
        return errors
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        return errors
    _walk(fields, PROFILE_FIELDS_SCHEMA, "profile_fields", errors)
    if errors:
        return errors
    for key in _NON_EMPTY_STRING_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and not value.strip():
            errors.append(f"profile_fields.{key}: must be a non-empty string")
    pr_url = fields.get("pr_url")
    if isinstance(pr_url, str) and not pr_url.strip():
        errors.append("profile_fields.pr_url: must be a non-empty string when present")
    return errors


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors


DELIVERY_PROFILE = DeliveryProfile(
    name="maintenance-remediation",
    change_class="maintenance-remediation",
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    forbidden_evidence_types=frozenset({"automated_test"}),
    required_checks=("target repo's own named check on the PR head",),
    default_authority=AuthorityDefaults(
        budgets=BUDGETS,
        capabilities=CAPABILITIES,
        command_ordering="mutators first, verifier last; make check never in an envelope",
    ),
    evidence_expectations=(
        "Runner-opened PR; verifier-owned named-check evidence on the PR head "
        "(automated_check); a human_review AC confirming the handoff item is "
        "closed. budgets.max_llm_calls bounds re-claim eligibility, not "
        "spend-in-run."
    ),
    observation_window=(
        "Declared per package via follow_up; remediations to running services "
        "should declare follow_up.required=true."
    ),
    validate=validate,
)
```

Register in `profiles/__init__.py` (import the module, add `maintenance_remediation.DELIVERY_PROFILE,` to the tuple).

- [ ] **Step 4: Run tests + full suite** — new file green; full suite green including regression harness.

- [ ] **Step 5: Lint, type-check, commit**

```bash
.venv/bin/ruff format src/intent_packages/profiles/ tests/test_profile_maintenance_remediation.py
.venv/bin/ruff check src/intent_packages/profiles/ tests/test_profile_maintenance_remediation.py
.venv/bin/pyright src/intent_packages/profiles/
git add src/intent_packages/profiles tests/test_profile_maintenance_remediation.py
git commit -m "feat: maintenance-remediation profile (Phase-3 WS-P3.2 authoring target) (WS-P2.10 task 7)"
```

---

### Task 8: `non-software-operational` profile

**Files:**
- Create: `src/intent_packages/profiles/non_software_operational.py`
- Modify: `src/intent_packages/profiles/__init__.py` (register + add `"external:"`, `"observation:"` to `KNOWN_EVIDENCE_PREFIXES`)
- Test: `tests/test_profile_non_software_operational.py`

**Interfaces:**
- Consumes: `OptionalKey`, `base`. NOT `dependency_update` — this profile has no envelope, no tooling, no change class.
- Produces: registry entry `"non-software-operational"` with `change_class=None`, `default_authority=None`, `tooling=None`. Reference exemplar is `packages/ws-2.4-historical-listing-launch/` (universal-only; its YAML is NEVER edited — WS-P2.13 authors the first package declaring this profile).

- [ ] **Step 1: Write the failing tests**

```python
"""non-software-operational profile (WS-P2.10): the WS-P2.13 vehicle, shaped
from the historical listing-launch package. No repo, no CI, no authority
envelope — evidence is human/external/observation only, so automated_test is
structurally unreachable AND explicitly forbidden."""

from intent_packages import profiles

VALID_FIELDS = {
    "owner": "Devon",
    "operating_procedure": "listing-description skill + listing-launch checklist",
}
VALID_AC = [
    {
        "id": "AC-001",
        "condition": "listing is live on the MLS",
        "evidence_type": "external_attestation",
        "evidence": "external: MLS listing number recorded",
        "approver": "external:mls",
    },
    {
        "id": "AC-002",
        "condition": "Devon confirms marketing assets shipped",
        "evidence_type": "human_review",
        "evidence": "human: Devon signs off",
        "approver": "human:devon",
    },
]


def _pkg(fields: dict, acceptance: list) -> dict:
    return {
        "profile": "non-software-operational",
        "profile_fields": fields,
        "acceptance": acceptance,
    }


def test_registered_without_envelope_or_tooling():
    profile = profiles.PROFILES["non-software-operational"]
    assert profile.change_class is None
    assert profile.default_authority is None
    assert profile.tooling is None
    assert profile.forbidden_evidence_types == frozenset({"automated_test"})


def test_valid_package_passes():
    assert profiles.validate_profile(_pkg(VALID_FIELDS, VALID_AC)) == []


def test_optional_external_systems_list():
    fields = dict(VALID_FIELDS, external_systems=["MLS", "Zillow"])
    assert profiles.validate_profile(_pkg(fields, VALID_AC)) == []
    bad = dict(VALID_FIELDS, external_systems="MLS")
    errs = profiles.validate_profile(_pkg(bad, VALID_AC))
    assert "profile_fields.external_systems: expected a list, got str" in errs


def test_ci_tag_is_not_in_this_profiles_vocabulary():
    bad = [dict(VALID_AC[0], evidence="ci: something automated")]
    errs = profiles.validate_profile(_pkg(VALID_FIELDS, bad))
    assert any("does not start with a recognized producer tag" in e for e in errs)


def test_observation_tag_maps_to_observation_type():
    ac = [
        dict(
            VALID_AC[0],
            evidence="observation: post-launch signals recorded",
            evidence_type="observation",
            approver="role:verifier",
        )
    ]
    assert profiles.validate_profile(_pkg(VALID_FIELDS, ac)) == []


def test_missing_owner_fails():
    errs = profiles.validate_profile(_pkg({"operating_procedure": "x"}, VALID_AC))
    assert "profile_fields.owner: missing required key" in errs


def test_new_prefixes_are_known():
    assert {"external:", "observation:"} <= profiles.KNOWN_EVIDENCE_PREFIXES
```

Note on `test_observation_tag_maps_to_observation_type`: universal check A restricts `external:` approvers to `{external_attestation, human_review}` evidence types, but check A runs in `validate_package`, not in `validate_profile` — this test goes through `validate_profile` only, so `approver` just needs to be shaped consistently for the profile checks. Keep `role:verifier` as written.

- [ ] **Step 2: Run to verify failure** — unknown-profile errors expected.

- [ ] **Step 3: Implement `profiles/non_software_operational.py`**

```python
"""Non-software-operational delivery profile (WS-P2.10): work with no repo,
no CI, and no authority envelope — listing launches and similar operational
workflows. Shaped from packages/ws-2.4-historical-listing-launch (the
reference exemplar); WS-P2.13's native run authors the first package that
declares it. Evidence comes from humans, external systems, and observations
only — the tag map has no ci:/gate: entries, so automated_test is
structurally unreachable, and it is explicitly forbidden for defense in
depth."""

from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.profiles.base import DeliveryProfile
from intent_packages.schema import ListSpec, MapSpec, OptionalKey, _s, _walk

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "owner": _s(str),
        "operating_procedure": _s(str),
        "external_systems": OptionalKey(ListSpec(_s(str))),
    }
)

TAG_TO_EVIDENCE_TYPE = {
    "human:": "human_review",
    "external:": "external_attestation",
    "observation:": "observation",
}

_NON_EMPTY_STRING_FIELDS = ("owner", "operating_procedure")


def _check_profile_fields(package: dict) -> list[str]:
    errors: list[str] = []
    if "profile_fields" not in package:
        errors.append("profile_fields: missing required key")
        return errors
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        return errors
    _walk(fields, PROFILE_FIELDS_SCHEMA, "profile_fields", errors)
    if errors:
        return errors
    for key in _NON_EMPTY_STRING_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and not value.strip():
            errors.append(f"profile_fields.{key}: must be a non-empty string")
    return errors


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors


DELIVERY_PROFILE = DeliveryProfile(
    name="non-software-operational",
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    forbidden_evidence_types=frozenset({"automated_test"}),
    evidence_expectations=(
        "human_review, external_attestation, and observation only; no automated "
        "producers exist for this profile's work."
    ),
    observation_window=(
        "Declared per package via follow_up (e.g. days-on-market signals for a "
        "listing launch)."
    ),
    validate=validate,
)
```

Register in `profiles/__init__.py`, and extend the prefix set:

```python
KNOWN_EVIDENCE_PREFIXES = frozenset(
    {
        "ci:",
        "gate:",
        "scan:",
        "review:",
        "health:",
        "human:",
        "plan:",
        "backup:",
        "external:",
        "observation:",
    }
)
```

- [ ] **Step 4: Run tests + full suite** — the `KNOWN_EVIDENCE_PREFIXES` extension changes only the non-blocking warning path (`validate.validate_warnings`); the Task-1 harness proves no real package's error output changed. If any warning-related test asserts the exact prefix set, update it deliberately and say so in the commit message.

- [ ] **Step 5: Lint, type-check, commit**

```bash
.venv/bin/ruff format src/intent_packages/profiles/ tests/test_profile_non_software_operational.py
.venv/bin/ruff check src/intent_packages/profiles/ tests/test_profile_non_software_operational.py
.venv/bin/pyright src/intent_packages/profiles/
git add src/intent_packages/profiles tests/test_profile_non_software_operational.py
git commit -m "feat: non-software-operational profile (WS-P2.13 vehicle) (WS-P2.10 task 8)"
```

---

### Task 9: decompose consumes the routing policy (fail-closed) + rationale provenance

**Files:**
- Modify: `src/intent_packages/factory/decompose.py`
- Test: extend `tests/factory/test_decompose.py` (follow its existing fake-client fixture idiom)

**Interfaces:**
- Consumes: `routing` (Task 3). The change-class is read from the built proposal: `proposal["proposed_units"][0]["authority"]["change_class"]` — the authoritative value, not a parallel constant.
- Produces: `decompose.run(..., policy_path: Path | None = None)` — new keyword-only param, default `None` (= repo policy). On a change-class with no routing row: exit 1, `decompose failed: unknown change-class …` on stderr, BEFORE any submit. On success: proposal `rationale` gains `" routing: {slugs} per routing-policy v{version}."` where slugs is `"/".join(row.models)`. This is advisory provenance, not enforcement — the orchestrator ignores unknown unit fields, so the resolution is recorded in prose, never stamped as a field.

- [ ] **Step 1: Write the failing tests** — add to `tests/factory/test_decompose.py`, reusing its existing fixtures/fakes for `client`, repo checkout, and pin site (read the file first; mirror the setup of an existing passing test):

```python
def test_routing_note_lands_in_rationale(...existing fixture args...):
    # arrange exactly as the existing happy-path decompose test does,
    # capture the emitted proposal JSON (via --out to a tmp file or stdout)
    ...
    proposal = json.loads(out_path.read_text())
    assert proposal["rationale"].endswith(" routing: sonnet-5 per routing-policy v1.")


def test_missing_routing_row_fails_closed(tmp_path, capsys, ...):
    # a policy file with no change_class table at all
    policy = tmp_path / "p.toml"
    policy.write_text(
        'version = 1\n[models]\nsonnet-5 = "claude-sonnet-5"\n'
        '[no_llm]\nitems = []\n'
        '[[surface]]\nid = "runner-implementation"\nmodels = ["sonnet-5"]\n'
        'where = "w"\nrationale = "r"\ndecided = "2026-07-29"\n',
        encoding="utf-8",
    )
    rc = decompose.run(..., policy_path=policy)
    assert rc == 1
    err = capsys.readouterr().err
    assert "decompose failed:" in err
    assert "unknown change-class" in err
```

(The implementer fills the `...` from the file's real fixture names — the two assertions above are the contract; the arrangement is whatever the existing happy-path test already does. Do not invent new fixtures if the file has them.)

- [ ] **Step 2: Run to verify failure** — first test fails on the missing rationale suffix; second on `TypeError: unexpected keyword argument 'policy_path'`.

- [ ] **Step 3: Implement** — in `decompose.py`:

Add imports: `from intent_packages import routing` (top-level import is fine; routing has no heavy deps).

Extend `run()`'s signature (keyword section, after `submit: bool`):

```python
    policy_path: Path | None = None,
```

Inside the `try:` block, immediately after `proposal = build_proposal(...)` and before the `allowed = ...` line:

```python
        change_class = proposal["proposed_units"][0]["authority"]["change_class"]
        policy = routing.load_policy(policy_path)
        row = routing.resolve_change_class(policy, change_class)
        proposal["rationale"] += (
            f" routing: {'/'.join(row.models)} per routing-policy v{policy.version}."
        )
```

Add `routing.RoutingPolicyError` to the `except` tuple at the bottom of `run()`:

```python
    except (
        DecomposeError,
        ValidationError,
        OrchestratorCliError,
        ProfileError,
        routing.RoutingPolicyError,
    ) as error:
```

Do NOT thread `--policy` through `factory decompose`'s argparse — production always uses the repo policy; the parameter exists for tests. (If a reviewer wants the flag later it is a two-line addition.)

- [ ] **Step 4: Run the factory suite + full suite**

Run: `.venv/bin/pytest tests/factory/ -v` → all PASS. Any pre-existing decompose test asserting the exact `rationale` string must be updated to expect the routing suffix — that is the intended behavior change; note it in the commit message. Then full suite.

- [ ] **Step 5: Lint, type-check, commit**

```bash
.venv/bin/ruff format src/intent_packages/factory/decompose.py tests/factory/test_decompose.py
.venv/bin/ruff check src/intent_packages/factory/ tests/factory/
.venv/bin/pyright src/intent_packages/factory/
git add src/intent_packages/factory/decompose.py tests/factory/test_decompose.py
git commit -m "feat: decompose fails closed on missing routing row; records routing provenance (WS-P2.10 task 9)"
```

---

### Task 10: README + final whole-repo gate

**Files:**
- Modify: `README.md` — add a short section (place it after the existing profiles/validation description; match the README's current tone and heading level): the five registered profiles with one-line descriptions; `routing-policy.toml` as the sole source of model selection with the `factory route` example; a pointer to the design doc for the named stubs (docs-only, python-service, ts-service, emergency-remediation).

- [ ] **Step 1: Write the README section** (adapt heading level to the file):

```markdown
## Delivery profiles

Registered profiles (declared via `profile:` in package.yaml; validated at
authoring time by `intent_packages validate`):

- `software-delivery` — repo-backed delivery (WS-2.2)
- `infrastructure-change` — infra changes with blast-radius vocabulary (WS-2.2)
- `dependency-update` — factory-executable pin moves; production-proven (GAP-4)
- `maintenance-remediation` — bounded fix from an approved handoff item (Phase-3 authoring target)
- `non-software-operational` — no-repo operational work (listing launches; WS-P2.13 vehicle)

Named stubs (not registered; owners and promotion triggers in
`docs/superpowers/specs/2026-07-29-wsp210-profiles-routing-policy-design.md`):
docs-only, python-service, ts-service, emergency-remediation.

## Model routing

`routing-policy.toml` (repo root) is the sole source of model selection
(program exit criterion #11), seeded from the decided 2026-07-08 table.
Query it:

    factory route --surface runner-implementation
    factory route --change-class dependency-update

`factory decompose` fails closed if a change-class has no routing row.
Graduation edits follow the contract in the file's header comment.
```

- [ ] **Step 2: Run the full gate**

```bash
make check
```

Expected: ruff check clean, `ruff format --check` clean, pyright clean, pytest green. **Read the collected count** — expect roughly 197 baseline + ~90 new (Task 1: 39, Task 2: 7, Task 3: 10, Task 4: 7, Task 5: 6, Task 6: 8, Task 7: 7, Task 8: 7, Task 9: 2 — confirm the real numbers; the point is the count grew and nothing silently vanished). If format --check fails on files this branch never touched, diff against `main` before blaming the branch (pre-existing format debt is a known class — fix it in a separate commit or flag it).

- [ ] **Step 3: Verify the working tree is clean and the branch is coherent**

```bash
git status
git log --oneline main..HEAD
```

Expected: clean tree; ~10 commits, one per task.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README — delivery profiles + routing policy (WS-P2.10 task 10)"
```

---

## Out of scope (deliberately — do not add)

- Any orchestrator or factory-runner change; any new authority-envelope key.
- The `follow_up` cadence/recurrence field (deferred with rationale — design §7).
- Intake-side profile enforcement (authoring-time only — design decision Q4).
- Continuous cross-repo assertion of factory-runner's workflow model (ship-time check is closeout evidence, gathered by the orchestrating session, not this plan).
- `factory decompose` deriving its CLI args from a declared dependency-update package (named follow-up).
- Registering stub profiles.

## After the plan completes (orchestrating session, not implementers)

Final adversarial whole-branch review (budget for kills) → `/code-review` → Devon merges → ship-time factory-runner model assertion → closeout note in `~/docs/software-delivery-system/` updating the Phase-2 plan header + scorecard cell #11 (no `exit-criteria-claims.toml` entry — #11 cites no routes; state that explicitly) → Part 2b seeded-from annotation.
