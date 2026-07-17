# factory decompose + dependency-update delivery profile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `factory decompose` command in `intent-packages` that turns *(intaken revision + mapped AC + target repo + chosen dependency + tooling)* into a validated, optionally-submitted dependency-update decomposition proposal, making the four WS-6.4 defect classes structurally impossible.

**Architecture:** A new `factory` console script (argparse, lazy imports) that shells the existing `orchestrator` CLI for all API/scanner touches (`show-package-intake`, `conformance-claim`, `propose-decomposition`), assembles the byte-pinned authority envelope from a per-tooling profile registry (uv/pip/npm), and runs three owned fail-closed validations (dry-run diff+idempotency, pin-site coverage, verifier deny-list) before emitting/submitting.

**Tech Stack:** Python 3.12+, argparse, `subprocess`, `tomllib` (stdlib), `json`, `git` (subprocess), pytest. No new third-party deps (repo stays pyyaml-only at runtime).

## Global Constraints

- Python **3.12+**; runtime deps limited to `pyyaml` (do not add libraries — shell out instead, mirroring `emitter.py`).
- The tool **never** accepts a hand-typed `conformance`; it comes only from `orchestrator conformance-claim`.
- The emitted envelope **omits `constraints.work_unit_id`** (orchestrator stamps `uuid5(proposal_id, unit_key)`; author-supplied is rejected).
- `ac_mappings[].ac_id` and `retained_acs[].ac_id` carry the criterion **DB UUID** (from the intake GET `id` field), never the human string `"AC-001"`.
- Every criterion must be disposed **exactly once** (mapped xor retained); union == all criteria.
- `allowed_commands = mutation_commands + [verifier]` — mutators first, deterministic assertion last (uniform across tooling).
- Proposal body `expected_version` is always `0`.
- Submission uses the **system** M2M credential; it is the only orchestrator write. No auto-approve, no auto-merge.
- Follow the repo's CLI idiom: `main(argv: list[str] | None = None) -> int`, argparse subparsers, lazy per-subcommand imports, errors to `stderr` + non-zero rc (see `src/intent_packages/cli.py`).
- Gate: `make check` (`.venv/bin/ruff check .` + `ruff format --check .` + `pyright` + `pytest`) must be green before "done"; ruff line-length 100, mccabe max-complexity 10.

---

## File Structure

- `src/intent_packages/factory_cli.py` — **new.** `factory` front door: argparse, `main(argv)->int`, `decompose` subcommand. Thin: parse → call `decompose.run(...)` → print → rc.
- `src/intent_packages/factory/__init__.py` — **new.** Empty package marker.
- `src/intent_packages/factory/orchestrator_cli.py` — **new.** Injectable subprocess wrappers around the `orchestrator` CLI (`show_package_intake`, `conformance_claim`, `propose_decomposition`). Parse `--json` stdout, raise `OrchestratorCliError` on `{"error":...}` or non-zero exit.
- `src/intent_packages/factory/validations.py` — **new.** `dry_run_mutation()` (clone at HEAD, run list twice, diff), `assert_pin_sites_moved()`, `assert_runner_honest()` (deny-list). `ValidationError`.
- `src/intent_packages/factory/decompose.py` — **new.** The flow: fetch criteria → build ac_mappings/retained_acs → conformance → envelope → validate → assemble proposal → emit/submit. `DecomposeError`.
- `src/intent_packages/profiles/dependency_update.py` — **new.** Per-tooling registry: `PinSite`, `ToolingProfile`, `PROFILES` (`pip`/`uv`/`npm`), `build_envelope(...)`, `DENIED_VERIFIER_PATTERNS`.
- `pyproject.toml` — **modify.** Add `[project.scripts] factory = "intent_packages.factory_cli:main"`.
- Tests: `tests/factory/test_profiles_dependency_update.py`, `tests/factory/test_orchestrator_cli.py`, `tests/factory/test_validations.py`, `tests/factory/test_decompose.py`, `tests/factory/test_factory_cli.py`.
- `docs/superpowers/evidence/2026-07-17-npm-envelope-preflight.md` — **new** (Task 0 output).

---

## Task 0: npm envelope preflight (investigation, gates Task 4)

**Not a TDD task** — a hand-proof against `AlobarQuest/infraops-mcp-server` (local checkout `~/Projects/infraops-mcp-server`), recorded as evidence exactly like `docs/superpowers/evidence/2026-07-17-ws64-revision6-brain-preflight.md`.

**Files:**
- Create: `docs/superpowers/evidence/2026-07-17-npm-envelope-preflight.md`

- [ ] **Step 1: Pick a real available upgrade.** In a scratch copy of `~/Projects/infraops-mcp-server`, read `package.json`. For a pinned dependency, check `npm view <pkg> version` (latest) vs the pinned value. Record a package with a real upgrade (non-empty diff guaranteed). Note whether it lives in `dependencies` or `devDependencies`, and confirm whether it also appears in `package-lock.json` (it will).

- [ ] **Step 2: Prove the mutator on a COPY.** `cp -r` the repo to a temp dir. Run the candidate mutator (start with `npm install <pkg>@<new> --save-exact` for a runtime dep, `--save-dev --save-exact` for a dev dep). Confirm: (a) `git diff --name-only` includes **both** `package.json` and `package-lock.json`; (b) running the mutator a **second time** leaves the diff unchanged (idempotent). If `npm install` requires network the bare runner may lack, record that risk.

- [ ] **Step 3: Confirm the runner can run node/npm.** Check whether factory-runner's reusable workflow provides node/npm on the hosted runner (grep `~/Projects/factory-runner` workflows for `setup-node`/`actions/setup-node`). If node/npm is NOT guaranteed on the runner, **npm degrades to a documented extension point** — record that decision and STOP npm here (Task 4 becomes "register npm as unsupported-pending-runner-node").

- [ ] **Step 4: Fix the deterministic verifier.** The assertion the pin moved, no services: `grep -q '"<pkg>": "<new>"' package.json`. Confirm it matches after mutation and fails before.

