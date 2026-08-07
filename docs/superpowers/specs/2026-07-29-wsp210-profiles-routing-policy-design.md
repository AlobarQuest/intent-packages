# WS-P2.10 — Delivery Profiles + Model-Routing Policy: Design

Status: approved design (brainstormed with Devon 2026-07-29; four open questions + approach
resolved interactively). Wave 3 opener; program exit criterion #11 is this workstream's to close.
Owner repo: `intent-packages`. The orchestrator and factory-runner are untouched by design.

Sources of authority: Phase-2 plan WS-P2.10 bullet (`2026-07-09-program-phase2-post-mvp-plan.md`),
post-MVP recommendations C#4 and §11 (`2026-07-04-codex-post-mvp-recommendations.md` — the §11
seed table is the decided 2026-07-08 content), WS-P2.8 spec §14.2, the 2026-07-17
dependency-update spec + GAP-4 closeout (`2026-07-29-gap4-closeout-evidence.md`), and the
2026-07-29 handoff prompt. All in `~/docs/software-delivery-system/`.

## 1. Context corrections (verified against source before design)

The handoff was substantially faithful; six facts discovered during exploration shaped the design:

1. **The routing table's contents are already decided.** Post-MVP §11 carries the full seed:
   8 surface→model rows, the explicitly-no-LLM list, and the graduation rules. The policy file's
   initial content is transcription, not design.
