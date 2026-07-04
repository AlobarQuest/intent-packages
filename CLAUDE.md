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