- [ ] **Step 5: Record the evidence doc** with: chosen pkg/old/new, the exact mutator command string(s), the exact verifier string, the pin sites (`package.json` section + `package-lock.json`), idempotency confirmation, and the runner-node decision. These exact strings feed Task 4.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/evidence/2026-07-17-npm-envelope-preflight.md
git commit -m "docs: npm dependency-update envelope preflight (infraops-mcp-server)"
```

---

## Task 1: `factory` CLI skeleton + console script

**Files:**
- Create: `src/intent_packages/factory_cli.py`
- Create: `src/intent_packages/factory/__init__.py`
- Modify: `pyproject.toml` (add `[project.scripts]`)
- Test: `tests/factory/__init__.py` (empty), `tests/factory/test_factory_cli.py`

**Interfaces:**
- Produces: `intent_packages.factory_cli.main(argv: list[str] | None = None) -> int`. The `decompose` subparser collects: `--revision` (str, required), `--ac` (str, required), `--target-repo` (str, required), `--repo-path` (str, default `""` → resolved later), `--tooling` (choices `pip|uv|npm`, required), `--package` (str, required), `--from` (dest `from_version`, required), `--to` (dest `to_version`, required), `--unit-key` (str, default `""`), `--rationale` (str, default `""`), `--out` (str, default `""` → stdout), `--submit` (store_true). It calls `intent_packages.factory.decompose.run(**opts) -> int` (added in Task 7); for this task, stub `run` is not yet imported — the subcommand handler returns 0 after printing the parsed namespace so the wiring is testable.

- [ ] **Step 1: Write the failing test**

```python
# tests/factory/test_factory_cli.py
import pytest

from intent_packages.factory_cli import main


def test_no_subcommand_errors():
    with pytest.raises(SystemExit):
        main([])


def test_decompose_requires_revision():
    with pytest.raises(SystemExit):
        main(["decompose", "--ac", "AC-001"])