2. **The dependency-update profile already exists in code** (`profiles/dependency_update.py`,
   PR #26) with the four fail-closed validations in `factory/validations.py` — GAP-4 ran through
   it. It is NOT in the domain-profile registry, and both profile modules export a name-colliding
   `PROFILES` dict. Three artifacts have drifted: the 07-17 spec (3-command uv envelope), the
   shipped code (2-command; `uv add` locks inline; per-site flags; multi-site `--frozen`
   strategy), and GAP-4's production proof. The shipped+proven shape wins.
3. **A software-service profile partly exists** — `software-delivery` is registered and used by
   10 real packages; `infrastructure-change` by 4.
4. **Phase 3 expects a `maintenance/emergency-remediation` profile** (WS-P3.2 authors against
   it), and WS-P2.13 needs the non-software profile to exist to prove criterion #1's fourth leg.
   Part 5 decision 4 (docs-only) is about *dispatch enablement* posture — a separate axis, still
   open, conditioned on guardrail evidence.
5. **The `automated_test` ban collides with existing machinery.** intent-packages' evidence enum
   is `{automated_test, automated_check, human_review, external_attestation, observation}` —
   `test` is not legal here — and the existing profiles' tag maps force `automated_test` onto
   10+ approved packages whose YAML cannot be edited (hash/lineage invalidation). Enforcement
   must be scoped to the new profiles.
6. **Per-unit model stamping is decoration end-to-end today.** No model/runtime field exists
   anywhere in this repo; the orchestrator's `ProposedUnitCommand` silently drops unknown keys
   (no `extra="forbid"`); dispatch sends factory-runner only `work_unit_id`; the runner's model
   is hardcoded in its workflow YAML. Any consumer must be honest about this.

## 2. Decisions (resolved with Devon, 2026-07-29)

| # | Question | Decision |
|---|----------|----------|
| Q1 | Routing policy consumption contract | **Layered**: (a) `factory decompose` reads the policy, fail-closed on a missing change-class row; (b) new `factory route` query command becomes the source for session-model / handoff "Suggested model" lines (Phase-2 plan Part 2b becomes seeded-from); (c) ship-time assertion that factory-runner's hardcoded workflow model equals the policy's runner-implementation row, recorded in closeout evidence. Continuous cross-repo enforcement deferred to the filed max_turns/envelope-alignment backlog item. |
| Q2 | Which profiles ship | **dependency-update (formalized) + maintenance-remediation + non-software-operational.** Existing software-delivery and infrastructure-change are folded into the framework unchanged. docs-only and the rest are named stubs with owners. |
| Q3 | follow_up tightening | **Optional-key walker support ships here; the cadence/recurrence field is deferred** until the orchestrator workstream that will read it exists — an unconsumed field is the `profile_fields.branch` decoration defect again. Phase-3 riders become a small additive change later. |
| Q4 | Validation surface | **Authoring-time only** (extend the existing check-P surface). Intake-side enforcement is a later, deliberate orchestrator workstream. |
| A | Structural approach | **`DeliveryProfile` frozen dataclass + separate versioned `routing-policy.toml`.** Profiles stay Python (repo idiom); routing rows change on graduation-edit cadence, profiles on engineering cadence. Rejected: per-profile declarative manifests (second schema system, splits profiles across files); one combined file (welds two edit cadences). |

## 3. The routing policy file

`routing-policy.toml` at the repo root. Versioned by git plus an explicit `version` integer
bumped on every content change. Header comment names it the sole source of model selection
(criterion #11), points at the 2026-07-08 seed decision, and transcribes the graduation editing
contract (demotions suggested by N clean runs; promotions manual and immediate, before more
retries; every change a versioned edit, never an inline override).

Sections:

- `version = 1`
- `[models]` — slug → API model id (`fable-5 = "claude-fable-5"`, `sonnet-5`, `opus-4-8`,
  `haiku-4-5`). A future family upgrade is a one-table edit.
- `[[surface]]` — the eight decided rows transcribed verbatim from post-MVP §11: `id` slug
  (`intent-authoring`, `decomposition-proposals`, `runner-implementation`, `local-heavy`,
  `judgment-ac-verification`, `guarded-infra-agent`, `lesson-proposals`, `high-volume-text`),
  `model` slug (dual-model rows like judgment-AC verification carry both), `where`, `rationale`,
  `decided = 2026-07-08`. `model` is a list of one or more slugs: dual-model rows
  (judgment-AC verification: `["fable-5", "opus-4-8"]`) list both and `factory route` prints
  all; the decomposition-proposals row's "(or Opus 4.8)" alternate stays in its rationale, with
  `fable-5` as the single listed model.
- `[no_llm]` — the explicitly-no-LLM list, restated so the file inherits it.
- `[change_class]` — the lookup `factory decompose` uses. One explicit row per
  factory-executable change-class. Seed: `dependency-update = "sonnet-5"` (surface row 3's
  default), `maintenance-remediation = "sonnet-5"` (derived from the same row's default — the
  one seed entry not literally in the 2026-07-08 table; the derivation is recorded in the row's
  rationale). **No implicit default:** a change-class absent from this table is a hard error.
  Consequence, deliberate: shipping a new factory-executable profile requires adding its routing
  row in the same change.

A graduation edit changes a row's `model`, updates its `decided` date, rewrites its `rationale`,
and bumps `version` — a small reviewable diff, audit trail in git.

## 4. The consumers

1. **`factory route`** — `factory route --surface <id>` | `--change-class <name>`. Prints slug,
   resolved API model id, and rationale. Exit 1 on unknown key or unparseable/invalid policy.
   Becomes the query point for session models and handoff "Suggested model" lines; the Phase-2
   plan's Part 2b table gets a one-line annotation that it is seeded from the policy file.
2. **`factory decompose`** — before assembling the proposal, resolves the profile's
   `change_class` against `[change_class]`; a missing row fails closed alongside the existing
   validations. The resolved routing is recorded in the proposal `rationale` string
   ("routing: sonnet-5 per routing-policy v1") — this is **advisory provenance, not
   enforcement**: the orchestrator drops unknown unit fields silently and nothing downstream
   reads a model today (context correction #6). Recording it in `rationale` is honest; stamping
   it as a unit field would be the `github.pr.create` defect class.
3. **Ship-time assertion** — closeout evidence includes a dated check that factory-runner's
   workflow-hardcoded model equals the policy's `runner-implementation` row.

Non-goals, named: continuous cross-repo model enforcement against factory-runner (deferred to
the filed max_turns/envelope-alignment backlog item); any orchestrator change; any per-unit
model field.

## 5. The profile framework

A frozen `DeliveryProfile` dataclass (in `profiles/base.py`) unifies the two currently
ungoverned kinds — domain profiles (validator + MapSpec + tag map) and the tooling profile
(`ToolingProfile` keyed by uv/pip/npm) — under the single registry in `profiles/__init__.py`:

```python
@dataclass(frozen=True)
class DeliveryProfile:
    name: str  # registry key; package.yaml `profile:` value
    change_class: str | None  # non-None ⇒ factory-executable ⇒ routing row required
    profile_fields_schema: MapSpec | None
    tag_to_evidence_type: Mapping[str, str]
    forbidden_evidence_types: frozenset[str]  # banked-constraint enforcement hook
    required_checks: tuple[str, ...]
    default_authority: AuthorityDefaults | None  # envelope template PARAMETERS: budgets,
    # capabilities, command-ordering rule.
    # Defaults, never grants.
    evidence_expectations: str  # prose contract, incl. budget honesty
    observation_window: str  # prose; machine field deferred with follow_up
    validate: Callable[[dict], list[str]] | None
    tooling: Mapping[str, ToolingProfile] | None  # dep-update's uv/pip/npm variants
```

`PROFILES: dict[str, DeliveryProfile]`. The two existing domain profiles are **wrapped, not
changed**: same MapSpecs, tag maps, and validators; `forbidden_evidence_types=frozenset()`. All
19 existing packages must validate byte-identically (explicit regression test, §8).
`dependency_update.py`'s module-level `PROFILES` dict is absorbed as the `tooling` attribute of
the dependency-update entry, ending the name collision; decompose reaches tooling variants
through the one registry.

Budget honesty (GAP-4 finding 4: declared `max_llm_calls: 4`, recorded 15): `AuthorityDefaults`
field docstrings state that `budgets.max_llm_calls` gates re-claim eligibility, not spend-in-run;
the per-attempt cap is factory-runner's `max_turns` literal, a separate number. Each profile's
`evidence_expectations` prose repeats what its budgets actually bound.

Envelope layering (cross-repo contract): profiles carry envelope *parameters* only. The envelope
builder remains `dependency_update.py::build_envelope`, byte-pinned to the shared fixture. A test
asserts the emitted envelope's key set equals the contract fixture's. A profile that needs a new
envelope key is out of scope by definition and goes to HQ.

Defaults-not-grants: nothing here changes approval behavior; every unit still gets its own
fingerprint-bound human authority approval.

## 6. The three profiles

**`dependency-update` (formalized).** Becomes a declarable registry profile for the first time.
Contract = shipped code + GAP-4 proof, superseding the 07-17 spec's drifted details: 2-command uv
envelope (`uv add` locks inline), per-site section flags, multi-site `--frozen` strategy + final
`uv lock`; the four fail-closed validations as implemented (`validations.py` #1/#2/#4 + #3
structural); mutators-first-verifier-last; `make check` never in an envelope. npm variant
retained, explicitly marked production-unproven. `profile_fields`: `target_repo`, `package`,
`from_version`, `to_version`. Decompose's CLI args are unchanged this workstream; deriving them
from a declared package is a named follow-up. Tag map: `ci:`/`gate:` → `automated_check`,
`human:` → `human_review` (same mapping as maintenance-remediation — never `automated_test`).
Validator: `forbidden_evidence_types={"automated_test"}`; `max_attempts` default 3.

**`maintenance-remediation`.** Phase-3 WS-P3.2's authoring target: a bounded fix in an existing
repo from an approved handoff item. `profile_fields`: `repo`, `remediation_source` (handoff item
ref), `rollback_plan`, optional `pr_url` (first `OptionalKey` consumer). Required checks: the
repo's own named check on the PR head. Evidence: `automated_check` + `human_review`;
`automated_test` forbidden. Factory-executable: `change_class="maintenance-remediation"`,
routing row required (seeded `sonnet-5`, derivation noted in §3).

**`non-software-operational`.** The WS-P2.13 vehicle, shaped from the existing
`ws-2.4-historical-listing-launch` package as reference exemplar. No repo, no CI, no authority
envelope: `change_class=None`, `tooling=None`, `default_authority=None`. `profile_fields`:
`owner`, `operating_procedure` (pointer to the checklist/skill), optional `external_systems`
(second `OptionalKey` consumer). Evidence: `human_review` / `external_attestation` /
`observation` only — the tag map has no `ci:`/`gate:` entries, so `automated_test` is
structurally unreachable, plus the explicit forbid for defense in depth.

**Named stubs (documented here + PROJECT.md, not registered):** `docs-only` (owner: Devon;
promotes when Part 5 decision 4's guardrail evidence exists), `python-service` / `ts-service`
(owner: Devon; largely covered by `software-delivery` today — promote when a greenfield service
package needs what it lacks), `emergency-remediation` (owner: Devon; distinct from maintenance
by authority posture — promote with the Phase-3 WS-P3.2 build if its lane needs the split).
An empty registered profile invites use; stubs stay out of the registry.

## 7. Optional-key support in the schema walker

Minimal marker type in `schema.py`:

```python
@dataclass(frozen=True)
class OptionalKey:
    spec: ScalarSpec | ListSpec | MapSpec | OpenMapSpec
```

`_walk_map` changes by two lines: a missing key whose spec is `OptionalKey` is skipped; a present
key unwraps and walks normally. The unknown-key check is untouched — schemas stay closed.
`validate.py`'s duplicated top-level check is untouched (no top-level optional exists). The only
`OptionalKey` uses at ship time are the two new profiles' `profile_fields` (real consumers — the
mechanism does not ship dead).

The `follow_up` cadence/recurrence field (WS-P2.8 §14.2's assignment) is **deferred with
rationale**: the orchestrator computes due-ness from its own config and is untouched this
workstream, so the field would have no reader — the `profile_fields.branch` decoration defect.
When the consuming orchestrator workstream exists, adding the field is a small additive change
enabled by this walker support. Recurrence semantics (ADR-0007: one follow-up per revision,
forever) remain WS-P2.10-owned and move with the field.

## 8. Testing

- Routing policy: parse + schema (8 surface rows present; every `[change_class]` model slug
  exists in `[models]`; version is a positive int); `factory route` tested through its real CLI
  entrypoint; decompose fail-closed on a missing routing row.
- Profiles: positive + negative tests per validator constraint (including `automated_test`
  rejection with the relaxation condition in the message: "until orchestrator remediation
  2.1/2.2/2.3 ship together"); envelope key-set equals the byte-pinned contract fixture.
- Walker: `OptionalKey` present/absent/unknown-key behavior.
- Regression: all 19 real `packages/` dirs validate with output identical to pre-change;
  explicit `package_hash` stability over every real package; the locked-hash constant test
  (`test_profiles_compat.py`) stays green.
- Gate: `make check` green with the collected-test count read (197 baseline + new), CI
  `validate --all` green. Discipline: subagent TDD, fresh implementer + two-stage review per
  task, final adversarial whole-branch review with kill budget, `/code-review`, Devon merges.

## 9. Closeout and evidence (criterion #11)

Closeout note in `~/docs/software-delivery-system/` updating the Phase-2 plan header and
scorecard cell #11. Evidence form: artifact + evidence doc + HUMAN closeout (Devon). **#11 cites
no routes, so it gets no `exit-criteria-claims.toml` entry — stated explicitly, not skipped.**
The cell cites: the policy file path + version, the three consumers, the ship-time factory-runner
assertion result, and the Part 2b seeded-from annotation. Criterion #1 (profiles *proven*) stays
open — proving is WS-P2.13 and later real packages; the closeout says so. No production deploy.
