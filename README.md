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

## factory — the front-door CLI

```bash
PYTHONPATH=src python3 -m intent_packages.factory_cli <verb> [flags]
```

(or, if the console script is on `PATH`: `factory <verb> [flags]`.)

Ten verbs carry an intent package from scaffold to a verified, merged PR. Each is a thin front
door over the orchestrator's own API and lifecycle rules — it validates, derives, and refuses
locally where it safely can, but it never invents an approval, a merge, or a human decision.

| Verb | What it does |
|------|--------------|
| `create` | Scaffold a package from a registered delivery profile (`--profile`, `--name`). |
| `validate` | Validate a package directory or `package.yaml`. |
| `route` | Resolve a model from `routing-policy.toml` by `--surface` or `--change-class`. |
| `decompose` | Author + validate a dependency-update decomposition proposal for an intaken revision. |
| `submit` | Stage an intake payload, copy it, and print the `/review/intakes/new` link. Stops there. |
| `status` | One screen for a revision: intake, proposals, units, and the next action. `--wait` polls until a unit's state changes. |
| `evidence` | Fetch a revision's or a unit's evidence pack (`--unit-key`; `--markdown` for the redacted PR-comment form). |
| `ready` | SYSTEM: move a unit `DRAFT -> READY` (an authority approval alone never does this). |
| `dispatch` | SYSTEM: dispatch a `READY` unit to the runner. |
| `verify` | VERIFIER: post named-check evidence, then evaluate the unit's acceptance criteria. |

`decompose`'s usage, as the most-flagged verb:

```bash
factory decompose --revision <id> --ac AC-002 --target-repo AlobarQuest/brain \
  --tooling pip --package fastapi --from 0.139.0 --to 0.139.2 [--out proposal.json] [--submit]
```

Without `--submit` it validates and prints the proposal only. It never approves or merges.

### Credentials

`ready`, `dispatch`, `status`, `evidence` and decomposition submission use the **SYSTEM** role;
`verify` uses the **VERIFIER** role. Each resolves its bearer token from the environment first,
falling back to Bitwarden Secrets Manager (`bws secret get`, keyed by the UUIDs in
`.bws-secrets.toml`) when `BWS_ACCESS_TOKEN` is set:

- `ORCHESTRATOR_SYSTEM_TOKEN` — SYSTEM role.
- `ORCHESTRATOR_VERIFIER_TOKEN` — VERIFIER role.

**`factory decompose`'s environment contract changed on this branch.** It used to shell out to
the `orchestrator` CLI entirely and read `ORCHESTRATOR_API_TOKEN`. It now speaks HTTP directly for
every API call (shelling out only for local computation — `conformance-claim`,
`emit-intake-payload`) and reads **`ORCHESTRATOR_SYSTEM_TOKEN`** instead, with the same BWS
fallback as every other verb above. If you're following an older note (including the
orchestrator repo's own docs, which still name the old variable) and see a clean "no credential"
error, it's naming the current variable, not a broken credential.

`ORCHESTRATOR_API_URL` selects the orchestrator base URL for every verb (default
`http://127.0.0.1:8000`).

### `$FACTORY_REVISION`

`status`, `evidence`, `ready`, `dispatch` and `verify` all take an optional `--revision`; when it
is omitted, each falls back to `$FACTORY_REVISION`. Neither set is a clean exit code `2` naming
the missing variable — never a stack trace.

### `--verbose`

A global flag: `factory --verbose <verb> ...` prints `METHOD /path -> status` for every
orchestrator API call that verb makes. It never prints a token, request body, or response body —
only the request line.

### Human gates are browser-only, permanently (ADR-0006)

No `factory` verb can act as a human, and none ever will — there is no `--as-human`, `--human`,
`--force`, or `--impersonate` flag, and the orchestrator's own decomposition- and
authority-approval routes require a real `HUMAN` actor. Where the flow reaches a human gate
(package intake, decomposition approval, authority approval), the CLI **stops**: it stages the
payload, copies it to the clipboard, and prints a `/review` deep link for you to act on in a
browser. `submit` is the clearest example — it can never complete an intake itself, by design.