def test_decompose_parses_all_args(capsys):
    rc = main([
        "decompose", "--revision", "rev-1", "--ac", "AC-002",
        "--target-repo", "AlobarQuest/brain", "--tooling", "pip",
        "--package", "fastapi", "--from", "0.139.0", "--to", "0.139.2",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "rev-1" in out and "AC-002" in out and "pip" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/factory/test_factory_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'intent_packages.factory_cli'`

- [ ] **Step 3: Create the package marker and CLI skeleton**

```python
# src/intent_packages/factory/__init__.py
"""Factory front-door helpers (WS-P2.9): decompose and future journey verbs."""
```

```python
# src/intent_packages/factory_cli.py
"""`factory` CLI front door (WS-P2.9). First subcommand: decompose.

Mirrors intent_packages.cli: main(argv) -> int, argparse subparsers, lazy
per-subcommand imports. Future journey verbs (create/validate/submit/status/
evidence/retry/cancel) join as sibling subparsers.
"""

import argparse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("decompose", help="author + validate a dependency-update decomposition proposal")
    p.add_argument("--revision", required=True, help="intaken package revision id")
    p.add_argument("--ac", required=True, help="acceptance criterion human id, e.g. AC-002")
    p.add_argument("--target-repo", required=True, help="GitHub slug, e.g. AlobarQuest/brain")
    p.add_argument("--repo-path", default="", help="local checkout path (default: ~/Projects/<repo>)")
    p.add_argument("--tooling", required=True, choices=("pip", "uv", "npm"))
    p.add_argument("--package", required=True, help="dependency name")
    p.add_argument("--from", dest="from_version", required=True, help="current pinned version")
    p.add_argument("--to", dest="to_version", required=True, help="target version")
    p.add_argument("--unit-key", default="", help="proposed unit key (default: derived from --ac)")
    p.add_argument("--rationale", default="", help="retained-AC rationale (default: auto)")
    p.add_argument("--out", default="", help="write proposal JSON here (default: stdout)")
    p.add_argument("--submit", action="store_true", help="submit via orchestrator (default: dry only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "decompose":
        # Wired to factory.decompose.run in Task 7. For now echo the parsed request.
        print(
            f"decompose revision={args.revision} ac={args.ac} "
            f"target={args.target_repo} tooling={args.tooling} "
            f"package={args.package} {args.from_version}->{args.to_version}"
        )
        return 0
    return 0
```

- [ ] **Step 4: Add the console script entry to pyproject.toml**

Add immediately after the `[project.optional-dependencies]` block:

```toml
[project.scripts]
factory = "intent_packages.factory_cli:main"
```

Create `tests/factory/__init__.py` (empty file).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_factory_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/intent_packages/factory_cli.py src/intent_packages/factory/__init__.py \
        pyproject.toml tests/factory/__init__.py tests/factory/test_factory_cli.py
git commit -m "feat: factory CLI skeleton with decompose subcommand"
```

---

## Task 2: profile registry — data types + pip variant

**Files:**
- Create: `src/intent_packages/profiles/dependency_update.py`
- Test: `tests/factory/test_profiles_dependency_update.py`

**Interfaces:**
- Produces:
  - `PinSite` (frozen dataclass): `.file: str`, `.label: str`, `.current_version: str | None`.
  - `ToolingProfile` (frozen dataclass): `.name: str`, `.discover_pin_sites: Callable[[Path, str], list[PinSite]]`, `.mutation_commands: Callable[[str, str, str, list[PinSite]], list[str]]`, `.verifier_command: Callable[[str, str, str, list[PinSite]], str]`.
  - `PROFILES: dict[str, ToolingProfile]` (this task registers `"pip"`).
  - `CAPABILITIES: dict[str,str]`, `BUDGETS: dict[str,int]`, `DENIED_VERIFIER_PATTERNS: tuple[str,...]`.
  - `build_envelope(target_repo, tooling, package, old, new, conformance, sites) -> dict` (Task 5 consumer; defined here).
  - `ProfileError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/factory/test_profiles_dependency_update.py
from pathlib import Path

from intent_packages.profiles import dependency_update as dep


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_pip_discovers_single_site(tmp_path):
    _write(tmp_path, "requirements.txt", "fastapi==0.139.0\nuvicorn==0.51.0\n")
    sites = dep.PROFILES["pip"].discover_pin_sites(tmp_path, "fastapi")
    assert [(s.file, s.current_version) for s in sites] == [("requirements.txt", "0.139.0")]


def test_pip_discovers_dual_site(tmp_path):
    _write(tmp_path, "requirements.txt", "httpx==0.28.1\n")
    _write(tmp_path, "requirements-dev.txt", "httpx==0.28.1\n")
    sites = dep.PROFILES["pip"].discover_pin_sites(tmp_path, "httpx")
    assert {s.file for s in sites} == {"requirements.txt", "requirements-dev.txt"}


def test_pip_mutation_commands_one_sed_per_site(tmp_path):
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    cmds = dep.PROFILES["pip"].mutation_commands("fastapi", "0.139.0", "0.139.2", sites)
    assert cmds == ["sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt"]


def test_pip_verifier_is_grep(tmp_path):
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    v = dep.PROFILES["pip"].verifier_command("fastapi", "0.139.0", "0.139.2", sites)
    assert v == "grep -qx 'fastapi==0.139.2' requirements.txt"


def test_build_envelope_shape_matches_contract():
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    env = dep.build_envelope(
        "AlobarQuest/brain", "pip", "fastapi", "0.139.0", "0.139.2",
        {"accepted_standards": [], "standards_touched": ["project"], "status": "green"},
        sites,
    )
    assert "work_unit_id" not in env["constraints"]
    assert env["change_class"] == "dependency-update"
    assert env["constraints"]["allowed_commands"] == [
        "sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt",
        "grep -qx 'fastapi==0.139.2' requirements.txt",
    ]
    assert env["constraints"]["mutation_commands"] == [
        "sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt",
    ]
    assert env["capabilities"]["command.run"] == "allowed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/factory/test_profiles_dependency_update.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'intent_packages.profiles.dependency_update'`

- [ ] **Step 3: Write the implementation**

```python
# src/intent_packages/profiles/dependency_update.py
"""Dependency-update delivery profile (WS-P2.10): per-tooling pin discovery,
mutators, deterministic verifiers, and the byte-pinned authority envelope.

The envelope shape is fixed by orchestrator's
tests/fixtures/runner_authority_envelope.json (a cross-repo contract). We emit it
minus constraints.work_unit_id, which the orchestrator stamps.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CAPABILITIES: dict[str, str] = {
    "command.run": "allowed",
    "github.pr.create": "allowed",
    "orchestrator.claim": "allowed",
    "orchestrator.evidence.write": "allowed",
    "repo.edit": "allowed",
    "repo.read": "allowed",
}
BUDGETS: dict[str, int] = {"max_attempts": 3, "max_llm_calls": 4}

# Runner-honesty deny-list (validation #2): tool-guarded checks the bare hosted
# runner cannot honestly run (need services / a migrated DB / can exit 0 having
# verified nothing). uv lock --check and grep are deterministic and allowed.
DENIED_VERIFIER_PATTERNS: tuple[str, ...] = (
    r"\bmake\s+check\b",
    r"\bmake\s+test\b",
    r"\bpytest\b",
    r"\bnpm\s+test\b",
    r"\bnpm\s+run\s+test\b",
    r"\btox\b",
    r"\bnox\b",
)


class ProfileError(Exception):
    """Raised when a tooling profile cannot build a valid envelope."""


@dataclass(frozen=True)
class PinSite:
    file: str
    label: str
    current_version: str | None


@dataclass(frozen=True)
class ToolingProfile:
    name: str
    discover_pin_sites: Callable[[Path, str], list[PinSite]]
    mutation_commands: Callable[[str, str, str, list[PinSite]], list[str]]
    verifier_command: Callable[[str, str, str, list[PinSite]], str]


# ----- pip / requirements.txt -----

_PIP_FILES = ("requirements.txt", "requirements-dev.txt")


def _pip_discover(repo: Path, package: str) -> list[PinSite]:
    pattern = re.compile(rf"^{re.escape(package)}==(.+)$")
    sites: list[PinSite] = []
    for name in _PIP_FILES:
        path = repo / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line.strip())
            if match:
                sites.append(PinSite(name, name, match.group(1)))
                break
    return sites


def _pip_mutation(package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    return [
        f"sed -i 's/^{package}=={old}$/{package}=={new}/' {site.file}" for site in sites
    ]


def _pip_verifier(package: str, old: str, new: str, sites: list[PinSite]) -> str:
    primary = next((s.file for s in sites if s.file == "requirements.txt"), None)
    primary = primary or (sites[0].file if sites else "requirements.txt")
    return f"grep -qx '{package}=={new}' {primary}"


PROFILES: dict[str, ToolingProfile] = {
    "pip": ToolingProfile("pip", _pip_discover, _pip_mutation, _pip_verifier),
}


def build_envelope(
    target_repo: str,
    tooling: str,
    package: str,
    old: str,
    new: str,
    conformance: dict,
    sites: list[PinSite],
) -> dict:
    if tooling not in PROFILES:
        raise ProfileError(f"unknown tooling: {tooling}")
    profile = PROFILES[tooling]
    mutations = profile.mutation_commands(package, old, new, sites)
    if not mutations:
        raise ProfileError(f"{tooling}: no mutation commands (no pin sites for {package}?)")
    verifier = profile.verifier_command(package, old, new, sites)
    return {
        "budgets": dict(BUDGETS),
        "capabilities": dict(CAPABILITIES),
        "change_class": "dependency-update",
        "conformance": conformance,
        "constraints": {
            "allowed_commands": [*mutations, verifier],
            "mutation_commands": list(mutations),
            "target_repository": target_repo,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_profiles_dependency_update.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/intent_packages/profiles/dependency_update.py tests/factory/test_profiles_dependency_update.py
git commit -m "feat: dependency-update profile registry + pip variant"
```

---

## Task 3: profile registry — uv variant

**Files:**
- Modify: `src/intent_packages/profiles/dependency_update.py`
- Test: `tests/factory/test_profiles_dependency_update.py` (add uv tests)

**Interfaces:**
- Consumes: `PinSite`, `ToolingProfile`, `PROFILES` from Task 2.
- Produces: `PROFILES["uv"]`. uv `discover_pin_sites` parses `pyproject.toml` with `tomllib` across `[project.dependencies]`, `[dependency-groups.*]`, `[project.optional-dependencies.*]`; each `PinSite.file == "pyproject.toml"`, `.label` == the section (e.g. `"dependency-groups.dev"`), `.current_version` == the version after `==`/`>=`. **Pinned sites only** — an occurrence of the package with no `==`/`>=` version is not a pin site (nothing to move OLD→NEW) and is not returned. Mutation: single `uv add [--dev] 'PKG>=NEW'` (`--dev` when every site label starts with `dependency-groups` or `optional-dependencies`). Verifier: `uv lock --check`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/factory/test_profiles_dependency_update.py
def test_uv_discovers_project_and_group(tmp_path):
    _write(tmp_path, "pyproject.toml", (
        '[project]\n'
        'dependencies = ["fastapi==0.139.0"]\n'
        '[dependency-groups]\n'
        'dev = ["ruff==0.15.20", "fastapi==0.139.0"]\n'
    ))
    sites = dep.PROFILES["uv"].discover_pin_sites(tmp_path, "fastapi")
    labels = sorted(s.label for s in sites)
    assert labels == ["dependency-groups.dev", "project.dependencies"]
    assert all(s.file == "pyproject.toml" and s.current_version == "0.139.0" for s in sites)


def test_uv_mutation_runtime_dep_no_dev_flag(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "project.dependencies", "0.139.0")]
    cmds = dep.PROFILES["uv"].mutation_commands("fastapi", "0.139.0", "0.139.2", sites)
    assert cmds == ["uv add 'fastapi>=0.139.2'"]


def test_uv_mutation_dev_only_adds_dev_flag(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "dependency-groups.dev", "0.15.20")]
    cmds = dep.PROFILES["uv"].mutation_commands("ruff", "0.15.20", "0.15.21", sites)
    assert cmds == ["uv add --dev 'ruff>=0.15.21'"]


def test_uv_verifier_is_lock_check(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "project.dependencies", "0.139.0")]
    assert dep.PROFILES["uv"].verifier_command("fastapi", "0", "1", sites) == "uv lock --check"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/factory/test_profiles_dependency_update.py -k uv -v`
Expected: FAIL with `KeyError: 'uv'`

- [ ] **Step 3: Write the implementation** — add above the `PROFILES` assignment and extend the dict.

```python
# add to src/intent_packages/profiles/dependency_update.py
import tomllib


