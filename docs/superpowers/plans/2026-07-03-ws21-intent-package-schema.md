# WS-2.1 Intent-Package Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the universal intent-package schema, lifecycle state machine, and the zero-install
`validate/hash/transition/approve/revise/supersede/verify-approval` CLI, per the spec
`docs/superpowers/specs/2026-07-03-ws21-intent-package-schema.md`.

**Architecture:** A `PYTHONPATH=src python3 -m intent_packages` module (mirrors security-standards
`agent_registry`). Small focused modules: strict YAML loading, canonical hashing (RFC 8785 JCS over the
intent core minus `status`), a data-driven lifecycle, a registry adapter (capability vocabulary + agent
ids from the sibling security-standards checkout), lineage read/write, semantic validation, an injectable
factory-events emitter, the state-changing operations, and an argparse CLI. Packages live under
`packages/<id>/` as `package.yaml` + `lineage.yaml`.

**Tech Stack:** Python 3.12+, PyYAML, pytest. No install (`pythonpath=["src"]`). Emits factory events by
shelling out to the security-standards `factory_events` CLI.

## Global Constraints
- Python **3.12+**. Zero-install: `package-dir={"" = "src"}`, `pythonpath=["src"]`; run as `python -m intent_packages`.
- **Hash = `sha256_hex(JCS(intent_core))`**, `intent_core` = `package.yaml` mapping **minus the single key `status`**. JCS = RFC 8785.
- **Strict YAML typing** (hash determinism): scalars are only `str|int|bool|None`; **no floats, no datetime/date, single YAML document, every documented key present** (explicit `null`/`[]`).
- **Authority default-deny:** a capability term in none of `allowed`/`requires_approval`/`prohibited` is prohibited; a term in >1 list is an error; a term outside the 17-term vocabulary is an error (degrade to warning if the registry can't be located).
- **Approver forms:** `policy` | a registry agent id | `external:<label>` (last only when `evidence_type ∈ {external_attestation, human_review}`).
- **Registry location:** env `SECURITY_STANDARDS_DIR`, default sibling `~/Projects/security-standards`. Capability vocab: `registry/capabilities.yaml`; agent ids: `registry/agents/<id>.yaml` (`authority_profile` field → human-operator check via profile `human-operator-v1`).
- **Emit seam:** shell out to `PYTHONPATH=$SEC/src <py> -m factory_events emit --actor $FACTORY_AGENT_ID --action package.<x> --ref <package_id> --result success --evidence-json '{...}'`. `approve` emit is **fatal**; other transitions best-effort (`event_id: null` + `emit_error` on failure). Emitter is injectable; `NullEmitter` for tests.
- **Commit discipline:** TDD; commit after each task. Commit trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01Deo4kuD6pB78xQ49uCNke9`.
- All work on branch `feat/ws21-intent-package-schema`. Never merge; PR waits for Devon.

---

## File structure (created across tasks)
```
src/intent_packages/
  __init__.py          # docstring
  __main__.py          # sys.exit(main())
  cli.py               # argparse dispatch -> command funcs
  loader.py            # strict safe-YAML load (no datetime), single-doc, load package/lineage
  canonical.py         # intent_core(), jcs(), package_hash()
  lifecycle.py         # State constants, LEGAL_TRANSITIONS, DRIFT_LOCKED, REVISE_LEGAL_FROM, TERMINAL, helpers
  registry.py          # locate SECURITY_STANDARDS_DIR; load capabilities; agent-id / human-operator checks
  lineage.py           # Lineage load/save + append revision/transition/approval; hash snapshot
  validate.py          # structural + semantic checks (ID,S,H,A,TR,T,J,K,O,L); validate_package(dir)->errors
  emitter.py           # Emitter protocol, FactoryEventsEmitter, NullEmitter
  operations.py        # do_transition/do_approve/do_revise/do_supersede/verify_approval
tests/
  conftest.py          # fixtures: valid_package factory, fake_registry, stub emitter, tmp package dir
  test_*.py            # one per module + per CLI command
packages/
  ws-2.2-domain-profiles/{package.yaml,lineage.yaml}   # dogfood (Task 13)
.github/workflows/validate.yml
PROJECT.md, STANDARD_VERSION, CLAUDE.md, pyproject.toml
```

---

### Task 1: Python scaffold + smoke CLI

**Files:**
- Create: `pyproject.toml`, `src/intent_packages/__init__.py`, `src/intent_packages/__main__.py`, `src/intent_packages/cli.py`, `tests/conftest.py`, `tests/test_cli_smoke.py`

**Interfaces:**
- Produces: `cli.main(argv: list[str] | None = None) -> int`; `python -m intent_packages` runs it.

- [ ] **Step 1: `pyproject.toml`**
```toml
[project]
name = "intent-packages"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pyyaml>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pyyaml>=6.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "C90"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["B", "C90"]
```

- [ ] **Step 2: module files**

`src/intent_packages/__init__.py`:
```python
"""Universal intent packages (WS-2.1): schema, lifecycle, and validate/hash/approve CLI."""
```
`src/intent_packages/__main__.py`:
```python
import sys

from intent_packages.cli import main

sys.exit(main())
```
`src/intent_packages/cli.py` (grows in later tasks; smoke version):
```python
"""CLI: validate / hash / transition / approve / revise / supersede / verify-approval."""

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="intent_packages", description=__doc__)
    parser.add_subparsers(dest="cmd", required=True)
    parser.parse_args(argv)
    return 0
