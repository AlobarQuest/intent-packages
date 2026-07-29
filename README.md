# intent-packages

Universal **intent packages** for the software factory — a domain-neutral, versioned, immutable-when-approved
description of a desired outcome, plus the CLI that validates, hashes, and records approvals.

An intent package says *what should become true*, within what scope, drawing on which sources (classified
trusted-instruction vs untrusted-data), under what constraints, with acceptance criteria that each carry an
evidence requirement and an approver, an explicit authority envelope, and a lifecycle. Packages are **YAML in
git**. Approval binds to an immutable revision whose sha256 is recorded, so an agent reading a package can
determine `ready` / `blocked` / `not authorized` without improvising.

This repo is **WS-2.1** of the factory (Phase 2). It ships the *universal envelope* only; domain profiles
(software-delivery, infrastructure-change, listing-launch), the authoring skill, and the orchestrator that
executes packages come in later workstreams.

## CLI (zero-install)

```bash
PYTHONPATH=src python3 -m intent_packages <command>
```

| Command | What it does |
|---------|--------------|
| `validate <path> \| --all` | Schema + semantic checks; actionable errors; non-zero exit on failure. |
| `hash <path>` | Deterministic `sha256(JCS(intent_core))` of the immutable intent core. |
| `transition <path> --to <state>` | Perform a legal lifecycle transition. |
| `approve <path>` | Devon-only: bind approval to the current revision's hash. |
| `revise <path>` | Register a new revision after a material intent edit. |
| `verify-approval <path> [--revision N]` | Mechanically confirm a revision was approved. |

## Layout

```
packages/<package_id>/
  package.yaml    # the intent (status field is excluded from the hash)
  lineage.yaml    # append-only revisions + transitions + approvals
```

## Design

See `docs/superpowers/specs/2026-07-03-ws21-intent-package-schema.md`.

## Delivery profiles

Registered profiles (declared via `profile:` in `package.yaml`; validated at authoring time by
`intent_packages validate`):

- `software-delivery` — repo-backed delivery (WS-2.2)
- `infrastructure-change` — infra changes with blast-radius vocabulary (WS-2.2)
- `dependency-update` — factory-executable pin moves; production-proven (GAP-4)
- `maintenance-remediation` — bounded fix from an approved handoff item (Phase-3 authoring target)
- `non-software-operational` — no-repo operational work (listing launches; WS-P2.13 vehicle)

Named stubs (not registered; owners and promotion triggers in
`docs/superpowers/specs/2026-07-29-wsp210-profiles-routing-policy-design.md`):
docs-only, python-service, ts-service, emergency-remediation.

## Model routing

`routing-policy.toml` (repo root) is the sole source of model selection (program exit criterion #11),
seeded from the decided 2026-07-08 table. Query it:

```bash
factory route --surface runner-implementation
factory route --change-class dependency-update
```

`factory decompose` fails closed if a change-class has no routing row. Graduation edits follow the
contract in the file's header comment.

## factory decompose

Author + validate a dependency-update decomposition proposal for an intaken revision:

```bash
factory decompose --revision <id> --ac AC-002 --target-repo AlobarQuest/brain \
  --tooling pip --package fastapi --from 0.139.0 --to 0.139.2 [--out proposal.json] [--submit]
```

Requires the `orchestrator` CLI on PATH and `ORCHESTRATOR_API_URL` / `ORCHESTRATOR_API_TOKEN` /
`ORCHESTRATOR_API_CREDENTIAL_KEY_ID` set (use the **system** M2M credential for `--submit`).
Without `--submit` it validates and prints the proposal only. It never approves or merges.