def _uv_pin_version(spec: str, package: str) -> str | None:
    # spec is a PEP 508 requirement string, e.g. "fastapi==0.139.0" or "fastapi>=1,<2"
    name = re.split(r"[<>=!~ \[]", spec.strip(), maxsplit=1)[0]
    if name != package:
        return None
    remainder = spec.strip()[len(name):]
    match = re.search(r"(?:==|>=)\s*([0-9][^,;\s]*)", remainder)
    return match.group(1) if match else None


def _uv_discover(repo: Path, package: str) -> list[PinSite]:
    path = repo / "pyproject.toml"
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sections: list[tuple[str, list]] = []
    project = data.get("project", {})
    if isinstance(project.get("dependencies"), list):
        sections.append(("project.dependencies", project["dependencies"]))
    for group, specs in (data.get("dependency-groups") or {}).items():
        if isinstance(specs, list):
            sections.append((f"dependency-groups.{group}", specs))
    for extra, specs in (project.get("optional-dependencies") or {}).items():
        if isinstance(specs, list):
            sections.append((f"optional-dependencies.{extra}", specs))
    sites: list[PinSite] = []
    for label, specs in sections:
        for spec in specs:
            if not isinstance(spec, str):
                continue
            version = _uv_pin_version(spec, package)
            if version is not None:
                sites.append(PinSite("pyproject.toml", label, version))
                break
    return sites