```

- [ ] **Step 3: smoke test** — `tests/test_cli_smoke.py`
```python
import pytest

from intent_packages.cli import main


def test_no_subcommand_errors():
    with pytest.raises(SystemExit):
        main([])
```

- [ ] **Step 4: run** `pytest tests/test_cli_smoke.py -v` → PASS. Also `PYTHONPATH=src python3 -m intent_packages --help` prints usage.
- [ ] **Step 5: commit** `feat(ws21): python scaffold + smoke CLI`

---

### Task 2: Strict YAML loader

**Files:** Create `src/intent_packages/loader.py`, `tests/test_loader.py`

**Interfaces:**
- Produces:
  - `class LoadError(Exception)`
  - `load_yaml_strict(text: str) -> dict` — `safe_load` with a resolver that never yields `datetime`/`date`; rejects multi-document streams; returns the top mapping (raises `LoadError` if not a mapping).
  - `load_package(pkg_dir: str | Path) -> dict` — reads `<dir>/package.yaml` via `load_yaml_strict`.
  - `load_lineage(pkg_dir: str | Path) -> dict` — reads `<dir>/lineage.yaml`.

- [ ] **Step 1: failing tests** — `tests/test_loader.py`
```python
import pytest

from intent_packages.loader import LoadError, load_yaml_strict


def test_rejects_multiple_documents():
    with pytest.raises(LoadError):
        load_yaml_strict("a: 1\n---\nb: 2\n")


def test_timestamp_stays_string_when_quoted():
    d = load_yaml_strict('created_at: "2026-07-03T00:00:00Z"\n')
    assert d["created_at"] == "2026-07-03T00:00:00Z"
    assert isinstance(d["created_at"], str)


def test_unquoted_timestamp_is_not_a_datetime():
    # A bare timestamp must NOT become a datetime object (breaks JSON round-trip).
    d = load_yaml_strict("created_at: 2026-07-03T00:00:00Z\n")
    assert isinstance(d["created_at"], str)


def test_top_level_must_be_mapping():
    with pytest.raises(LoadError):
        load_yaml_strict("- just\n- a\n- list\n")
```

- [ ] **Step 2: run** → FAIL (module missing).
- [ ] **Step 3: implement** `src/intent_packages/loader.py`
```python
from __future__ import annotations

from pathlib import Path

import yaml


class LoadError(Exception):
    pass


class _NoDatesLoader(yaml.SafeLoader):
    """SafeLoader that never auto-parses timestamps into datetime/date objects."""


