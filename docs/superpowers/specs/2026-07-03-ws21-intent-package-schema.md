# WS-2.1 — Universal Intent-Package Schema, Lifecycle, and validate/hash/approve CLI

**Status:** Design approved 2026-07-03 (Devon); revised after Fable-5 red-team (see §16). Ready for planning.
**Workstream:** Software Factory Phase 2, WS-2.1 (opening workstream).
**Repo:** `~/Projects/intent-packages` (`AlobarQuest/intent-packages`, default branch `main`).
**Authoritative source:** companion §4 (`~/docs/software-delivery-system/2026-06-30-foundation-intent-orchestration-architecture.md`), master plan Phase 2 + D2 + D3.

---

## 1. Goal and scope

An **intent package** is a domain-neutral, versioned, immutable-when-approved description of a desired
outcome: what should become true, within what scope, drawing on which sources (classified
trusted-instruction vs untrusted-data), under what constraints, with acceptance criteria that each carry
an evidence requirement and an approver, an explicit authority envelope, and a lifecycle. Packages are
**YAML in git**; a deterministic **CLI** validates, hashes, and records approvals. Approval binds to an
immutable revision whose sha256 is recorded; an agent later reading a package can determine `ready` /
`blocked` / `not authorized` without improvising.

### In scope (WS-2.1)
1. The **universal intent-package schema** (v1) — the envelope every domain profile will extend.
2. The **lifecycle** — states + the legal-transition map + revision/supersession mechanics, enforced by
   the CLI.
3. The **CLI** — `validate`, `hash`, `transition`, `approve`, `revise`, `supersede`, `verify-approval`
   (Python 3.12+, zero-install `PYTHONPATH` module, like `agent_registry`).
4. Repo bootstrap: `foundation: true`, PROJECT.md + `foundation_contract`, STANDARD_VERSION pin, CI that
   validates every package on every PR.
5. One **dogfood package** — the WS-2.2 workstream authored as the first real package, driven through the
   full CLI path.

### Explicitly OUT of scope (later workstreams — do not build)
- Domain **profiles** (software-delivery, infrastructure-change, listing-launch) — **WS-2.2**.
- The **intent-authoring skill** (conversational intake) — **WS-2.3**.
- The **pilots** — **WS-2.4**.
- Any **orchestrator / work-unit machinery** (claims, leases, runner, action-grant granting) — **Phase 3**.
- Any **package database** — YAGNI; files + git until they hurt (master plan Part 6).
- **Retiring the ADAS repos** (`shaper`, `proto-migration`) — harvest only now; retirement waits for the
  Phase-4 runner harvest (D3), done later via the retire-project skill with Devon.

The schema must nonetheless be **decomposition-ready** (companion §4.3): the universal envelope carries
the fields a Phase-3 work unit will inherit — package identity + revision, applicable standards, authority
limits, context, evidence requirements — even though work-unit machinery is not built here.

---