def _uv_mutation(package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    dev_only = bool(sites) and all(
        s.label.startswith(("dependency-groups", "optional-dependencies")) for s in sites
    )
    flag = "--dev " if dev_only else ""
    return [f"uv add {flag}'{package}>={new}'"]


def _uv_verifier(package: str, old: str, new: str, sites: list[PinSite]) -> str:
    return "uv lock --check"
```

Then extend the registry:

```python
PROFILES["uv"] = ToolingProfile("uv", _uv_discover, _uv_mutation, _uv_verifier)
```

(Move the `import tomllib` and `import re` to the top import block; `re` is already imported.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_profiles_dependency_update.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/intent_packages/profiles/dependency_update.py tests/factory/test_profiles_dependency_update.py
git commit -m "feat: uv variant for dependency-update profile"
```

---

## Task 4: profile registry — npm variant (consumes Task 0)

**Files:**
- Modify: `src/intent_packages/profiles/dependency_update.py`
- Test: `tests/factory/test_profiles_dependency_update.py` (add npm tests)

**Interfaces:**
- Consumes: Task 0 evidence (`docs/superpowers/evidence/2026-07-17-npm-envelope-preflight.md`) for the exact mutator/verifier strings; `PinSite`, `ToolingProfile`, `PROFILES`.
- Produces: `PROFILES["npm"]`. `discover_pin_sites` parses `package.json` `dependencies`/`devDependencies` (`.file == "package.json"`, `.label == "dependencies"`/`"devDependencies"`, `.current_version` == the version string, exact or with a leading `^`/`~` stripped for comparison). Mutation and verifier per Task 0.

**If Task 0 concluded npm is unsupported-pending-runner-node:** implement `_npm_mutation`/`_npm_verifier` to `raise ProfileError("npm unsupported: hosted runner lacks node/npm — see 2026-07-17-npm-envelope-preflight.md")`, register the profile with a working `_npm_discover` only, and skip the mutation/verifier tests (assert the `ProfileError` instead). Then STOP.

- [ ] **Step 1: Write the failing test** (values below assume Task 0 proved `npm install <pkg>@<new> --save-exact`; adjust to Task 0's actual strings)

```python
# add to tests/factory/test_profiles_dependency_update.py
import json as _json


def test_npm_discovers_dependency(tmp_path):
    _write(tmp_path, "package.json", _json.dumps({
        "dependencies": {"zod": "3.23.8"}, "devDependencies": {"typescript": "5.4.5"},
    }))
    sites = dep.PROFILES["npm"].discover_pin_sites(tmp_path, "zod")
    assert [(s.label, s.current_version) for s in sites] == [("dependencies", "3.23.8")]


def test_npm_mutation_and_verifier(tmp_path):
    sites = [dep.PinSite("package.json", "dependencies", "3.23.8")]
    cmds = dep.PROFILES["npm"].mutation_commands("zod", "3.23.8", "3.24.0", sites)
    assert cmds == ["npm install zod@3.24.0 --save-exact"]
    v = dep.PROFILES["npm"].verifier_command("zod", "3.23.8", "3.24.0", sites)
    assert v == "grep -q '\"zod\": \"3.24.0\"' package.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/factory/test_profiles_dependency_update.py -k npm -v`
Expected: FAIL with `KeyError: 'npm'`

- [ ] **Step 3: Write the implementation** (adjust strings to Task 0)

```python
# add to src/intent_packages/profiles/dependency_update.py
import json

_NPM_SECTIONS = ("dependencies", "devDependencies")


def _npm_discover(repo: Path, package: str) -> list[PinSite]:
    path = repo / "package.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    sites: list[PinSite] = []
    for section in _NPM_SECTIONS:
        deps = data.get(section)
        if isinstance(deps, dict) and package in deps:
            version = str(deps[package]).lstrip("^~")
            sites.append(PinSite("package.json", section, version))
    return sites


def _npm_mutation(package: str, old: str, new: str, sites: list[PinSite]) -> list[str]:
    dev = bool(sites) and all(s.label == "devDependencies" for s in sites)
    flag = " --save-dev" if dev else ""
    return [f"npm install {package}@{new} --save-exact{flag}"]


def _npm_verifier(package: str, old: str, new: str, sites: list[PinSite]) -> str:
    return f"grep -q '\"{package}\": \"{new}\"' package.json"


PROFILES["npm"] = ToolingProfile("npm", _npm_discover, _npm_mutation, _npm_verifier)
```

(Move `import json` to the top import block.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_profiles_dependency_update.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/intent_packages/profiles/dependency_update.py tests/factory/test_profiles_dependency_update.py
git commit -m "feat: npm variant for dependency-update profile"
```

---

## Task 5: orchestrator CLI subprocess wrappers

**Files:**
- Create: `src/intent_packages/factory/orchestrator_cli.py`
- Test: `tests/factory/test_orchestrator_cli.py`

**Interfaces:**
- Produces:
  - `OrchestratorCliError(Exception)`.
  - `class OrchestratorClient:` constructed as `OrchestratorClient(runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None)`. Default runner shells `subprocess.run([...], capture_output=True, text=True)`; tests inject a fake.
  - `.show_package_intake(revision_id: str) -> dict`
  - `.conformance_claim(repo_path: str) -> dict`
  - `.propose_decomposition(revision_id: str, proposal_path: str) -> dict`
  - Each builds argv `["orchestrator", <cmd>, ..., "--json"]`, runs it, parses stdout as JSON, and raises `OrchestratorCliError` if the process exited non-zero, stdout isn't JSON, or the JSON has an `"error"` key.

- [ ] **Step 1: Write the failing test**

```python
# tests/factory/test_orchestrator_cli.py
import json
import subprocess

import pytest

from intent_packages.factory.orchestrator_cli import OrchestratorClient, OrchestratorCliError


def _fake(returncode, stdout):
    def runner(argv):
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")
    return runner


def test_show_package_intake_parses_json():
    payload = {"acceptance_criteria": [{"id": "uuid-1", "ac_id": "AC-001"}]}
    client = OrchestratorClient(runner=_fake(0, json.dumps(payload)))
    assert client.show_package_intake("rev-1") == payload


def test_error_key_raises():
    client = OrchestratorClient(runner=_fake(0, json.dumps({"error": {"code": "boom"}})))
    with pytest.raises(OrchestratorCliError, match="boom"):
        client.show_package_intake("rev-1")


def test_nonzero_exit_raises():
    client = OrchestratorClient(runner=_fake(1, ""))
    with pytest.raises(OrchestratorCliError):
        client.conformance_claim("/tmp/repo")


def test_conformance_builds_expected_argv():
    seen = {}

    def runner(argv):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"status": "green"}), stderr="")

    OrchestratorClient(runner=runner).conformance_claim("/tmp/repo")
    assert seen["argv"] == ["orchestrator", "conformance-claim", "/tmp/repo", "--json"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/factory/test_orchestrator_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/intent_packages/factory/orchestrator_cli.py
"""Thin subprocess wrappers over the `orchestrator` CLI (must be on PATH).

Mirrors emitter.py's shell-out pattern so intent-packages keeps a pyyaml-only
runtime footprint. Every call uses --json (compact json.dumps stdout) and treats
an "error" key or a non-zero exit as failure.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class OrchestratorCliError(Exception):
    """Raised when an `orchestrator` CLI call fails or returns an error body."""


def _default_runner(argv: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(argv, capture_output=True, text=True, timeout=120)


class OrchestratorClient:
    def __init__(self, runner: Runner | None = None) -> None:
        self._run = runner or _default_runner

    def _call(self, argv: list[str]) -> dict:
        result = self._run(["orchestrator", *argv, "--json"])
        if result.returncode != 0:
            raise OrchestratorCliError(
                f"orchestrator {' '.join(argv)} exited {result.returncode}: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise OrchestratorCliError(f"non-JSON output: {result.stdout!r}") from error
        if isinstance(value, dict) and "error" in value:
            raise OrchestratorCliError(str(value["error"]))
        if not isinstance(value, dict):
            raise OrchestratorCliError(f"expected a JSON object, got {type(value).__name__}")
        return value

    def show_package_intake(self, revision_id: str) -> dict:
        return self._call(["show-package-intake", revision_id])

    def conformance_claim(self, repo_path: str) -> dict:
        return self._call(["conformance-claim", repo_path])

    def propose_decomposition(self, revision_id: str, proposal_path: str) -> dict:
        return self._call(["propose-decomposition", revision_id, "--data", f"@{proposal_path}"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_orchestrator_cli.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/intent_packages/factory/orchestrator_cli.py tests/factory/test_orchestrator_cli.py
git commit -m "feat: orchestrator CLI subprocess wrappers"
```

---

## Task 6: the three owned validations

**Files:**
- Create: `src/intent_packages/factory/validations.py`
- Test: `tests/factory/test_validations.py`

**Interfaces:**
- Consumes: `PinSite`, `DENIED_VERIFIER_PATTERNS` from `profiles.dependency_update`.
- Produces:
  - `ValidationError(Exception)`.
  - `dry_run_mutation(repo_path: Path, allowed_commands: list[str]) -> set[str]` — `git clone --local` the repo at HEAD into a temp dir, run each command via `subprocess.run(cmd, shell=True, cwd=clone, check=True)`, capture `git diff --name-only` after the **first** full pass (fail closed if empty), run the whole list a **second** time and fail closed if `git diff --name-only` changed. Returns the set of changed repo-relative paths. Cleans up the temp clone.
  - `assert_pin_sites_moved(changed_files: set[str], sites: list[PinSite]) -> None` — fail closed if any `site.file` is not in `changed_files`.
  - `assert_runner_honest(allowed_commands: list[str]) -> None` — fail closed if any command matches a `DENIED_VERIFIER_PATTERNS` entry.

- [ ] **Step 1: Write the failing test**

```python
# tests/factory/test_validations.py
import subprocess
from pathlib import Path

import pytest

from intent_packages.factory.validations import (
    ValidationError,
    assert_pin_sites_moved,
    assert_runner_honest,
    dry_run_mutation,
)
from intent_packages.profiles.dependency_update import PinSite


def _git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name, text in files.items():
        (repo / name).write_text(text, encoding="utf-8")
    for argv in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "init"]):
        subprocess.run(["git", *argv], cwd=repo, check=True)
    return repo


def test_dry_run_reports_changed_file(tmp_path):
    repo = _git_repo(tmp_path, {"requirements.txt": "fastapi==0.139.0\n"})
    changed = dry_run_mutation(repo, [
        "sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt",
        "grep -qx 'fastapi==0.139.2' requirements.txt",
    ])
    assert changed == {"requirements.txt"}


def test_dry_run_fails_closed_on_no_diff(tmp_path):
    repo = _git_repo(tmp_path, {"requirements.txt": "fastapi==0.139.2\n"})
    with pytest.raises(ValidationError, match="no diff"):
        dry_run_mutation(repo, [
            "sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt",
        ])


def test_pin_site_coverage_fails_when_site_untouched():
    sites = [PinSite("requirements.txt", "requirements.txt", "0.139.0"),
             PinSite("requirements-dev.txt", "requirements-dev.txt", "0.139.0")]
    with pytest.raises(ValidationError, match="requirements-dev.txt"):
        assert_pin_sites_moved({"requirements.txt"}, sites)


def test_runner_honest_rejects_make_check():
    with pytest.raises(ValidationError, match="make check"):
        assert_runner_honest(["uv add 'x>=1'", "uv run make check"])


def test_runner_honest_allows_uv_lock_check():
    assert assert_runner_honest(["uv add 'x>=1'", "uv lock --check"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/factory/test_validations.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/intent_packages/factory/validations.py
"""The three owned fail-closed validations for a dependency-update envelope.

#1 dry_run_mutation      — real diff + idempotency against a clean clone at HEAD.
#4 assert_pin_sites_moved — every discovered pin-site file is actually changed.
#2 assert_runner_honest  — no tool-guarded check the bare runner can't run.
(#3 conformance-from-real-scan is structural in decompose.py — no code path
 accepts a hand-typed conformance.)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from intent_packages.profiles.dependency_update import DENIED_VERIFIER_PATTERNS, PinSite


class ValidationError(Exception):
    """Raised when a fail-closed validation rejects the envelope."""


def _diff_names(clone: Path) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only"], cwd=clone, capture_output=True, text=True, check=True
    )
    return {line for line in result.stdout.splitlines() if line}


