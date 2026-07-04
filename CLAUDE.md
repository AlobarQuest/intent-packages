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