## 2. Design decisions (settled with Devon 2026-07-03)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D-Q1 | Revision / immutability model | **Hash excludes `status`; approval binds to the immutable intent core.** Lifecycle advances without changing the hash. Material intent edit → new `revision` (pre-execution) or **supersession** (post-approval). | Preserves the "approved hash == executing hash" invariant the Phase-3 orchestrator needs. |
| D-Q2a | Canonicalization | **`sha256(RFC-8785 JCS(intent_core))`** — canonical JSON, not raw bytes, over strictly-typed YAML (§4.3). | Raw bytes churn on reformatting/comments/key-order; JSON canonicalization is well-specified, YAML's is not; the orchestrator can recompute independently. |
| D-Q2b | Approval proof | **`git commit -s` + append-only approvals ledger entry + a `package.approved` event in the hash-chained factory-events store.** The event is the authoritative, tamper-evident record; the ledger is a convenience mirror. No GPG/SSH commit signature for MVP. | Mechanical verifiability comes from matching the recomputed intent hash to BOTH a ledger entry and a chained event by `devon` (§4.4). A plain YAML ledger alone is forgeable by any `repository_write` actor (rule #2), so the chain is required. |
| D-Q3 | Event emission scope | **Every transition the CLI performs attempts a `factory-event/v1`.** `approve` guarantees its event is in-chain (emit is fatal); other transitions are best-effort (lineage records `event_id: null` + an `emit_error` on failure). | Approvals must be tamper-evidently audited; full lifecycle audit is desirable but not worth blocking a `blocked→executable` transition on a transient events-store outage. |
| D-Q4 | File layout | **Directory per package:** `packages/<id>/package.yaml` + `packages/<id>/lineage.yaml`. | Hashable, good git-diff review, approval provenance without git archaeology, room for WS-2.4 pilots side by side. |
| D-Q5a | Foundation status | **`foundation: true`.** | Intent-packages gates everything the factory does. |
| D-Q5b | Code-standards onboarding | **Lightweight now** (foundation_contract + STANDARD_VERSION + one real `required_check`); defer heavier tooling to Phase-2 stabilization. | Standards-conformant day one without over-investing before the schema settles. |

### Refinements from self-review + red-team
- **Two versions:** `schema_version` (envelope format, integer `1`) vs `revision` (this package's immutable
  intent revision, monotonic integer). The hash binds to a `revision`.
- **Minimal exclusion set:** the canonical hash excludes **exactly one field — `status`**. Every other key
  in `package.yaml` is immutable intent. Consequence (accepted friction): an `owner` transfer is a material
  change like any other — pre-execution it is a `revise`, post-approval a `supersede`. Ownership churn is
  rare enough that this friction is acceptable; all *administrative* facts (timestamps, transition
  authorship, approvals, grants) live in `lineage.yaml`, never in the hash.
- **Strict YAML typing** for hash determinism (§4.3) — the single most bug-prone area.

---

## 3. Universal envelope (`package.yaml`, schema_version 1)

Field-by-field. `validate` enforces required keys, types, enums, and the cross-checks in §6. The envelope
is **closed at every level** — unknown keys (top-level or nested) are an error — **except** the reserved
forward-extension keys `profile` (string) and `profile_fields` (mapping, opaque to universal validation,
validated by a profile validator in WS-2.2). Several sections provide an explicit `other: [strings]` escape
hatch so a domain need without a dedicated field is captured *inside the schema* (validated, hashed) rather
than as a stray key. **Every documented key must be present** (use an explicit `null`/`[]` when empty) so
JCS never has to distinguish absent-vs-null (§4.3).

### 3.1 Identity
```yaml
schema_version: 1                        # envelope format version (integer)
package_id: ws-2.2-domain-profiles       # kebab-case slug, unique, == directory name
title: "WS-2.2 — Domain profiles for intent packages"
revision: 1                              # monotonic intent revision (integer, starts at 1)
status: draft                            # EXCLUDED FROM HASH (§4/§5)
created_by: claude-code-interactive      # registry agent id
owner: devon                             # registry agent id
created_at: "2026-07-03T00:00:00Z"       # QUOTED string; ISO-8601 UTC regex; set once, immutable
supersedes: null                         # package_id this replaces, or null
```

### 3.2 Desired outcome
```yaml
outcome:
  what: "..."             # what becomes true
  why: "..."              # why it matters
  beneficiary: "..."      # who benefits
  success_signal: "..."   # how success is observed
```

### 3.3 Scope
```yaml
scope:
  included: [ ... ]
  excluded: [ ... ]
  non_goals: [ ... ]
  assumptions: [ ... ]
  open_questions: [ ... ]  # must be [] before approve (§6 check O)
```

### 3.4 Sources and context — trust classification mandatory
```yaml
sources:
  - location: "companion §4"
    authority_level: authoritative    # authoritative | supporting | reference
    required_version: "2026-06-30"    # string or null
    trust: trusted_instruction        # trusted_instruction | untrusted_data   (REQUIRED)
    sensitivity: internal             # public | internal | confidential | secret
```
`trust` is the rule-#3 containment hook: untrusted_data can inform a package but never carries authority to
act. Every source **must** declare `trust`. (Listing-launch example: the signed listing agreement =
`trusted_instruction`/`confidential`; Zillow comps = `untrusted_data`/`public`.)

### 3.5 Constraints
```yaml
constraints:
  time_budget: "..."          # each: string or null
  technology: "..."
  policy_legal: "..."
  privacy_security: "..."
  compatibility: "..."
  quality_accessibility: "..."
  operational: "..."
  other: [ ... ]              # escape hatch: constraints without a dedicated field (list of strings)
```

### 3.6 Acceptance criteria — id + evidence + approver, each required
```yaml
acceptance:
  - id: AC-001                    # unique within package, regex ^AC-[0-9]{3,}$
    condition: "..."             # observable statement
    evidence_type: automated_test # automated_test | automated_check | human_review
                                  # | external_attestation | observation
    evidence: "pytest tests/test_hash.py::test_deterministic passes"   # concrete evidence required
    approver: policy              # see approver forms below
```
**Approver forms** (`validate` check A): exactly one of —
- `policy` — a deterministic gate/policy closes it, no human;
- a **registry agent id** (e.g. `devon`) — that identity's judgment closes it;
- `external:<label>` — a party outside the registry (e.g. `external: "seller — 123 Main St"`), **legal only
  when** `evidence_type` ∈ {`external_attestation`, `human_review`}. This is what lets a non-software package
  (a seller sign-off, an MLS compliance desk) record *whose* judgment closes a criterion without falsifying
  it as `devon`.

`evidence` (the concrete required evidence) lives **on the acceptance item**, not in a parallel list — the
universal `verification` section (§3.11) keeps only what doesn't map 1:1 to a criterion.

### 3.7 Authority envelope — registry capability vocabulary, default-deny
```yaml
authority:
  allowed: [ repository_read, repository_write, test_execution ]   # capability terms
  requires_approval: [ merge_to_main, outward_publish ]            # need a grant before use (§3.14/§9)
  prohibited: [ secret_write, infra_mutation ]                     # explicitly forbidden
  budgets:                        # optional (ADAS harvest), null-ok
    max_attempts: null
    max_llm_calls: null
```
Terms come from `security-standards/registry/capabilities.yaml` (the 17-term vocabulary). **Semantics
(`validate` check T + the Phase-3 contract):**
- A term in **none** of the three lists is **prohibited (default-deny)** — matches the estate posture and
  removes the "must improvise" gap. An agent needs no list-membership reasoning beyond "is it in `allowed`?".
- A term appearing in **more than one** list is a hard error.
- A term **not in the vocabulary** is a hard error whose message says an unknown term needs a
  registry-addition PR (kickoff ground-truth #1 — reference registry terms, never fork them). The registry is
  located via `SECURITY_STANDARDS_DIR` (default sibling `~/Projects/security-standards`); if unavailable,
  this specific check degrades to a warning and says so, so the CLI runs in other checkouts/CI.

> **Non-software note (see §14):** the current vocabulary is software/infra-shaped. A listing-launch package
> needs verbs the 17 terms lack (spend money, contact a person, write a calendar, edit a not-yet-public MLS
> draft). Those are registry additions the WS-2.4 pilot must file first — a real cross-repo dependency, not a
> schema flaw. `validate` stays strict.

### 3.8 Deliverables and handoff
```yaml
deliverables:
  artifacts: [ ... ]
  destination: "..."
  recipient: "..."
  definition_of_done: "..."
  operator_responsibilities: [ ... ]
```

### 3.9 Dependencies — predecessors pinned by revision
```yaml
dependencies:
  predecessor_packages:            # pinned so a predecessor revised out from under us is detectable
    - package: ws-2.1-...
      revision: 3
  external_decisions: [ ... ]      # free-text blocker lists (§5.4 defines their gating semantics)
  required_people_systems: [ ... ]
  required_capabilities: [ ... ]   # capability terms
  blocking_conditions: [ ... ]
```

### 3.10 Risk and failure handling
```yaml
risk:
  failure_modes: [ ... ]
  max_impact: "..."
  stop_conditions: [ ... ]
  rollback: "..."
  escalation_target: devon        # registry agent id OR external:<label> (no free text — must be actionable)
```

### 3.11 Verification plan
```yaml
verification:
  independent_review: [ ... ]     # what needs an independent reviewer
  non_mechanical: [ ... ]         # criteria that cannot be verified mechanically
```
(Per-criterion evidence now lives on each `acceptance[]` item, §3.6 — no parallel AC-id-keyed list to join.)

### 3.12 Follow-up
```yaml
follow_up:
  required: false                 # bool; if true, completed→closed must route via follow_up_due (§5.3)
  revisit_when: "..."             # or null
  signals: [ ... ]
  owner: devon                    # registry agent id, or null when required=false
```

### 3.13 Applicable standards — open mapping (decomposition-readiness)
```yaml
applicable_standards:             # standard-name → version string; a Phase-3 work unit inherits this
  project: "1.0"                  # the ONLY universally-required key
```
An **open mapping**, not a fixed triple. `project` is always required; a software package adds
`code`/`security`, a listing-launch package might add none (or a domain standard). Which additional standards
are *mandatory* is a **profile** decision (WS-2.2). `validate`: keys are non-empty strings, values are
strings; `code`/`security`/etc. are optional here.

### 3.14 (reserved) action grants
`requires_approval` names capabilities that need a **grant** before an agent may use them. The *granting
machinery* is Phase-3 (change-manager territory) — but the schema reserves where a grant is recorded:
`lineage.yaml.grants[]` (§9), empty in WS-2.1. This keeps "authorized to do X?" mechanically answerable later
without a schema change now.

---

## 4. Hashing and the revision model

### 4.1 Canonical intent core
`intent_core` = the parsed `package.yaml` mapping **minus the single key `status`**. The hash is
`package_hash = sha256_hex( JCS( intent_core ) )`, where **JCS** = RFC 8785 (recursively sort keys, no
insignificant whitespace, UTF-8, canonical scalar forms). `lineage.yaml` never contributes. `hash` is a
**pure, read-only** command.

### 4.2 Revisions and supersession (resolves the lifecycle collision)
- `revision` starts at 1. `lineage.yaml.revisions[]` records each revision's snapshotted hash + author + time.
- **When the hash is snapshotted:** at package creation (revision 1), and re-snapshotted on every
  `→ ready_for_review` transition (capturing accumulated draft edits — this is *what Devon reviews and
  approves*), and on `revise`. In `draft`/`needs_clarification`, `package.yaml` may be freely edited and the
  snapshot is intentionally stale; the drift check (below) does not apply there.
- **Material intent edit** = the live intent-core hash ≠ the current revision's snapshotted hash.
- **`revise`** is a *distinct lineage operation*, recorded as `{kind: revision}` and **exempt from the
  legal-transition-path check**. It is legal only from the **pre-execution** states
  {`draft`, `needs_clarification`, `ready_for_review`, `rejected`, `approved`}. It increments `revision`,
  snapshots the new hash, and sets `status: draft`. Revising from `approved` leaves the prior approval in
  history bound to its old revision/hash; the new revision is unapproved and must be re-approved to advance.
- **From `executable` onward** (execution has begun) intent is locked: a material change is a **supersession**,
  not a revise. `supersede` transitions the current package to `superseded` and requires a *new* package whose
  `supersedes:` points back. `revise` refuses from these states with a message pointing to `supersede`.
- **Drift enforcement** (`validate` check H): in the **drift-locked states**
  {`ready_for_review`, `approved`, `executable`, `in_execution`, `verification`, `completed`,
  `follow_up_due`, `blocked`, `rejected`} the live hash **must** equal the current revision's snapshotted
  hash; otherwise a hard error — worded "run `revise`" in the pre-execution set and "materially changed after
  execution began — create a superseding package" in the execution set. `draft`/`needs_clarification` and the
  terminal states {`closed`, `cancelled`, `failed`, `superseded`} are not drift-checked. `revise`/`supersede`
  themselves skip the drift check (they exist to resolve it).

### 4.3 Strict YAML typing (hash determinism)
`validate` check J enforces, and the hasher assumes:
- `yaml.safe_load` configured so **timestamps/dates are never auto-parsed** to `datetime`/`date` (custom
  resolver or a post-load type check that rejects them). `created_at` and all time fields are **quoted
  strings** matching an ISO-8601 regex.
- **No floats** anywhere: every scalar is `str`, `int`, `bool`, or `null`. A YAML float (`1.0`, `2.5`) is a
  hard error ("quote it"). This kills the `1.0`-vs-`"1.0"` and `1.10→1.1` hash divergences; version pins are
  strings by construction.
- **Single document only** — a multi-document YAML stream is rejected.
- **All documented keys present** (nullable) so JCS never distinguishes absent from `null`.
These rules make `sha256(JCS(intent_core))` reproducible byte-for-byte by any independent consumer.

### 4.4 Mechanical approval verification
`verify-approval <path>` (current revision only — historical revisions aren't on disk under D-Q4) succeeds
**iff both**: (1) `lineage.approvals[]` has an entry whose `approved_hash` == the recomputed intent hash with
a `human-operator-v1` approver (normally `devon`); **and** (2) the factory-events chain contains a
`package.approved` event carrying the same `approved_hash` + `revision`, and `factory_events verify` passes.
The chain is authoritative (tamper-evident); the ledger is the convenience mirror. A `--ledger-only` flag
(tests / chain-unreachable environments) checks (1) only and prints a loud "UNVERIFIED CHAIN" warning; the
default **fails closed** if the chain can't be consulted. This is the Phase-3 orchestrator's gate.

---

## 5. Lifecycle

### 5.1 States (companion §4.2)
Primary: `draft → needs_clarification → ready_for_review → approved → executable → in_execution →
verification → completed → follow_up_due → closed`. Additional: `rejected | cancelled | blocked | superseded
| failed`.

### 5.2 Legal-transition map (illegal transition = hard error)
| From | Legal → |
|------|---------|
| `draft` | needs_clarification, ready_for_review, cancelled |
| `needs_clarification` | draft, ready_for_review, cancelled |
| `ready_for_review` | approved, rejected, needs_clarification, cancelled |
| `approved` | executable, superseded, cancelled |
| `executable` | in_execution, blocked, superseded, cancelled |
| `in_execution` | verification, blocked, failed, superseded, cancelled |
| `verification` | completed, in_execution, failed, blocked, superseded |
| `completed` | follow_up_due, closed |
| `follow_up_due` | closed |
| `blocked` | executable, in_execution, cancelled |
| `rejected` | draft |
| `closed`, `cancelled`, `failed`, `superseded` | *(terminal)* |

The map is data (a dict in the state-machine module) so WS-2.2/Phase-3 read it, not re-derive it. `revise`
(§4.2) is **not** in this map — it is a revision operation that sets `status: draft` as a side effect.

### 5.3 follow-up enforcement
If `follow_up.required` is true, `completed → closed` is **illegal** (must route via `follow_up_due`);
`validate`/`transition` enforce it.

### 5.4 Readiness decidability (makes the §1 "ready/blocked/not-authorized without improvising" claim true)
A Phase-3 orchestrator decides, from a validated package + its lineage alone:
- **not authorized** — the action it wants is not in `authority.allowed` (default-deny, §3.7), or is in
  `requires_approval` with no matching `lineage.grants[]` entry (§3.14/§9).
- **blocked** — any `predecessor_packages[]` entry's package is **not** in {`completed`, `closed`} at the
  pinned `revision` (a predecessor revised past its pin ⇒ still blocked, now detectably), **or** any entry in
  `external_decisions` / `required_people_systems` / `blocking_conditions` is non-empty and has not been
  cleared by an explicit human `blocked → executable` transition recorded in lineage.
- **ready** — approved (revision matches a `verify-approval` pass), not blocked, authorized for its next
  action. `executable → in_execution` is permitted only when not blocked.

WS-2.1 encodes these as documented rules + the data they need (pinned predecessors, default-deny authority,
reserved grants); the *orchestrator that acts on them* is Phase-3.

---

## 6. `validate` cross-checks (beyond structural schema)
After structural validation, these semantic checks, each with an actionable, file-and-field-scoped message:
- **check ID** — `package_id` == directory name.
- **check S** — `package.yaml.status` == `lineage.yaml.current_state`.
- **check H** — drift rule (§4.2) over the drift-locked state set.
- **check A** — every `acceptance[]` has unique well-formed `id`, enum `evidence_type`, non-empty `evidence`,
  and an `approver` in one of the three legal forms (§3.6), with `external:` only for
  `external_attestation`/`human_review`.
- **check TR** — every `sources[]` declares `trust`.
- **check T** — authority terms in-vocabulary, no term in >1 list (else default-deny), unknown-term message
  (degraded-to-warning if registry unavailable).
- **check J** — strict YAML typing (§4.3): no floats, no datetimes, single doc, all keys present.
- **check K** — no unknown keys at any level except `profile`/`profile_fields`.
- **check O** — `scope.open_questions` is `[]` (checked as an error by `approve`; a warning by `validate` in
  earlier states).
- **check L** — `lineage.yaml` consistency: monotonic revisions; every transition is either a legal edge
  (§5.2) or a `kind: revision`/`kind: supersession` entry; approvals/grants reference existing revisions;
  `current_state` reachable.

`validate --all` validates every `packages/*/` directory and is the CI gate. Exit non-zero on any error.

---

## 7. CLI surface
Invocation (zero-install): `PYTHONPATH=src python3 -m intent_packages <cmd>`.

| Command | Behavior | Emits? |
|---------|----------|--------|
| `validate <path> \| --all` | §6 checks; actionable errors; non-zero exit on failure. | no (pure) |
| `hash <path>` | Print `sha256(JCS(intent_core))`. | no (pure) |
| `transition <path> --to <state>` | Perform a legal transition (§5.2); append to lineage; update `status`. Illegal → hard error. | yes (best-effort) |
| `approve <path>` | Specialized `ready_for_review→approved`. Records `{revision, approved_hash, approver, approved_at, commit}` in `lineage.approvals[]`; sets status `approved`. Approver defaults to `devon` (`--approver <id>`) and **must resolve to a `human-operator-v1` registry id** else hard error. Refuses if `scope.open_questions` non-empty. | yes (`package.approved`, **fatal on failure**) |
| `revise <path>` | Register a new revision (§4.2); legal only pre-execution; sets status `draft`. | yes (`package.revised`) |
| `supersede <path> --by <new_package_id>` | Transition current → `superseded` with a back-reference; for post-execution material change. | yes (`package.superseded`) |
| `verify-approval <path> [--ledger-only]` | §4.4 dual check (ledger + chain); fails closed. | no (pure) |

`show`/`list` omitted (YAGNI; `validate`/`cat`/git suffice for MVP).

**Approval identity:** the **emitting actor** is `FACTORY_AGENT_ID` (`claude-code-interactive` in an
interactive session — the channel); the **approver** recorded in ledger + event payload is the registry id
`devon` (the human root of authority). No new registry vocabulary is introduced.

---

## 8. Factory-event emission
- **Seam:** WS-1.1 `factory_events` (hash-chained JSONL `~/.factory/events.jsonl` + Postgres projection).
  intent-packages is a **separate repo**, so the CLI emits by shelling out to the `factory_events` CLI:
  `... -m factory_events emit --actor $FACTORY_AGENT_ID --action package.<approved|transitioned|revised|superseded>
  --ref <package_id> --result success --evidence-json '{"from":...,"to":...,"revision":N,"approved_hash":...,"commit":...}'`.
- **Actor gate:** `claude-code-interactive`/`devon`/`factory-runner`/… are registered, so emits are accepted;
  an unregistered actor is (correctly) rejected by the gate.
- **Emitter abstraction:** the CLI depends on an injectable `Emitter`. Default `FactoryEventsEmitter` shells
  out (locating security-standards via `SECURITY_STANDARDS_DIR`); `NullEmitter` serves `--no-emit`/tests.
  `validate`/`hash`/`verify-approval` never touch it.
- **Failure behavior & recovery (not "transactional"):** two file writes + a subprocess can't be atomic, so
  we define recovery instead. For **`approve`**: emit the `package.approved` event **first**, then write the
  lineage approval carrying the returned `event_id`. If the emit fails → abort, write nothing (no unaudited
  approval). If the process dies *after* the emit but *before* the lineage write → the chain has the
  approval, lineage doesn't; `approve` is **idempotent** — on re-run it finds the existing chained approval
  for the current hash and only completes the lineage write (no double-emit). `verify-approval` treats the
  chain as authoritative, so this torn state still verifies. For non-approval transitions: lineage is written
  first (authoritative for state), then best-effort emit; on emit failure lineage records `event_id: null`
  and an `emit_error`. `--no-emit` (refused by `approve`) records `event_id: null` for tests/dry-runs.

---

## 9. `lineage.yaml`
```yaml
package_id: ws-2.2-domain-profiles
current_state: approved
revisions:
  - revision: 1
    hash: "<sha256 hex>"
    created_at: "2026-07-03T00:00:00Z"
    author: claude-code-interactive
transitions:
  - kind: transition            # transition | revision | supersession
    from: draft
    to: ready_for_review
    at: "2026-07-03T00:05:00Z"
    actor: claude-code-interactive
    event_id: "<id or null>"
approvals:
  - revision: 1
    approved_hash: "<sha256 hex — must equal revisions[revision-1].hash>"
    approver: devon
    approved_at: "2026-07-03T00:10:00Z"
    commit: "<git sha of the -s commit>"
    event_id: "<factory event_id>"
grants: []                      # reserved (§3.14) — action-grants are Phase-3; empty in WS-2.1
```

---

## 10. Repo / foundation conformance
Matches the WS-1.3 `foundation_contract` frontmatter shape:
```yaml
foundation: true
foundation_contract: 1
applicable_standards:
  project: '1.0'
  security: '1.0'
  code: '1.0'
required_checks:
- id: intent-package-validate
  executor: github-actions:validate.yml
```
- **One honest CI check** (`.github/workflows/validate.yml`): install deps (dev extra, `pip install -e ".[dev]"`
  like `security-scan.yml`), run `PYTHONPATH=src python3 -m intent_packages validate --all`, then `pytest`.
  Because of the estate `uv sync`-no-extras / zero-tests invariant, the workflow **asserts a non-zero
  collected-tests count** so the suite can't silently run nothing, and runs `ruff check` opportunistically.
- `STANDARD_VERSION` = `1.0` (repo-root; the standard this repo participates in; distinct from the envelope's
  `schema_version: 1`).
- **Full code-standards onboarding deferred (D-Q5b):** vendored `quality.yml` + `Makefile check` + pyright
  are NOT added now (they'd need a real `make check` target or they lie — the documented estate gap). `pyproject.toml`
  still carries `[tool.ruff]`, `pythonpath=["src"]`, `package-dir={"" = "src"}`, `requires-python=">=3.12"`.
- **Security-scan** is portfolio-wide via the global session Stop hook (`bws-scan-gate.sh`) + weekly
  `com.devon.security-scan` launchagent — not a repo-local CI check here. No BWS tokens in tracked files
  (write-guard); end sessions with the shell at the repo root (scan-gate cwd quirk).

## 11. ADAS harvest folded in
Typed core + `required` fields, forward-compatible via `profile`/`profile_fields` (proto-migration
`additionalProperties:true` + required core); "LLM writes, deterministic gates decide / LLM output untrusted
until it passes gates" realized as `sources[].trust` + the deterministic `validate` gate; provenance `kind`
generalized to `sources[].trust`; budgets → optional `authority.budgets`; explicit lifecycle enum +
re-validate-after-transition. **Not** carried over: migration passes, stack detection, npm gates.
proto-migration has **no** content-hashing — WS-2.1's immutable/hashable requirement is genuinely new.

## 12. Verification / dogfood plan
1. Author `packages/ws-2.2-domain-profiles/` (the WS-2.2 workstream itself) as the first real package.
2. `validate` clean; `hash` it (record digest).
3. Show a **deliberately broken** copy failing `validate` with a specific error (e.g. an AC missing
   `approver`, an authority term not in vocabulary, or an unquoted float).
4. `transition` Draft → Ready for Review (hash re-snapshotted).
5. `approve` as Devon; confirm `lineage.approvals[].approved_hash` == the recorded revision hash and the
   `package.approved` event landed (`factory_events verify`).
6. `verify-approval` returns success (dual ledger+chain check).

## 13. Exit criteria (WS-2.1's slice of companion §4)
- [ ] Versioned universal schema (`schema_version: 1`); a **reserved extension point** (`profile_fields`,
      exempt from unknown-key rejection) exists for profiles — full "extends without breaking" is
      *demonstrable* only in WS-2.2.
- [ ] Packages validate mechanically with actionable errors; sources classified trusted/untrusted; every AC
      has id + evidence_type + evidence + approver.
- [ ] Revisions immutable and hashable; `hash` deterministic and documented (JCS + strict typing, exclude
      `status`).
- [ ] Approval binds to an exact revision (Devon-only) and is mechanically verifiable via ledger **and**
      tamper-evident chain (`verify-approval`).
- [ ] Authority boundaries explicit, default-deny, in the registry vocabulary.
- [ ] Lifecycle states + legal transitions + revise/supersede implemented and enforced (illegal = hard error).
- [ ] Readiness/authorization decidable from package+lineage (§5.4) — the "without improvising" criterion.
- [ ] The dogfood package (WS-2.2) exists and passed the full CLI path.
- [ ] Repo standards-conformant: PROJECT.md + foundation_contract, security-clean, CI validating all packages.

## 14. Open items deferred to later workstreams
- **Profile field location + validation** — WS-2.2 (this spec reserves `profile`/`profile_fields`).
- **Non-software authority vocabulary** — the listing-launch pilot (WS-2.4) needs registry additions before
  it can express its authority; candidate terms to propose: `spend_money`, `calendar_write`,
  `third_party_contact`, `data_delete`, `external_system_write`. File as small registry PRs when WS-2.4 starts.
- **Action-grant granting machinery** — Phase-3 change-manager territory; schema reserves `lineage.grants[]`.
- **Cryptographic commit signing** as approval hardening — future.
- **A dedicated `intent-package-cli` registry actor** — optional; MVP reuses `claude-code-interactive`.

## 15. Test surface (for the plan)
Deterministic-hash tests (reformatting/comment/key-order invariance; float/datetime/multi-doc rejection);
JCS golden vectors; transition-map legality (every legal edge + a sampling of illegal ones hard-error);
revise/supersede state rules; drift detection across the drift-locked set; validate cross-checks A/T/J/H/O/L
each with a passing and a failing fixture; approver-form matrix (policy / registry id / external + evidence
guard); verify-approval dual-check with a stubbed emitter + a forged-ledger negative; readiness rules (§5.4).
All CLI tests drive `cli.main([...])` and assert on `capsys` + exit code (agent_registry pattern); a
`NullEmitter`/stub isolates tests from the events backend.

## 16. Design review dispositions (Fable-5 red-team, 2026-07-03)
Red-team ran before implementation against both golden paths (a software feature and a real-estate
listing-launch) + the immutability semantics. 21 findings; dispositions:
- **Accepted & folded in:** external approver form (§3.6); open `applicable_standards` mapping (§3.13);
  authority default-deny + no-double-list (§3.7); `revise`/`supersede` split resolving the transition-map
  collision (§4.2/§5.2); strict YAML typing for hash determinism (§4.3); `verify-approval` dual ledger+chain
  check (§4.4); predecessor revision-pinning + readiness rules (§3.9/§5.4); reserved `lineage.grants[]`
  (§3.14/§9); merge per-criterion evidence onto acceptance items (§3.6/§3.11); follow-up + open-questions
  enforcement (§5.3/§6); `superseded` reachability in the map (§5.2); best-effort-vs-fatal emit + crash
  recovery (§8); non-software vocabulary gap named (§14); honesty-worded exit criteria (§13).
- **Accepted as documented friction, not changed:** `owner` stays in the hash (ownership transfer =
  revise/supersede) — §2 refinements.
- **Simplified (YAGNI):** dropped `verify-approval --revision N` (only current revision on disk); folded the
  evidence-per-criterion parallel list into `acceptance[]`.