def dry_run_mutation(repo_path: Path, allowed_commands: list[str]) -> set[str]:
    clone = Path(tempfile.mkdtemp(prefix="factory-dryrun-"))
    target = clone / "repo"
    try:
        subprocess.run(
            ["git", "clone", "--local", "--quiet", str(repo_path), str(target)], check=True
        )
        for command in allowed_commands:
            subprocess.run(command, shell=True, cwd=target, check=True)
        first = _diff_names(target)
        if not first:
            raise ValidationError("mutation produced no diff (already at target, or no-op mutator)")
        for command in allowed_commands:
            subprocess.run(command, shell=True, cwd=target, check=True)
        second = _diff_names(target)
        if second != first:
            raise ValidationError(
                f"mutation is not idempotent: changed files differ on second run "
                f"({sorted(first)} -> {sorted(second)})"
            )
        return first
    finally:
        shutil.rmtree(clone, ignore_errors=True)


def assert_pin_sites_moved(changed_files: set[str], sites: list[PinSite]) -> None:
    for site in sites:
        if site.file not in changed_files:
            raise ValidationError(
                f"pin site not updated: {site.file} ({site.label}) was not changed by the mutator"
            )


def assert_runner_honest(allowed_commands: list[str]) -> None:
    for command in allowed_commands:
        for pattern in DENIED_VERIFIER_PATTERNS:
            if re.search(pattern, command):
                raise ValidationError(
                    f"runner-dishonest command (bare runner cannot run it): {command!r}"
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_validations.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/intent_packages/factory/validations.py tests/factory/test_validations.py
git commit -m "feat: dry-run + pin-site + runner-honesty validations"
```

---

## Task 7: the decompose flow

**Files:**
- Create: `src/intent_packages/factory/decompose.py`
- Test: `tests/factory/test_decompose.py`

**Interfaces:**
- Consumes: `OrchestratorClient` (Task 5), `profiles.dependency_update` (Tasks 2-4), `validations` (Task 6).
- Produces:
  - `DecomposeError(Exception)`.
  - `build_proposal(intake: dict, ac: str, unit_key: str, target_repo: str, tooling, package, old, new, conformance: dict, sites, rationale: str) -> dict` — pure: maps `ac`→its UUID, builds `ac_mappings` + full-coverage `retained_acs`, assembles the envelope via `build_envelope`, returns the full proposal body (`idempotency_key`, `expected_version:0`, `rationale`, `proposed_units`, `dependencies:[]`, `ac_mappings`, `retained_acs`).
  - `run(*, revision, ac, target_repo, repo_path, tooling, package, from_version, to_version, unit_key, rationale, out, submit, client=None) -> int` — the orchestration; returns 0 on success, 1 on any `DecomposeError`/`ValidationError`/`OrchestratorCliError`/`ProfileError` (message to stderr).

- [ ] **Step 1: Write the failing test**

```python
# tests/factory/test_decompose.py
import subprocess
from pathlib import Path

import pytest

from intent_packages.factory import decompose
from intent_packages.factory.orchestrator_cli import OrchestratorClient


_INTAKE = {
    "acceptance_criteria": [
        {"id": "uuid-1", "ac_id": "AC-001"},
        {"id": "uuid-2", "ac_id": "AC-002"},
        {"id": "uuid-3", "ac_id": "AC-003"},
    ]
}
_CONFORMANCE = {"accepted_standards": [], "standards_touched": ["project"], "status": "green"}


def test_build_proposal_maps_uuid_and_covers_all_acs():
    from intent_packages.profiles.dependency_update import PinSite
    sites = [PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    proposal = decompose.build_proposal(
        _INTAKE, "AC-002", "brain-ac002", "AlobarQuest/brain", "pip",
        "fastapi", "0.139.0", "0.139.2", _CONFORMANCE, sites, "retained: not this run",
    )
    assert proposal["expected_version"] == 0
    assert proposal["ac_mappings"] == [{"ac_id": "uuid-2", "unit_key": "brain-ac002"}]
    assert sorted(r["ac_id"] for r in proposal["retained_acs"]) == ["uuid-1", "uuid-3"]
    unit = proposal["proposed_units"][0]
    assert unit["required_capability"] == "repo.edit"
    assert "work_unit_id" not in unit["authority"]["constraints"]


def test_build_proposal_unknown_ac_raises():
    with pytest.raises(decompose.DecomposeError, match="AC-999"):
        decompose.build_proposal(
            _INTAKE, "AC-999", "k", "AlobarQuest/brain", "pip",
            "fastapi", "0.139.0", "0.139.2", _CONFORMANCE, [], "r",
        )


def _git_repo(tmp_path):
    repo = tmp_path / "brain"
    repo.mkdir()
    (repo / "requirements.txt").write_text("fastapi==0.139.0\n", encoding="utf-8")
    for argv in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "init"]):
        subprocess.run(["git", *argv], cwd=repo, check=True)
    return repo


