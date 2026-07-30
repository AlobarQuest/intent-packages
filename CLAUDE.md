# intent-packages

Universal intent-package schema, lifecycle, and validate/hash/approve CLI for the
software factory (WS-2.1). Provides the foundation format that later workstreams
(domain profiles, intent-authoring skill, pilots, and the Phase-3 orchestrator)
build on.

## Invocation (zero-install)

```bash
PYTHONPATH=src python3 -m intent_packages <cmd>   # validate | hash | transition | approve | revise | supersede | verify-approval
```

## Key invariants

- Packages are plain YAML in git: `packages/<id>/package.yaml` + `packages/<id>/lineage.yaml`.
- `status` is the one field excluded from the canonical hash — every other key is
  immutable intent (`sha256(RFC-8785 JCS(intent_core))`).
- Approval binds to an immutable revision and is verified against a tamper-evident,
  hash-chained factory-events store (a YAML ledger alone is forgeable and not
  sufficient proof).
- Never merge — PRs wait for Devon.
- The `factory` CLI speaks **HTTP** to the orchestrator API for every API call
  (`intent_packages/factory/api.py::OrchestratorApi`), and shells out to the `orchestrator` CLI
  **only** for local computation the orchestrator owns: `emit-intake-payload` and
  `conformance-claim` (`factory/orchestrator_cli.py`). One transport, one auth path, one error
  vocabulary. `factory decompose` in particular used to shell out for `show-package-intake` and
  `propose-decomposition`; both moved to HTTP in WS-P2.9. Consequence for operators: it reads
  `ORCHESTRATOR_SYSTEM_TOKEN` (or fetches from BWS), **not** the generic
  `ORCHESTRATOR_API_TOKEN` the orchestrator CLI used — deliberately with no fallback, because
  that variable can hold any role's token and a wrong-role token fails more confusingly than
  "not set".
- `factory decompose` never accepts a hand-typed conformance; the emitted envelope omits
  `constraints.work_unit_id` (orchestrator stamps it) and `ac_mappings`/`retained_acs` carry
  criterion DB UUIDs, not the "AC-001" string.
- Human gates (package intake, decomposition decision, authority approval) are browser-only
  **permanently**, by ADR-0006. The CLI prepares, deep-links `/review`, and resumes; it never
  impersonates a human and must not grow a flag that pretends to. A future reviewer finding one
  should treat it as a defect, not a feature.

## Spec

See `docs/superpowers/specs/2026-07-03-ws21-intent-package-schema.md` for the full
schema, lifecycle, and design-decision record.

<!-- code-standards:start -->
# Code Quality (code-standards layer)

Standards reference: `~/Developer/code-standards/STANDARDS.md`

## Before writing a cross-cutting pattern — query Code Brain

Before implementing a recurring cross-cutting concern (logging, error handling,
auth, notifications, API conventions, secrets, …), query **Code Brain** — the
machine source of record for our paved roads — and follow its rules:

- `get_road("<slug>")` → the decided approach + rules + exemplars, or
- `get_rules(severity="BLOCK")` → the must-follow rules.

Do **not** infer the standard from existing code; it may predate the standard.
When you decide a new cross-cutting pattern, write it back (`add_road` / `add_rule`).

## Before declaring a non-trivial change done

1. Run `make check` — full-repo lint, type-check, and tests must be green.
2. Run `/code-review` — review the diff for correctness bugs and simplification opportunities.

Both gates apply to any change that touches logic, interfaces, or configuration.
Trivial fixes (typos, comment edits) may skip `/code-review` at your discretion.

## Enforcement

A diff-scoped Stop hook enforces this automatically: it runs the linters over your
changed files when the session ends and blocks completion if new violations are
introduced. Existing baseline violations are tracked and do not block.

## Canonical example module

The authoritative pattern for this repo's style is:

the cleanest, most idiomatic existing module in this repo

When writing new code, mirror the structure, naming conventions, and documentation
style of that module.

<!-- code-standards:end -->