# Drop YAML's implicit timestamp resolver so 2026-07-03T00:00:00Z loads as str.
_NoDatesLoader.yaml_implicit_resolvers = {
    ch: [(tag, regexp) for (tag, regexp) in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml_strict(text: str) -> dict:
    try:
        docs = list(yaml.load_all(text, Loader=_NoDatesLoader))
    except yaml.YAMLError as exc:  # noqa: BLE001
        raise LoadError(f"invalid YAML: {exc}") from exc
    if len(docs) != 1:
        raise LoadError(f"expected exactly one YAML document, found {len(docs)}")
    data = docs[0]
    if not isinstance(data, dict):
        raise LoadError("top-level YAML must be a mapping")
    return data


def load_package(pkg_dir: str | Path) -> dict:
    return load_yaml_strict((Path(pkg_dir) / "package.yaml").read_text(encoding="utf-8"))


def load_lineage(pkg_dir: str | Path) -> dict:
    return load_yaml_strict((Path(pkg_dir) / "lineage.yaml").read_text(encoding="utf-8"))
```

- [ ] **Step 4: run** `pytest tests/test_loader.py -v` → PASS. (Note: verify `test_unquoted_timestamp_is_not_a_datetime` — if PyYAML still returns a datetime, the resolver removal is wrong; the test is the gate.)
- [ ] **Step 5: commit** `feat(ws21): strict YAML loader (no datetime, single-doc)`

---

### Task 3: Canonicalization + hash + `hash` CLI

**Files:** Create `src/intent_packages/canonical.py`, `tests/test_canonical.py`; Modify `src/intent_packages/cli.py`

**Interfaces:**
- Produces:
  - `class CanonicalError(Exception)`
  - `intent_core(package: dict) -> dict` — returns a shallow copy without the `status` key.
  - `jcs(obj) -> str` — RFC 8785 canonical JSON string. Rejects floats and non-JSON scalars (raises `CanonicalError`).
  - `package_hash(package: dict) -> str` — `sha256_hex(jcs(intent_core(package)).encode("utf-8"))`.
- Consumes: nothing.

- [ ] **Step 1: failing tests** — `tests/test_canonical.py`
```python
import pytest

from intent_packages.canonical import CanonicalError, intent_core, jcs, package_hash


def test_jcs_sorts_keys_no_whitespace():
    assert jcs({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_jcs_rejects_float():
    with pytest.raises(CanonicalError):
        jcs({"x": 1.5})


def test_jcs_unicode_and_nesting():
    assert jcs({"z": [3, 2], "a": "é"}) == '{"a":"é","z":[3,2]}'


def test_status_excluded_from_hash():
    a = {"package_id": "p", "status": "draft", "revision": 1}
    b = {"package_id": "p", "status": "approved", "revision": 1}
    assert package_hash(a) == package_hash(b)


def test_hash_is_key_order_and_reformat_invariant():
    a = {"a": 1, "b": {"c": 2, "d": 3}}
    b = {"b": {"d": 3, "c": 2}, "a": 1}
    assert package_hash(a) == package_hash(b)


def test_hash_is_stable_sha256_hex():
    h = package_hash({"package_id": "p", "revision": 1})
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
```

- [ ] **Step 2: run** → FAIL.
- [ ] **Step 3: implement** `src/intent_packages/canonical.py`
```python
from __future__ import annotations

import hashlib


class CanonicalError(Exception):
    pass


def intent_core(package: dict) -> dict:
    core = dict(package)
    core.pop("status", None)
    return core


def _canon(obj) -> str:
    if obj is None or obj is True or obj is False:
        return {None: "null", True: "true", False: "false"}[obj]
    if isinstance(obj, float):
        raise CanonicalError("floats are not allowed in intent packages (quote the value)")
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, str):
        return _canon_str(obj)
    if isinstance(obj, list):
        return "[" + ",".join(_canon(v) for v in obj) + "]"
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0])
        return "{" + ",".join(f"{_canon_str(str(k))}:{_canon(v)}" for k, v in items) + "}"
    raise CanonicalError(f"unhashable type in package: {type(obj).__name__}")


def _canon_str(s: str) -> str:
    # RFC 8785 string escaping: JSON minimal escapes, UTF-8 preserved.
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def jcs(obj) -> str:
    return _canon(obj)


def package_hash(package: dict) -> str:
    return hashlib.sha256(jcs(intent_core(package)).encode("utf-8")).hexdigest()
```
> NOTE: this is a minimal JCS sufficient because strict typing (Task 2 + validate check J) guarantees only
> `str|int|bool|None|list|dict` reach it — no floats/large-int edge cases. Keep the float guard; it is the
> backstop that turns a stray float into a loud error instead of a silent hash divergence.

- [ ] **Step 4: add `hash` subcommand** to `cli.py` — after `parse_args`, dispatch:
```python
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_hash = sub.add_parser("hash", help="print sha256(JCS(intent_core)) of a package")
    p_hash.add_argument("path")
    args = parser.parse_args(argv)
    if args.cmd == "hash":
        from intent_packages.canonical import package_hash
        from intent_packages.loader import load_package
        print(package_hash(load_package(args.path)))
        return 0
    return 0
```

- [ ] **Step 5: CLI test** — `tests/test_cli_hash.py` writes a minimal `package.yaml` to a tmp dir, runs `main(["hash", str(dir)])`, asserts 64-hex on stdout (`capsys`). Run both test files → PASS.
- [ ] **Step 6: commit** `feat(ws21): canonical JCS hashing + hash CLI`

---

### Task 4: Lifecycle (states + transition map)

**Files:** Create `src/intent_packages/lifecycle.py`, `tests/test_lifecycle.py`

**Interfaces:**
- Produces:
  - `STATES: frozenset[str]` — all 15 states.
  - `LEGAL_TRANSITIONS: dict[str, frozenset[str]]` — exactly the §5.2 table.
  - `TERMINAL: frozenset[str]` = {closed, cancelled, failed, superseded}.
  - `DRIFT_LOCKED: frozenset[str]` = {ready_for_review, approved, executable, in_execution, verification, completed, follow_up_due, blocked, rejected}.
  - `REVISE_LEGAL_FROM: frozenset[str]` = {draft, needs_clarification, ready_for_review, rejected, approved}.
  - `is_legal_transition(src: str, dst: str) -> bool`.

- [ ] **Step 1: failing tests** — `tests/test_lifecycle.py`
```python
from intent_packages import lifecycle as lc


def test_legal_edges():
    assert lc.is_legal_transition("ready_for_review", "approved")
    assert lc.is_legal_transition("approved", "executable")
    assert lc.is_legal_transition("completed", "follow_up_due")
    assert lc.is_legal_transition("in_execution", "superseded")


def test_illegal_edges():
    assert not lc.is_legal_transition("in_execution", "draft")
    assert not lc.is_legal_transition("completed", "draft")
    assert not lc.is_legal_transition("draft", "approved")


def test_terminals_have_no_out_edges():
    for s in lc.TERMINAL:
        assert lc.LEGAL_TRANSITIONS.get(s, frozenset()) == frozenset()


def test_maps_reference_only_known_states():
    for src, dsts in lc.LEGAL_TRANSITIONS.items():
        assert src in lc.STATES
        assert dsts <= lc.STATES
```

- [ ] **Step 2: run** → FAIL.
- [ ] **Step 3: implement** `lifecycle.py` — encode the §5.2 table verbatim as `LEGAL_TRANSITIONS`, plus the sets above and `is_legal_transition = lambda in dict`. (Full table in spec §5.2. `is_legal_transition(src,dst)` returns `dst in LEGAL_TRANSITIONS.get(src, frozenset())`.)
- [ ] **Step 4: run** `pytest tests/test_lifecycle.py -v` → PASS.
- [ ] **Step 5: commit** `feat(ws21): lifecycle states + legal-transition map`

---

### Task 5: Registry adapter

**Files:** Create `src/intent_packages/registry.py`, `tests/test_registry.py`

**Interfaces:**
- Produces:
  - `registry_dir() -> Path | None` — `$SECURITY_STANDARDS_DIR/registry` else `~/Projects/security-standards/registry` if it exists, else `None`.
  - `capability_vocabulary() -> set[str] | None` — keys of `registry/capabilities.yaml` `terms`; `None` if registry absent.
  - `is_registered_agent(agent_id: str) -> bool` — `registry/agents/<id>.yaml` exists.
  - `is_human_operator(agent_id: str) -> bool` — that agent's `authority_profile == "human-operator-v1"`.

- [ ] **Step 1: failing tests** — `tests/test_registry.py` uses a `fake_registry` fixture (a tmp dir with `capabilities.yaml` holding `terms: {repository_read: ..., merge_to_main: ...}` and `agents/devon.yaml` with `authority_profile: human-operator-v1`), sets `SECURITY_STANDARDS_DIR` via monkeypatch:
```python
def test_vocab_loaded(fake_registry, monkeypatch):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    from intent_packages import registry
    assert "merge_to_main" in registry.capability_vocabulary()


def test_human_operator(fake_registry, monkeypatch):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    from intent_packages import registry
    assert registry.is_human_operator("devon")
    assert not registry.is_human_operator("claude-code-interactive")  # profile != human-operator-v1


def test_absent_registry_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path / "nope"))
    from intent_packages import registry
    assert registry.capability_vocabulary() is None