def test_run_end_to_end_no_submit(tmp_path, capsys):
    repo = _git_repo(tmp_path)
    out_file = tmp_path / "proposal.json"

    def runner(argv):
        import json
        cmd = argv[1]
        body = _INTAKE if cmd == "show-package-intake" else _CONFORMANCE
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(body), stderr="")

    rc = decompose.run(
        revision="rev-1", ac="AC-002", target_repo="AlobarQuest/brain",
        repo_path=str(repo), tooling="pip", package="fastapi",
        from_version="0.139.0", to_version="0.139.2", unit_key="",
        rationale="", out=str(out_file), submit=False,
        client=OrchestratorClient(runner=runner),
    )
    assert rc == 0
    assert out_file.exists()
    import json
    body = json.loads(out_file.read_text())
    assert body["ac_mappings"][0]["ac_id"] == "uuid-2"


def test_run_fails_closed_on_no_diff(tmp_path):
    repo = tmp_path / "brain"
    repo.mkdir()
    (repo / "requirements.txt").write_text("fastapi==0.139.2\n", encoding="utf-8")  # already new
    for argv in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "init"]):
        subprocess.run(["git", *argv], cwd=repo, check=True)

    def runner(argv):
        import json
        body = _INTAKE if argv[1] == "show-package-intake" else _CONFORMANCE
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(body), stderr="")

    rc = decompose.run(
        revision="rev-1", ac="AC-002", target_repo="AlobarQuest/brain",
        repo_path=str(repo), tooling="pip", package="fastapi",
        from_version="0.139.0", to_version="0.139.2", unit_key="",
        rationale="", out="", submit=False,
        client=OrchestratorClient(runner=runner),
    )
    assert rc == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/factory/test_decompose.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/intent_packages/factory/decompose.py
