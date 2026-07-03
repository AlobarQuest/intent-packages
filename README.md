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