```
Add the `fake_registry` fixture to `conftest.py` (writes `capabilities.yaml` + `agents/devon.yaml` + `agents/claude-code-interactive.yaml` with `authority_profile: interactive-dev-v1`).

- [ ] **Step 2: run** → FAIL.
- [ ] **Step 3: implement** `registry.py` — resolve dir, load YAML via `loader.load_yaml_strict`, return vocab/booleans; all functions tolerate a missing dir (return `None`/`False`).
- [ ] **Step 4: run** `pytest tests/test_registry.py -v` → PASS.
- [ ] **Step 5: commit** `feat(ws21): registry adapter (capability vocab + human-operator check)`

---

### Task 6: Lineage read/write

**Files:** Create `src/intent_packages/lineage.py`, `tests/test_lineage.py`

**Interfaces:**
- Produces:
  - `read(pkg_dir) -> dict` (loads `lineage.yaml`), `write(pkg_dir, lineage: dict) -> None` (dumps deterministically: `yaml.safe_dump(sort_keys=False)`).
  - `current_revision_hash(lineage: dict) -> str` — hash of the highest `revisions[].revision`.
  - `append_transition(lineage, kind, src, dst, at, actor, event_id) -> None`.
  - `snapshot_revision(lineage, revision, hash_hex, at, author) -> None` — append/replace the revisions entry.
  - `append_approval(lineage, revision, approved_hash, approver, at, commit, event_id) -> None`.
- Consumes: none (pure dict manipulation + file IO).

- [ ] **Step 1–5:** TDD. Tests: round-trip write→read; `current_revision_hash` returns the top revision's hash; `append_*` grow the right lists; `write` output re-parses under `load_yaml_strict` (keeps timestamps quoted — dump strings, never datetimes). Commit `feat(ws21): lineage read/write + append helpers`.

---

### Task 7: Validation — structure, typing, identity, acceptance, trust

**Files:** Create `src/intent_packages/validate.py`, `tests/test_validate_structure.py`; Modify `cli.py` (add `validate`)

**Interfaces:**
- Produces: `validate_package(pkg_dir: str | Path) -> list[str]` — returns a list of human-readable error strings (empty = valid). Internally runs ordered checks; this task implements: **K** (no unknown keys except `profile`/`profile_fields`, at every level via a closed-schema spec), **J** (strict typing: reject float/datetime/bytes anywhere; enforce required keys present), **ID** (`package_id` == dir name), **TR** (every source has `trust ∈ {trusted_instruction, untrusted_data}`), **A** (acceptance items: unique `^AC-[0-9]{3,}$` id, enum `evidence_type`, non-empty `evidence`, approver form per §3.6). Task 8 appends the cross-file checks.
- Consumes: `loader`, `registry` (for approver = registry id), `canonical` (float guard reuse).

- [ ] **Step 1: define the closed schema** — a module-level spec of the universal envelope (required keys per section + allowed value types + enums). Keep it a plain nested Python structure the checks walk; do NOT pull in jsonschema (not an estate dep). Fixtures: `tests/fixtures/valid/` (a full valid package) + broken variants.
- [ ] **Step 2: failing tests** — `tests/test_validate_structure.py`
```python
from intent_packages.validate import validate_package