"""The `factory decompose` flow: intake -> ac_mappings/retained_acs -> real-scan
conformance -> per-tooling envelope -> fail-closed validations -> emit/submit.

Human gates (intake, decomposition approval, authority approval, merge) are
out of scope. The only orchestrator write is the SYSTEM/M2M proposal submit.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from intent_packages.factory.orchestrator_cli import OrchestratorCliError, OrchestratorClient
from intent_packages.factory.validations import (
    ValidationError,
    assert_pin_sites_moved,
    assert_runner_honest,
    dry_run_mutation,
)
from intent_packages.profiles.dependency_update import ProfileError, build_envelope


class DecomposeError(Exception):
    """Raised when a decomposition request is malformed or a criterion is unknown."""


def _criteria_uuid_map(intake: dict) -> dict[str, str]:
    criteria = intake.get("acceptance_criteria") or []
    return {c["ac_id"]: c["id"] for c in criteria}


def build_proposal(
    intake: dict,
    ac: str,
    unit_key: str,
    target_repo: str,
    tooling: str,
    package: str,
    old: str,
    new: str,
    conformance: dict,
    sites: list,
    rationale: str,
) -> dict:
    uuids = _criteria_uuid_map(intake)
    if ac not in uuids:
        raise DecomposeError(f"acceptance criterion {ac} not found in revision")
    mapped_uuid = uuids[ac]
    envelope = build_envelope(target_repo, tooling, package, old, new, conformance, sites)
    retained = [
        {"ac_id": uuid, "rationale": rationale or f"not addressed by the {package} update ({ac})"}
        for human_id, uuid in uuids.items()
        if human_id != ac
    ]
    return {
        "idempotency_key": f"factory-decompose-{target_repo}-{package}-{new}".replace("/", "-"),
        "expected_version": 0,
        "rationale": rationale or f"Dependency update: {package} {old} -> {new} in {target_repo}.",
        "proposed_units": [
            {
                "unit_key": unit_key,
                "title": f"Update {package} to {new} in {target_repo}",
                "outcome": (
                    f"{target_repo} receives a PR that moves {package} {old} -> {new}; "
                    f"its named check passes on the PR head."
                ),
                "required_capability": "repo.edit",
                "authority": envelope,
                "max_attempts": 3,
            }
        ],
        "dependencies": [],
        "ac_mappings": [{"ac_id": mapped_uuid, "unit_key": unit_key}],
        "retained_acs": retained,
    }


def _resolve_repo_path(target_repo: str, repo_path: str) -> Path:
    if repo_path:
        return Path(repo_path).expanduser()
    return Path(os.environ["HOME"]) / "Projects" / target_repo.split("/", 1)[-1]


def run(
    *,
    revision: str,
    ac: str,
    target_repo: str,
    repo_path: str,
    tooling: str,
    package: str,
    from_version: str,
    to_version: str,
    unit_key: str,
    rationale: str,
    out: str,
    submit: bool,
    client: OrchestratorClient | None = None,
) -> int:
    client = client or OrchestratorClient()
    resolved_key = unit_key or f"{target_repo.split('/', 1)[-1]}-{ac.lower()}"
    local_repo = _resolve_repo_path(target_repo, repo_path)
    try:
        if not local_repo.is_dir():
            raise DecomposeError(f"target checkout not found: {local_repo}")
        from intent_packages.profiles.dependency_update import PROFILES

        if tooling not in PROFILES:
            raise DecomposeError(f"unknown tooling: {tooling}")
        sites = PROFILES[tooling].discover_pin_sites(local_repo, package)
        if not sites:
            raise DecomposeError(f"no pin site for {package} in {local_repo} ({tooling})")

        intake = client.show_package_intake(revision)
        conformance = client.conformance_claim(str(local_repo))

        proposal = build_proposal(
            intake, ac, resolved_key, target_repo, tooling,
            package, from_version, to_version, conformance, sites, rationale,
        )
        allowed = proposal["proposed_units"][0]["authority"]["constraints"]["allowed_commands"]

        assert_runner_honest(allowed)
        changed = dry_run_mutation(local_repo, allowed)
        assert_pin_sites_moved(changed, sites)

        body = json.dumps(proposal, indent=2, sort_keys=True)
        if out:
            Path(out).write_text(body + "\n", encoding="utf-8")
        else:
            print(body)

        if submit:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
                handle.write(body)
                proposal_path = handle.name
            try:
                result = client.propose_decomposition(revision, proposal_path)
            finally:
                os.unlink(proposal_path)
            print(f"submitted: {json.dumps(result, sort_keys=True)}", file=sys.stderr)
        return 0
    except (DecomposeError, ValidationError, OrchestratorCliError, ProfileError) as error:
        print(f"decompose failed: {error}", file=sys.stderr)
        return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_decompose.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/intent_packages/factory/decompose.py tests/factory/test_decompose.py
git commit -m "feat: decompose flow wiring intake, conformance, envelope, validations"
```

---

## Task 8: wire the CLI to the flow + docs

**Files:**
- Modify: `src/intent_packages/factory_cli.py` (call `decompose.run`)
- Modify: `tests/factory/test_factory_cli.py` (assert delegation)
- Modify: `README.md` and `CLAUDE.md` (document `factory decompose` + `orchestrator` CLI prerequisite)

**Interfaces:**
- Consumes: `intent_packages.factory.decompose.run(**opts) -> int`.

- [ ] **Step 1: Write the failing test** (replace `test_decompose_parses_all_args` from Task 1)

```python
# tests/factory/test_factory_cli.py — replace the parse test with a delegation test
def test_decompose_delegates_to_run(monkeypatch):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr("intent_packages.factory.decompose.run", fake_run)
    rc = main([
        "decompose", "--revision", "rev-1", "--ac", "AC-002",
        "--target-repo", "AlobarQuest/brain", "--tooling", "pip",
        "--package", "fastapi", "--from", "0.139.0", "--to", "0.139.2", "--submit",
    ])
    assert rc == 0
    assert seen["revision"] == "rev-1" and seen["ac"] == "AC-002"
    assert seen["from_version"] == "0.139.0" and seen["to_version"] == "0.139.2"
    assert seen["submit"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/factory/test_factory_cli.py::test_decompose_delegates_to_run -v`
Expected: FAIL (current handler prints instead of delegating; `seen` stays empty → KeyError)

- [ ] **Step 3: Wire the handler**

Replace the `if args.cmd == "decompose":` block in `main` with:

```python
    if args.cmd == "decompose":
        from intent_packages.factory import decompose

        return decompose.run(
            revision=args.revision,
            ac=args.ac,
            target_repo=args.target_repo,
            repo_path=args.repo_path,
            tooling=args.tooling,
            package=args.package,
            from_version=args.from_version,
            to_version=args.to_version,
            unit_key=args.unit_key,
            rationale=args.rationale,
            out=args.out,
            submit=args.submit,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/ -v`
Expected: PASS (all factory tests green)

- [ ] **Step 5: Document** — append to `README.md` a `## factory decompose` section and add a note under `CLAUDE.md` "Key invariants":

README section (verbatim):

```markdown
## factory decompose

Author + validate a dependency-update decomposition proposal for an intaken revision:

```bash
factory decompose --revision <id> --ac AC-002 --target-repo AlobarQuest/brain \
  --tooling pip --package fastapi --from 0.139.0 --to 0.139.2 [--out proposal.json] [--submit]
```

Requires the `orchestrator` CLI on PATH and `ORCHESTRATOR_API_URL` / `ORCHESTRATOR_API_TOKEN` /
`ORCHESTRATOR_API_CREDENTIAL_KEY_ID` set (use the **system** M2M credential for `--submit`).
Without `--submit` it validates and prints the proposal only. It never approves or merges.
```

CLAUDE.md note (verbatim, add as a new bullet under "## Key invariants"):

```markdown
- `factory decompose` (WS-P2.9 slice) shells the `orchestrator` CLI and never accepts a
  hand-typed conformance; the emitted envelope omits `constraints.work_unit_id` (orchestrator
  stamps it) and `ac_mappings`/`retained_acs` carry criterion DB UUIDs, not the "AC-001" string.
```

- [ ] **Step 6: Run the full gate**

Run: `make check`
Expected: ruff/pyright clean; `pytest` shows all tests passing (existing + new `tests/factory/`), non-zero `collected N items`.

- [ ] **Step 7: Commit**

```bash
git add src/intent_packages/factory_cli.py tests/factory/test_factory_cli.py README.md CLAUDE.md
git commit -m "feat: wire factory decompose CLI to the flow + document it"
```

---

## Self-Review

**Spec coverage:**
- Criterion-UUID resolution + `ac_mappings`/`retained_acs` full coverage → Task 7 (`build_proposal`, `_criteria_uuid_map`).
- Conformance from real scanners, never hand-typed → Task 5 (`conformance_claim`) + Task 7 (only source; structural).
- Per-tooling envelope template (uv/pip/npm) → Tasks 2/3/4 + `build_envelope`.
- Omit `work_unit_id` → Task 2 `build_envelope` (asserted in tests).
- Validation #1 dry-run + idempotency → Task 6 `dry_run_mutation`.
- Validation #2 runner-honest → Task 6 `assert_runner_honest` + Task 2 `DENIED_VERIFIER_PATTERNS`.
- Validation #3 conformance real-scan → structural (Tasks 5+7).
- Validation #4 name-every-pin-site → Task 6 `assert_pin_sites_moved` (file-level; note uv section-level caveat below).
- Submit (SYSTEM/M2M) → Task 5 `propose_decomposition` + Task 7 `--submit`.
- Human gates untouched → no approve/merge code anywhere; `--submit` is the only write.
- `factory` front door extensible for journey verbs → Task 1 subparser structure.

**Known limitation (documented, not a gap):** validation #4 is file-level; for uv a pin duplicated across two `pyproject.toml` sections lives in one file, so file-level coverage passes even if one section is stale. The dry-run still runs `uv add` (which resolves jointly) and `uv lock --check` fails closed on an unsatisfiable lock, so the multi-section uv hazard is caught at dry-run, not by #4. If a real uv multi-section case appears, add a section-level check to `assert_pin_sites_moved` for `pyproject.toml` sites (re-read the file, assert each `.label` section no longer contains `old`).

**Placeholder scan:** none — every step has real code/tests. Task 4's npm strings are gated on Task 0's proof and carry an explicit fallback branch.

**Type consistency:** `PinSite`/`ToolingProfile`/`build_envelope`/`OrchestratorClient`/`dry_run_mutation`/`assert_*`/`build_proposal`/`run` signatures are consistent across tasks 2-8.
