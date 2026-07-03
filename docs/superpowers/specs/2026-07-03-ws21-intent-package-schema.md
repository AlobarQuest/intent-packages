# WS-2.1 — Universal Intent-Package Schema, Lifecycle, and validate/hash/approve CLI

**Status:** Design approved 2026-07-03 (Devon). Ready for implementation planning.
**Workstream:** Software Factory Phase 2, WS-2.1 (opening workstream).
**Repo:** `~/Projects/intent-packages` (`AlobarQuest/intent-packages`, default branch `main`).
**Authoritative source:** companion §4 (`~/docs/software-delivery-system/2026-06-30-foundation-intent-orchestration-architecture.md`), master plan Phase 2 + D2 + D3.

---

## 1. Goal and scope

An **intent package** is a domain-neutral, versioned, immutable-when-approved description of a desired
outcome: what should become true, within what scope, drawing on which sources (classified
trusted-instruction vs untrusted-data), under what constraints, with acceptance criteria that each
carry evidence requirements and an approver, an explicit authority envelope, and a lifecycle. Packages
are **YAML in git**; a deterministic **CLI** validates, hashes, and records approvals. Approval binds
to an immutable revision whose sha256 is recorded; an agent later reading a package can determine
`ready` / `blocked` / `not authorized` without improvising.

### In scope (WS-2.1)
1. The **universal intent-package schema** (v1) — the envelope every domain profile will extend.
2. The **lifecycle** — states + the legal-transition map, enforced by the CLI.
3. The **CLI** — `validate`, `hash`, `transition`, `approve`, `revise`, `verify-approval` (Python 3.12+,
   zero-install `PYTHONPATH` module, like `agent_registry`).
4. Repo bootstrap: `foundation: true`, PROJECT.md + `foundation_contract`, STANDARD_VERSION pins, CI
   that validates every package on every PR.
5. One **dogfood package** — the WS-2.2 workstream authored as the first real package, driven through
   the full CLI path.

### Explicitly OUT of scope (later workstreams — do not build)
- Domain **profiles** (software-delivery, infrastructure-change, listing-launch) — **WS-2.2**.
- The **intent-authoring skill** (conversational intake) — **WS-2.3**.
- The **pilots** — **WS-2.4**.
- Any **orchestrator / work-unit machinery** (claims, leases, runner) — **Phase 3**.
- Any **package database** — YAGNI; files + git until they hurt (master plan Part 6).
- **Retiring the ADAS repos** (`shaper`, `proto-migration`) — harvest only now; retirement waits for
  the Phase-4 runner harvest (D3), done later via the retire-project skill with Devon.

The schema must nonetheless be **decomposition-ready** (companion §4.3): the universal envelope carries
the fields a Phase-3 work unit will inherit — package identity + revision, applicable standards,
authority limits, context, evidence requirements — even though work-unit machinery is not built here.

---

## 2. Design decisions (settled with Devon 2026-07-03)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D-Q1 | Revision / immutability model | **Hash excludes `status`; approval binds to the immutable intent core.** Lifecycle advances without changing the hash. Material intent edit → new `revision` + renewed approval. | Preserves the "approved hash == executing hash" invariant the Phase-3 orchestrator needs. Advancing Approved→Executable→In Execution must not invalidate an approval. |
| D-Q2a | Canonicalization | **`sha256(RFC-8785 JCS(intent_core))`** — canonical JSON, not raw bytes. | Raw bytes churn on reformatting/comments/key-order. JSON canonicalization is well-specified; YAML's is not. The orchestrator can recompute independently. |
| D-Q2b | Approval proof | **`git commit -s` + append-only approvals ledger entry + `package.approved` factory event.** No cryptographic (GPG/SSH) commit signature required for MVP. | Mechanical verifiability comes from recomputing the intent hash and matching the ledger's `approved_hash` by `devon`, plus the audit event. Crypto signing is documented future hardening. |
| D-Q3 | Event emission scope | **Every transition the CLI performs emits a `factory-event/v1`.** `approve` carries approval evidence. | Cheap; complete lifecycle audit trail in the hash-chained store from day one. |
| D-Q4 | File layout | **Directory per package:** `packages/<id>/package.yaml` + `packages/<id>/lineage.yaml`. | Hashable (canonical over `package.yaml` intent core), good git-diff review ergonomics, approval provenance without git archaeology, room for WS-2.4 pilots side by side. |
| D-Q5a | Foundation status | **`foundation: true`.** | Intent-packages gates everything the factory does. |
| D-Q5b | Code-standards onboarding | **Lightweight now** (foundation_contract + STANDARD_VERSION pins + three real `required_checks`); defer heavier tooling until Phase 2 stabilizes. | Standards-conformant on day one without over-investing before the schema settles. |