def test_valid_package_has_no_errors(valid_package):        # conftest factory -> pkg_dir
    assert validate_package(valid_package) == []


def test_float_is_rejected(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_raw="quality_accessibility: 1.5")
    errs = validate_package(valid_package)
    assert any("float" in e.lower() for e in errs)


def test_acceptance_missing_approver(valid_package, drop_key):
    drop_key(valid_package, "package.yaml", "acceptance", 0, "approver")
    assert any("approver" in e for e in validate_package(valid_package))


def test_external_approver_only_for_attestation(valid_package, edit_yaml):
    # external:<label> with evidence_type=automated_test must fail.
    ...
    assert any("external" in e for e in validate_package(valid_package))


def test_unknown_top_level_key(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_raw="bogus_key: 1")
    assert any("unknown" in e.lower() for e in validate_package(valid_package))


def test_package_id_must_match_dir(valid_package, edit_yaml):
    edit_yaml(valid_package, "package.yaml", set_key=("package_id", "wrong"))
    assert any("package_id" in e for e in validate_package(valid_package))
```
Add `valid_package`, `edit_yaml`, `drop_key` fixtures/helpers to `conftest.py`. The `valid_package` factory writes a complete valid `package.yaml` (all §3 sections, `status: draft`) + a matching `lineage.yaml` (revision 1 with the correct hash, `current_state: draft`) into a `packages/<id>/` tmp dir.
- [ ] **Step 3: implement** the checks K/J/ID/TR/A. Each error message names the file and the field path.
- [ ] **Step 4: add `validate` CLI** — `validate <path>` and `validate --all` (walk `packages/*/`); print each error; exit `1` if any.
- [ ] **Step 5: run** → PASS. **Step 6: commit** `feat(ws21): validate — structure, typing, identity, acceptance, trust`

---

### Task 8: Validation — status/hash-drift, authority, open-questions, lineage consistency

**Files:** Modify `src/intent_packages/validate.py`; Create `tests/test_validate_semantic.py`

**Interfaces:**
- Consumes: `canonical.package_hash`, `lifecycle` (DRIFT_LOCKED, LEGAL_TRANSITIONS), `registry` (vocab), `lineage`.
- Produces: appends checks **S** (`status` == `lineage.current_state`), **H** (drift rule over `DRIFT_LOCKED`; message differs pre-execution vs execution per §4.2), **T** (authority terms in-vocab / no term in >1 list / unknown-term message; degrade to warning if `capability_vocabulary()` is `None`), **O** (`scope.open_questions == []` → warning here; error is enforced by `approve`), **L** (lineage consistency: monotonic revisions; each transition a legal edge OR `kind ∈ {revision, supersession}`; approvals/grants reference existing revisions; `current_state` reachable).

- [ ] **Steps:** TDD each check with a passing + failing fixture. Key cases: drift in `approved` → error mentioning "supersede"; drift in `ready_for_review` → error mentioning "revise"; a `merge_to_main` term duplicated across `allowed` and `prohibited` → error; an out-of-vocab term → error naming a registry PR; a lineage transition `in_execution→draft` with `kind: transition` → error, but `kind: revision` → allowed. Commit `feat(ws21): validate — drift, authority, lineage consistency`.

---

### Task 9: Factory-events emitter

**Files:** Create `src/intent_packages/emitter.py`, `tests/test_emitter.py`

**Interfaces:**
- Produces:
  - `class Emitter(Protocol): def emit(self, action: str, ref: str, evidence: dict) -> str | None: ...` (returns event_id or None).
  - `class NullEmitter: def emit(...) -> None: return None`.
  - `class FactoryEventsEmitter:` — builds and runs the `factory_events emit` subprocess (actor from `FACTORY_AGENT_ID`, `--evidence-json`), parses the emitted `event_id` from stdout/JSON; raises `EmitError` on non-zero exit. Locates security-standards via `registry.registry_dir().parent` or `$SECURITY_STANDARDS_DIR`.
  - `class EmitError(Exception)`.

- [ ] **Steps:** TDD. Test `NullEmitter.emit(...) is None`. Test `FactoryEventsEmitter` by monkeypatching `subprocess.run` to a fake returning a known stdout, asserting the argv contains `-m`, `factory_events`, `emit`, `--actor`, the action, `--ref`, and that `emit()` returns the parsed id; and that a non-zero return raises `EmitError`. **Do not** hit the real events store in tests. Commit `feat(ws21): injectable factory-events emitter`.

---

### Task 10: `transition` operation + CLI

**Files:** Create `src/intent_packages/operations.py`, `tests/test_op_transition.py`; Modify `cli.py`

**Interfaces:**
- Produces: `do_transition(pkg_dir, to_state, *, emitter, actor, now) -> None` — validates the package first (must be error-free), checks `is_legal_transition(current, to_state)` (hard error if not), **snapshots the revision hash when `to_state == "ready_for_review"`**, appends a `kind: transition` lineage entry (best-effort emit → `event_id` or `null`+`emit_error`), updates `package.yaml.status` and `lineage.current_state`, writes both files. `now`/`actor` injectable for tests.
- Consumes: `validate`, `lifecycle`, `lineage`, `canonical`, `emitter`.

- [ ] **Steps:** TDD. Tests (with `NullEmitter`, injected `now`): legal draft→ready_for_review flips status in BOTH files and snapshots the hash into `lineage.revisions`; illegal draft→approved raises; a package that fails `validate` refuses to transition. CLI `transition <path> --to <state>`. Commit `feat(ws21): transition operation + CLI`.

---

### Task 11: `approve`, `revise`, `supersede` operations + CLI

**Files:** Modify `operations.py`, `cli.py`; Create `tests/test_op_approve.py`, `tests/test_op_revise_supersede.py`

**Interfaces:**
- Produces:
  - `do_approve(pkg_dir, *, emitter, approver="devon", commit, now) -> None` — requires `current_state == ready_for_review`; requires `scope.open_questions == []` (hard error otherwise); requires `is_human_operator(approver)` (hard error); computes hash; **emits `package.approved` FIRST (fatal on failure)**; then appends `lineage.approvals[]` with the returned `event_id`; sets status `approved`. **Idempotent:** if an approval for the current hash already exists in the chain (query via emitter/lineage), complete only the missing lineage write without re-emitting.
  - `do_revise(pkg_dir, *, emitter, actor, now) -> None` — legal only from `REVISE_LEGAL_FROM`; increments `revision`; snapshots new hash; sets status `draft`; appends `kind: revision` lineage entry; emits `package.revised` (best-effort). Refuses from execution states with a message pointing to `supersede`.
  - `do_supersede(pkg_dir, new_package_id, *, emitter, actor, now) -> None` — sets status `superseded`; appends `kind: supersession` entry referencing `new_package_id`; emits `package.superseded`.
- Consumes: Task 10 infra + `registry.is_human_operator`.

- [ ] **Steps:** TDD with a **stub emitter** returning a fixed `event_id`. Tests: approve from ready_for_review records an approval whose `approved_hash == package_hash`; approve with non-empty `open_questions` raises; approve with a non-human approver raises; approve where the stub emitter raises `EmitError` writes **no** approval (fatal); revise from `approved` → revision 2, status draft, prior approval remains in history; revise from `in_execution` raises pointing to supersede; supersede sets superseded + back-ref. CLI: `approve [--approver ID]`, `revise`, `supersede --by ID`. Commit `feat(ws21): approve/revise/supersede operations + CLI`.

---

### Task 12: `verify-approval` operation + CLI

**Files:** Modify `operations.py`, `cli.py`; Create `tests/test_op_verify_approval.py`

**Interfaces:**
- Produces: `verify_approval(pkg_dir, *, chain_checker, ledger_only=False) -> bool` — (1) recompute current hash; (2) require a `lineage.approvals[]` entry with matching `approved_hash` and a human-operator approver; (3) unless `ledger_only`, require `chain_checker(approved_hash, revision)` True AND the chain verifies. Returns True only if all required checks pass; **fails closed** if the chain can't be consulted (non-`ledger_only`).
- `chain_checker` is injectable (default queries `factory_events` for a `package.approved` event with the hash and runs `factory_events verify`); tests pass a stub. A **forged-ledger** test: ledger has a matching entry but `chain_checker` returns False → `verify_approval(..., ledger_only=False)` is False, while `ledger_only=True` is True but prints the "UNVERIFIED CHAIN" warning.

- [ ] **Steps:** TDD as above. CLI `verify-approval <path> [--ledger-only]` (exit 0 True / 1 False). Commit `feat(ws21): verify-approval dual ledger+chain check`.

---

### Task 13: Repo/foundation bootstrap + CI

**Files:** Create `PROJECT.md`, `STANDARD_VERSION`, `CLAUDE.md`, `.github/workflows/validate.yml`

- [ ] **Step 1: `STANDARD_VERSION`** = `1.0\n`.
- [ ] **Step 2: `PROJECT.md`** — frontmatter per spec §10 (`foundation: true`, `foundation_contract: 1`, `applicable_standards: {project: '1.0', security: '1.0', code: '1.0'}`, `required_checks: [{id: intent-package-validate, executor: github-actions:validate.yml}]`) + `## Backlog` section (empty) + `## Future plans`.
- [ ] **Step 3: `.github/workflows/validate.yml`** — on push/PR: checkout, setup-python 3.12, `pip install -e ".[dev]"`, step "validate all packages": `PYTHONPATH=src python3 -m intent_packages validate --all`, step "tests (assert non-zero collected)": `PYTHONPATH=src python3 -m pytest -q | tee /tmp/out; grep -Eq '[1-9][0-9]* (passed|selected)' /tmp/out`, step `ruff check .` (non-fatal `|| true` if ruff absent). Registry-dependent checks degrade to warnings in CI (no security-standards checkout) — that's expected and must not fail the run.
- [ ] **Step 4: `CLAUDE.md`** — short: what the repo is, the zero-install invocation, "packages are YAML in git; status is excluded from the hash; approval binds to a revision; never merge — PR waits for Devon", pointer to the spec.
- [ ] **Step 5:** run `PYTHONPATH=src python3 -m intent_packages validate --all` locally (0 packages yet → exit 0). Commit `chore(ws21): PROJECT.md, foundation_contract, validate.yml CI`.

---

### Task 14: Dogfood package — WS-2.2 as the first intent package

**Files:** Create `packages/ws-2.2-domain-profiles/package.yaml`, `packages/ws-2.2-domain-profiles/lineage.yaml`

- [ ] **Step 1:** author a **real, complete** intent package describing the WS-2.2 workstream (domain
  profiles for software-delivery + infrastructure-change; extends the universal envelope via
  `profile_fields`; acceptance criteria for "profiles validate", "universal envelope unchanged", etc.;
  authority envelope in registry terms; sources classify the master plan as `trusted_instruction`).
  `status: draft`; `lineage.yaml` with revision 1 (hash filled from `hash` output), `current_state: draft`.
- [ ] **Step 2:** `PYTHONPATH=src python3 -m intent_packages validate packages/ws-2.2-domain-profiles` → no errors.
- [ ] **Step 3:** `hash` it; paste the digest into `lineage.revisions[0].hash`; re-validate (drift check passes).
- [ ] **Step 4:** commit `feat(ws21): dogfood — WS-2.2 authored as the first intent package`.

(End-to-end drive — transition→approve→verify-approval with real event emission — happens in the
orchestrator's **verify** step, not this task, because `approve` requires the live events store + Devon.)

---

## Self-review notes
- **Spec coverage:** §3 envelope → Tasks 7/8/14; §4 hash/revision → Tasks 2/3 + drift in 8 + revise/supersede in 11; §5 lifecycle → Task 4 + enforcement in 8/10/11; §6 checks → Tasks 7/8; §7 CLI → 3/7/10/11/12; §8 emit → 9 + wired in 10/11; §9 lineage → 6; §10 repo → 13; §12 dogfood → 14; §5.4 readiness rules are *data + documented rules* (pinned predecessors validated in 8; the acting orchestrator is Phase-3, out of scope). Reserved `grants[]` written by lineage schema (6/14), never populated (correct for MVP).
- **Non-obvious risks flagged for doers:** (1) the PyYAML timestamp-resolver removal (Task 2) must be verified by its test — if PyYAML still returns datetime, use a post-load type check that raises instead. (2) JCS float guard (Task 3) is the backstop for hash determinism — never remove it. (3) `approve` emit-first ordering + idempotency (Task 11) is the crash-safety contract — implement the idempotent re-run.