### Refinements carried in from self-review
- **Two versions, disambiguated:** `schema_version` (envelope format, integer, `1`) vs `revision` (this
  package's immutable intent revision, monotonic integer). The hash binds to a `revision`.
- **Minimal exclusion set:** the canonical hash excludes **exactly one field — `status`**. Every other
  field in `package.yaml` (including `created_at`/`created_by`/`owner`/`supersedes`) is immutable intent.
  All timestamps, transition authorship, and approvals live in `lineage.yaml` (a separate file, never in
  the hash). Trivially reproducible.
- **JSON-round-trippable constraint:** package YAML must be JSON-representable (string keys, JSON scalars)
  so JCS applies unambiguously. `validate` enforces this.

---

## 3. Universal envelope (`package.yaml`, schema_version 1)

Field-by-field. Types are YAML/JSON. `validate` enforces required fields, types, enums, and the
cross-checks in §6. The envelope is **closed** — unknown top-level keys are an error — **except** the
reserved forward-extension keys `profile` (string) and `profile_fields` (mapping, opaque to universal
validation, validated by a profile validator in WS-2.2). This catches typos now while letting profiles
extend later without breaking v1.

### 3.1 Identity
```yaml
schema_version: 1                 # envelope format version (integer)
package_id: ws-2.2-domain-profiles  # kebab-case slug, unique, == directory name
title: "WS-2.2 — Domain profiles for intent packages"
revision: 1                       # monotonic intent revision (integer, starts at 1)
status: draft                     # EXCLUDED FROM HASH. See §4/§5.
created_by: claude-code-interactive   # registry agent id
owner: devon                          # registry agent id
created_at: 2026-07-03T00:00:00Z      # ISO-8601 UTC, set once, immutable
supersedes: null                      # package_id this replaces, or null
```

### 3.2 Desired outcome (companion §4.1 "Desired outcome")
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
  included: [ ... ]        # list of strings
  excluded: [ ... ]
  non_goals: [ ... ]
  assumptions: [ ... ]
  open_questions: [ ... ]  # non-empty here is a signal for the Needs-Clarification state
```

### 3.4 Sources and context — trust classification is mandatory
```yaml
sources:
  - location: "companion §4"          # where the source lives
    authority_level: authoritative    # authoritative | supporting | reference
    required_version: "2026-06-30"    # or null
    trust: trusted_instruction        # trusted_instruction | untrusted_data  (REQUIRED)
    sensitivity: internal             # public | internal | confidential | secret
```
`trust` is the rule-#3 containment hook: untrusted_data can inform a package but never carries authority
to act. Every source **must** declare `trust`; `validate` errors if any source omits it.

### 3.5 Constraints
```yaml
constraints:
  time_budget: "..."          # free text or null, per field
  technology: "..."
  policy_legal: "..."
  privacy_security: "..."
  compatibility: "..."
  quality_accessibility: "..."
  operational: "..."
```

### 3.6 Acceptance criteria — id + evidence + approver, each required
```yaml
acceptance:
  - id: AC-001                    # unique within the package (regex ^AC-[0-9]{3,}$)
    condition: "..."             # observable statement
    evidence_type: automated_test # automated_test | automated_check | human_review
                                  # | external_attestation | observation
    approver: policy              # 'policy' (deterministic gate, no human) OR a registry agent id
```
`validate` errors if: an id is duplicated or malformed; `evidence_type` is outside the enum; `approver`
is neither `policy` nor a registered agent id.

### 3.7 Authority envelope — grounded in the registry capability vocabulary
```yaml
authority:
  allowed: [ repository_read, repository_write, test_execution ]   # capability terms
  requires_approval: [ merge_to_main, outward_publish ]            # capability terms needing a grant
  prohibited: [ secret_write, infra_mutation ]                     # capability terms
  budgets:                        # optional (ADAS harvest); null-ok
    max_attempts: null
    max_llm_calls: null
```
Terms are drawn from `security-standards/registry/capabilities.yaml` (17-term vocabulary:
`repository_read, repository_write, test_execution, pr_open, merge_to_main, event_emit, infra_mutation,
drift_detection, change_filing, change_approval, secret_read, secret_write, credential_create,
credential_revoke, email_send, outward_publish, task_claim`). `validate` **errors** on a term not in the
vocabulary, with a message stating that an unknown term needs a registry-addition PR (kickoff
ground-truth #1 — reference registry terms, never fork them). The registry is located via
`SECURITY_STANDARDS_DIR` (default: sibling `~/Projects/security-standards`); if unavailable, `validate`
degrades that specific check to a warning and says so (so the CLI runs in CI/other checkouts).

### 3.8 Deliverables and handoff
```yaml
deliverables:
  artifacts: [ ... ]                 # required artifacts + formats
  destination: "..."
  recipient: "..."
  definition_of_done: "..."
  operator_responsibilities: [ ... ] # what remains a human/operator job
```

### 3.9 Dependencies
```yaml
dependencies:
  predecessor_packages: [ ... ]   # package_ids
  external_decisions: [ ... ]
  required_people_systems: [ ... ]
  required_capabilities: [ ... ]  # capability terms
  blocking_conditions: [ ... ]
```

### 3.10 Risk and failure handling
```yaml
risk:
  failure_modes: [ ... ]
  max_impact: "..."
  stop_conditions: [ ... ]
  rollback: "..."
  escalation_target: devon        # registry agent id or free text
```

### 3.11 Verification plan
```yaml
verification:
  evidence_per_criterion:         # maps every AC id to its required evidence
    - criterion: AC-001
      evidence: "pytest tests/test_hash.py::test_deterministic passes"
  independent_review: [ ... ]     # what needs an independent reviewer
  non_mechanical: [ ... ]         # criteria that cannot be verified mechanically
```
`validate` errors if any `acceptance[].id` lacks a matching `verification.evidence_per_criterion` entry.

### 3.12 Follow-up
```yaml
follow_up:
  required: false                 # bool
  revisit_when: "..."             # or null
  signals: [ ... ]
  owner: devon                    # registry agent id, or null when required=false
```

### 3.13 Applicable standards — decomposition-readiness (companion §4.3)
```yaml
applicable_standards:             # version pins a Phase-3 work unit inherits
  code: "1.0"
  security: "1.0"
  project: "1.0"
```
This, together with identity+revision, the authority envelope, sources/context, and the per-AC evidence
requirements, is the complete set a work unit inherits (§4.3). Work-unit-specific fields
(concrete-outcome, claim-state, retry) are **not** modeled here — Phase 3.

---

## 4. Hashing and the revision model

### 4.1 Canonical intent core
`intent_core` = the parsed `package.yaml` mapping **minus the single key `status`**. The hash is:
```
package_hash = sha256_hex( JCS( intent_core ) )
```
- **JCS** = RFC 8785 JSON Canonicalization Scheme: recursively sort object keys, no insignificant
  whitespace, UTF-8, canonical number/string forms. Deterministic and reproducible by any consumer.
- `lineage.yaml` is a **separate file** and never contributes to the hash.
- `hash` is a **pure, read-only** command: it prints the hex digest and emits nothing.

### 4.2 Revisions
- `revision` starts at 1. The **current** revision's authoritative hash is recorded in `lineage.yaml`
  `revisions[]`.
- A **material intent edit** = any change to `intent_core` (i.e. the computed hash no longer matches the
  latest recorded revision hash). `validate` detects drift: if the computed hash ≠ the latest
  `revisions[].hash` **and** `status` ≥ `ready_for_review`, it is a hard error instructing the author to
  run `revise`.
- `revise` appends a new `revisions[]` entry (`revision` incremented, new hash, author, timestamp),
  resets `status` to `draft`, and **voids** any prior approval for the superseded revision (approvals are
  revision-scoped; an approval only ever binds to the exact `approved_hash`).

### 4.3 Mechanical approval verification
`verify-approval <path> [--revision N]` recomputes the intent-core hash for revision N (default: current)
and returns success **iff** `lineage.yaml` `approvals[]` contains an entry with a matching
`approved_hash` and `approver: devon`. This is the Phase-3 orchestrator's gate and directly satisfies the
"approval binds to an exact revision, mechanically verifiable after the fact" exit criterion.

---

## 5. Lifecycle: states and legal transitions

### 5.1 States (companion §4.2)
Primary path: `draft → needs_clarification → ready_for_review → approved → executable → in_execution →
verification → completed → follow_up_due → closed`.
Additional outcomes: `rejected | cancelled | blocked | superseded | failed`.

### 5.2 Legal-transition map (illegal transition = hard error)
| From | Legal → |
|------|---------|
| `draft` | needs_clarification, ready_for_review, cancelled |
| `needs_clarification` | draft, ready_for_review, cancelled |
| `ready_for_review` | approved, rejected, needs_clarification, cancelled |
| `approved` | executable, superseded, cancelled |
| `executable` | in_execution, blocked, superseded, cancelled |
| `in_execution` | verification, blocked, failed, cancelled |
| `verification` | completed, in_execution, failed, blocked |
| `completed` | follow_up_due, closed |
| `follow_up_due` | closed |
| `blocked` | executable, in_execution, cancelled |
| `rejected` | draft |
| `closed`, `cancelled`, `failed`, `superseded` | *(terminal — no outgoing)* |

`superseded` is also reachable from `approved`/`executable`/`in_execution`/`verification` when a new
revision or package replaces this one (already covered above). The map is data (a dict in the state-machine
module), so WS-2.2/Phase-3 can read it, not re-derive it.

### 5.3 status field vs lineage
`package.yaml.status` is a **convenience mirror**; `lineage.yaml.current_state` is authoritative.
`validate` errors if they disagree. `transition`/`approve`/`revise` update both atomically.

---

## 6. `validate` cross-checks (beyond structural schema)
`validate` runs structural JSON-Schema-style validation, then these semantic checks (all producing
actionable, file-and-field-scoped error messages):
1. `package_id` == directory name.
2. `package.yaml.status` == `lineage.yaml.current_state`.
3. Computed intent hash consistency with `lineage.yaml.revisions[]` (drift rule, §4.2).
4. Every `acceptance[]` has unique well-formed `id`, enum `evidence_type`, and `approver` ∈
   {`policy`} ∪ registered agent ids.
5. Every `sources[]` declares `trust`.
6. Every `authority.*` term ∈ capability vocabulary (or degraded-to-warning if registry unavailable).
7. Every `acceptance[].id` has a matching `verification.evidence_per_criterion[].criterion`.
8. YAML is JSON-round-trippable.
9. No unknown top-level keys except `profile` / `profile_fields`.
10. `lineage.yaml` internal consistency: monotonic revisions, transitions form a legal path, approvals
    reference existing revisions.

`validate --all` validates every `packages/*/` directory and is the CI gate. Exit non-zero on any error.

---

## 7. CLI surface

Invocation (zero-install, like `agent_registry`): `PYTHONPATH=src python3 -m intent_packages <cmd>`.

| Command | Behavior | Emits? |
|---------|----------|--------|
| `validate <path> \| --all` | §6 checks; actionable errors; exit non-zero on failure. | no (pure) |
| `hash <path>` | Print `sha256(JCS(intent_core))`. | no (pure) |
| `transition <path> --to <state>` | Perform a legal transition; append to lineage; update `status`. Illegal transition → hard error. | yes |
| `approve <path>` | Specialized `ready_for_review→approved`. Records `{revision, approved_hash, approver, approved_at, commit}` in `lineage.approvals[]`; sets status `approved`. Approver defaults to `devon` (override `--approver <id>`) and **must resolve to a `human-operator-v1` registry id** (approval is a human act) else hard error. | yes (`package.approved`) |
| `revise <path>` | Register a new revision after an intent edit (§4.2). | yes (`package.revised`) |
| `verify-approval <path> [--revision N]` | Mechanical check that revision N's hash matches a recorded `devon` approval; exit non-zero if not. | no (pure) |

`show`/`list` are deliberately omitted (YAGNI; `validate`/`cat`/git cover introspection for MVP).

### Approval identity note
`approve` is Devon's act. The **emitting actor** of the factory event is `FACTORY_AGENT_ID`
(`claude-code-interactive` in an interactive session), and the **approver** recorded in the ledger and
event payload is the registry id `devon`. `approve` requires the resolved approver to be `devon`; a
`--approver` override exists only to name the human explicitly and still must resolve to a
`human-operator-v1` registry id. (No new registry vocabulary is introduced.)

---

## 8. Factory-event emission

- **Seam:** WS-1.1 `factory_events` (hash-chained JSONL `~/.factory/events.jsonl` + Postgres projection).
  intent-packages is a **separate repo**, so the CLI emits by shelling out to the `factory_events` CLI:
  `PYTHONPATH=<sec-std>/src <venv>/python -m factory_events emit --actor $FACTORY_AGENT_ID
  --action package.<transitioned|approved|revised> --ref <package_id> --result success
  --evidence-json '{"from":...,"to":...,"revision":N,"approved_hash":...,"commit":...}'`.
- **Actor gate:** `claude-code-interactive` (and `devon`, `factory-runner`, etc.) are registered, so
  direct emits are accepted. Unregistered actor → the gate rejects (correct).
- **Emitter abstraction:** the CLI depends on an injectable `Emitter` interface. The default
  `FactoryEventsEmitter` shells out as above (locating security-standards via `SECURITY_STANDARDS_DIR`);
  a `NullEmitter` is used by `--no-emit` and by tests. `validate`/`hash`/`verify-approval` never touch it.
- **Failure behavior:** for `approve`, a failed emit is **fatal** (do not record an approval that isn't in
  the audit chain) — the ledger write and the event must both succeed or the command aborts and rolls
  back the lineage write. For non-approval `transition`/`revise`, a failed emit is a **warning** (the
  transition still records, with `event_id: null` and an `emit_error` note in lineage). `--no-emit`
  records transitions with `event_id: null` for tests/dry-runs and is refused by `approve`.

---

## 9. `lineage.yaml`
```yaml
package_id: ws-2.2-domain-profiles
current_state: approved
revisions:
  - revision: 1
    hash: "<sha256 hex>"
    created_at: 2026-07-03T00:00:00Z
    author: claude-code-interactive
transitions:
  - from: draft
    to: ready_for_review
    at: 2026-07-03T00:05:00Z
    actor: claude-code-interactive
    event_id: "<factory event_id or null>"
approvals:
  - revision: 1
    approved_hash: "<sha256 hex — must equal revisions[revision-1].hash>"
    approver: devon
    approved_at: 2026-07-03T00:10:00Z
    commit: "<git sha of the -s commit>"
    event_id: "<factory event_id>"
```

---

## 10. Repo / foundation conformance
Matches the WS-1.3 `foundation_contract` shape (verbatim frontmatter keys from the estate):
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
- **One honest CI check** (`.github/workflows/validate.yml`, executor `github-actions:validate.yml`):
  install deps (dev extra), run `PYTHONPATH=src python3 -m intent_packages validate --all`, then
  `pytest`. Because of the estate `uv sync`-no-extras / zero-tests invariant, the workflow installs the
  dev group explicitly (`pip install -e ".[dev]"`, matching `security-scan.yml`) and **asserts a non-zero
  collected-tests count** so the suite can't silently run nothing. This single check covers both "validate
  all packages" and "run the tests" — both real executors, no lie.
- `STANDARD_VERSION` = `1.0` (repo-root, matches the estate; the standard this repo participates in;
  distinct from the envelope's `schema_version: 1`).
- **Full code-standards onboarding deferred (D-Q5b):** the vendored portfolio `quality.yml` +
  `Makefile check` + pyright are NOT added now (that is the heavier onboarding to run once the schema
  stabilizes in Phase 2). `pyproject.toml` still carries `[tool.ruff]` config and `pythonpath=["src"]`,
  and `validate.yml` runs `ruff check` opportunistically.
- **Security-scan** is covered portfolio-wide by the global session Stop hook (`bws-scan-gate.sh`) + the
  weekly `com.devon.security-scan` launchagent — it is NOT a repo-local CI `required_check` here (this is
  not the security repo). The repo still must be secret-clean: no BWS tokens in tracked files
  (write-guard); session ends with the shell at the repo root (scan-gate cwd quirk).
- `pyproject.toml`: `dev = ["pytest>=7.0", "pyyaml>=6.0", ...]`, `package-dir = {"" = "src"}`,
  `pythonpath = ["src"]`, `requires-python = ">=3.12"` — mirrors the `agent_registry` zero-install pattern.

## 11. ADAS harvest folded in
- Typed core with `required` fields but forward-compatible via `profile`/`profile_fields`
  (proto-migration `additionalProperties:true` + required core).
- "LLM writes, deterministic gates decide / LLM output untrusted until it passes gates" — the stated
  thesis; realized as the `sources[].trust` classification and the deterministic `validate` gate.
- Provenance `kind` → generalized into `sources[].trust` (trusted_instruction | untrusted_data).
- Budgets (`max_attempts`/`max_llm_calls`) → optional `authority.budgets`.
- Explicit lifecycle enum + re-validate-after-transition (proto-migration `state.json.phase`).
- **Not** carried over: migration passes, stack detection, npm gates. proto-migration has **no**
  content-hashing — WS-2.1's immutable/hashable requirement is genuinely new.

## 12. Verification / dogfood plan
1. Author `packages/ws-2.2-domain-profiles/` (the WS-2.2 workstream itself) as the first real package.
2. `validate` it clean; `hash` it (record digest).
3. Show a **deliberately broken** copy failing `validate` with a useful, specific error (e.g. an
   acceptance criterion missing `approver`, or an authority term not in the vocabulary).
4. `transition` Draft → Ready for Review.
5. `approve` as Devon; confirm `lineage.approvals[].approved_hash` == the recorded `hash`, and that the
   `package.approved` factory event landed in the chain (`factory_events verify`).
6. `verify-approval` returns success for the approved revision.

## 13. Exit criteria (WS-2.1's slice of companion §4)
- [ ] Versioned universal schema exists (`schema_version: 1`); profiles extend via `profile_fields`
      without breaking v1.
- [ ] Packages validate mechanically with actionable errors; sources classified trusted/untrusted; every
      AC has id + evidence_type + approver.
- [ ] Revisions immutable and hashable; `hash` deterministic and documented (JCS, exclude `status`).
- [ ] Approval binds to an exact revision (Devon-only) and is mechanically verifiable
      (`verify-approval`).
- [ ] Authority boundaries explicit, in the WS-1.2 registry capability vocabulary.
- [ ] Lifecycle states + legal transitions implemented and enforced (illegal = hard error).
- [ ] The dogfood package (WS-2.2) exists and passed the full CLI path.
- [ ] Repo standards-conformant: PROJECT.md + foundation_contract, security scan clean, CI validating all
      packages.

## 14. Open items deferred to later workstreams
- Where profile-specific fields live and how they validate — **WS-2.2** (this spec reserves
  `profile`/`profile_fields`).
- Cryptographic commit signing as approval hardening — future, if desired.
- A dedicated `intent-package-cli` registry actor id — optional small registry PR later; MVP reuses
  `claude-code-interactive`.
