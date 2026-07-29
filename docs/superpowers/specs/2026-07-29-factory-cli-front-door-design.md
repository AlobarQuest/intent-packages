# WS-P2.9 — the `factory` CLI, single paved-road front door

Date: 2026-07-29. Repo: `AlobarQuest/intent-packages`. Wave 3, second workstream
(P2.10 ✅ → **P2.9** → P2.11 → P2.12 → P2.13).

Grows the existing `factory_cli` on top of WS-P2.10's `DeliveryProfile` registry and
`routing.load_policy()` (merged `79be64b`). Consumes the orchestrator strictly as an API
client: **no orchestrator route or schema changes, and no orchestrator repo changes at all.**

Closes program deliverable **C#1** (the single paved-road front door) and folds in gap-closure
remediations **6.2** (the verifier flow has no CLI command) and **6.3** (no way to create an
intent package — the declared authoring front door hands you a blank page).

## Governing constraint — ADR-0006

Verbatim, from the ADR's consequences-for-WS-P2.9 clause:

> the CLI wraps every **non-human** surface — intake payload emission, conformance claims,
> decomposition proposal, verifier reads, status. At each **human** gate it stops and hands off:
> it deep-links the `/review` page, or puts the payload on the clipboard for the form. **It never
> impersonates a human**, and it must not grow a flag that pretends to. A CLI that could satisfy
> `_require_human` would defeat this ADR by construction, so "wrap the API" is not an available
> implementation for those three gates.

The three human gates are package intake, decomposition decision, and authority approval.
`cancel`/`retry`/`review` are human gates too (they are `/review` POST forms). None of them gets
a `factory` verb that performs the transition. There is deliberately **no flag** — not
`--as-human`, not `--force`, not a config key — that could ever satisfy `_require_human`. A
future reviewer finding one should treat it as a defect, not a feature.

## Decisions taken with Devon (2026-07-29)

| # | question | decision |
|---|---|---|
| 0 | transport for surfaces with no `orchestrator` CLI command | **Direct HTTP client in intent-packages** (`httpx` joins runtime deps) |
| 1 | increment-1 command surface | **Whole lane**: `create validate submit status evidence ready dispatch verify` |
| 2 | credential posture | **Env-first, BWS auto-fetch fallback**, two roles (SYSTEM + VERIFIER) |
| 3 | resume loop | **Stateless by default, opt-in `--wait`** |
| 4 | flow state | **None** — `--revision` is the only uuid; everything else re-derived |
| 5 | demonstration | **Build and drive production in the same session**, production drive last |

Decision 0's rationale is a verified gap, not a preference: `src/orchestrator/cli.py` has **no**
command for `evidence-pack`, `verifier-evidence/named-check`, or `POST /verify`. Its `verify` is
the *lifecycle transition* (`POST commands/verify`), a different route. The remediation order
already anticipated this — *"Fold into WS-P2.9 rather than building it twice."*

Decision 1's rationale: the definition of done requires driving a real flow with only `factory`
plus browser clicks, and the lane as GAP-4 actually ran it needs `commands/ready`, `dispatch`,
and the verifier pair. A five-verb increment would still have fallen back to raw `orchestrator`
CLI and hand-rolled `httpx` — the exact gap C#1 exists to close. None of the three added verbs is
a human gate; all are SYSTEM or VERIFIER.

Decision 4 is viable because exactly **one** id is underivable. There is no list route for
package intakes (`POST /api/v1/package-intakes` and `GET /api/v1/package-intakes/{revision_id}`
only), and `traceability`'s `source_repository` is a qualifier on the `pr`/`commit` anchors, not
a standalone anchor kind — so a freshly created revision cannot be discovered by polling. Devon
hands the revision id back once, from the `/review/intakes/{revision_id}` page the form redirects
to. Every id after that derives from it.

## 1. Architecture

New modules under `src/intent_packages/factory/`, matching the existing `decompose.py` /
`validations.py` / `orchestrator_cli.py` shape — thin, single-purpose, lazily imported from
`factory_cli.py` so no subcommand pays for another's imports.

| module | responsibility | depends on |
|---|---|---|
| `api.py` | `OrchestratorApi` — httpx client, one method per route used, `ApiError(code, message, hint)` parsed from the orchestrator's error envelope | `credentials` |
| `credentials.py` | `resolve_token(role)` — env first, `bws secret get <uuid>` fallback | `.bws-secrets.toml` |
| `links.py` | pure `/review` URL builders; no I/O, no network | — |
| `scaffolds.py` | `create` templates keyed by registered profile name | `profiles` |
| `journey.py` | `submit`, `status`, `ready`, `dispatch` | `api`, `links` |
| `verify.py` | named-check evidence + verifier evaluation (remediation 6.2) | `api` |

`factory_cli.py` gains eight sibling subparsers and keeps its current form: argparse,
`main(argv) -> int`, lazy per-subcommand imports.

### Transport rule

**Shell out to `orchestrator` only for local computation the orchestrator owns; use HTTP for
everything that is an API call.**

- Retained shell-outs: `emit-intake-payload` (builds the intake payload from a package on disk)
  and `conformance-claim` (runs the real scanners). Both are local; reimplementing either would
  duplicate a contract this repo does not own.
- Migrated to `api.py`: `show-package-intake` and `propose-decomposition`, which
  `factory/orchestrator_cli.py` currently shells out for.

The migration is deliberate. Leaving them would give the front door two transports, two auth
paths and two error vocabularies — the thing decision 0 rejected. It touches `factory decompose`,
which is production-proven (GAP-4), so `tests/factory/test_decompose.py` plus the production
drive in phase 4 are its regression check. `OrchestratorCliError` narrows to the two local
commands; `ApiError` covers the API.

### Dependency

`httpx` joins `[project].dependencies` alongside `pyyaml`. The `pyyaml`-only runtime footprint
was a stated preference in `orchestrator_cli.py`'s docstring, not a recorded rule; it is
consciously spent here. `sds.alobar.net` is **not** Cloudflare-proxied, so httpx's default
User-Agent authenticates fine — the portfolio-wide `error code: 1010` invariant does not apply.

## 2. Credentials

Two M2M roles are needed, and the handoff's single-credential framing was wrong:

| role | credential | BWS uuid | used by |
|---|---|---|---|
| SYSTEM | `orchestrator-system` | `221a48d5-3f29-4898-b300-b4820140c880` | all reads, `decompose --submit`, `ready`, `dispatch` |
| VERIFIER | `orchestrator-verifier` | `660d5846-abcb-4751-be86-b483012899eb` | `verifier-evidence/named-check`, `POST /verify` |

`orchestrator-drift-reporter` is **not** available to this tool. Its registry profile is
observe-and-propose and `agent_id` attribution is permanent.

`resolve_token(role)`:

1. Env: `ORCHESTRATOR_SYSTEM_TOKEN` / `ORCHESTRATOR_VERIFIER_TOKEN`. If set, use it.
2. Otherwise `bws secret get <uuid>`, uuid read from a repo-root `.bws-secrets.toml` manifest
   (uuids are identifiers, not secrets, and are already recorded in the orchestrator's
   `CLAUDE.md`). `BWS_ACCESS_TOKEN` must already be in the environment; `factory` never fetches
   or stores it.
3. Neither available → `ApiError("credential_unavailable", …)` naming both the env var and the
   uuid. Never a prompt, never a fallback to an unauthenticated call.

Every request sends `Authorization: Bearer <token>` **and** `X-Credential-Key-Id: <key-id>`; a
bare GET is 401. The token is held in a local variable and passed to httpx; it is never logged,
never put in an exception message, never written to disk, and never interpolated into a
subprocess argument. `--verbose` prints request method, path and status only.

`links.py` builds exactly four URLs, all pure string composition over
`$ORCHESTRATOR_API_URL`: `/review/intakes/new`, `/review/intakes/{revision_id}`,
`/review/decomposition-proposals/{proposal_id}`, and `/review/units/{unit_id}` (plus its
`/evidence-pack` child). Those are the human surfaces; there is no fifth.

## 3. Commands

Joining the existing `decompose` and `route`.

### `factory create --profile <name> --name <slug> [--out packages/]`

Remediation 6.3. Scaffolds `packages/<slug>/package.yaml` + `lineage.yaml` from a **registered**
profile. An unregistered name (including the four documented stubs — docs-only, python-service,
ts-service, emergency-remediation) errors with the sorted list of valid choices; WS-P2.10's
registry↔routing guard means registering one is a deliberate act, and `create` must not undercut
that.

Templates carry the banked rules at the point of use, as comments in the emitted YAML:

- No `evidence_type: automated_test` anywhere. It resolves to `judgment_required` in the verifier
  for every automated AC however good the evidence, and the `dependency-update` /
  `non-software-operational` profiles reject it outright via `forbidden_evidence_types`. Use
  `test` or `automated_check`.
- `ac_id` semantics stated where they are asked for: `ac_mappings[].ac_id` /
  `retained_acs[].ac_id` want the criterion's **database UUID**; evidence and adjudication want
  the human string `AC-001`.
- For `dependency-update`, the envelope discipline: `allowed_commands` is an ordered list the
  worker re-executes at finalize, so mutators come first and the verifier last; `make check`
  never appears in this repo's envelope; `uv venv --clear`, never bare `uv venv`.

`create` validates what it just wrote and fails if its own scaffold does not pass. A front door
that emits invalid output is worse than a blank page.

### `factory validate <path>`

Delegates in-process to `intent_packages.validate.validate_package` — the same code path as
`intent_packages validate`, not a reimplementation.

### `factory submit --package <path> --source-repository <slug> [--open]`

Human gate. Emits the intake payload, **copies it to the clipboard** (`pbcopy`), prints the
`/review/intakes/new` URL (opening it with `--open`), and stops:

> intake payload staged and copied; form opened; waiting on your approval.
> when the form redirects, re-run with:  factory status --revision <id from that URL>

It does not, and cannot, complete the intake. Two facts it must state rather than let the user
rediscover: the form takes its **idempotency key from the form field, not the payload**, so
re-submitting a rendered page is a *replay* and a genuinely new registration needs a page reload;
and intake requires the package to be `approved` (`status == current_state == approved`, exactly
one lineage approval matching `canonical_package_hash`, a real git HEAD commit). If the package
is not approved, `submit` refuses **before** emitting and prints the exact `intent_packages`
command to run. Package lifecycle verbs stay in `intent_packages`; `factory` does not duplicate
them.

### `factory status --revision <uuid> [--wait]`

One screen: intake state; decomposition proposals and their states; per unit the `unit_key`,
state, authority fingerprint, whether an authority approval is recorded and by whom; latest
dispatch ordinal; and **the next action with its deep link**. `--wait` polls (bounded interval
and timeout, Ctrl-C safe) until the state changes.

The next-action line is what makes this a front door rather than a dump. It must distinguish the
two failure modes that cost the most time historically: a unit with an authority approval
recorded but still in `DRAFT` (needs `factory ready`, because authority approval does not move
state), and a unit whose `/review` approval was the generic action button rather than the
authority form (`subject_type="action"` does not satisfy readiness).

### `factory evidence --revision <uuid> [--unit-key K] [--markdown]`

`GET /work-units/{id}/evidence-pack` (JSON) or `/evidence-pack/markdown`. Without `--unit-key`,
the revision-level pack. The markdown variant is the redacted form that gets relayed to a
possibly-public PR comment; the JSON is full-fidelity and auth-gated. `factory` prints them as
returned and redacts nothing further — the redaction decision belongs to the renderer.

### `factory ready --revision <uuid> --unit-key K`

SYSTEM, `POST /work-units/{id}/commands/ready`. `(DRAFT, READY)` is a SYSTEM edge with no
approval guard; only `AWAITING_APPROVAL → READY` is guarded. This verb exists because authority
approval does not move the unit's state and forgetting the step yields a `work_unit_not_ready`
dispatch block while `readiness` still reports `status: ready` (that endpoint reports conditions
met, not lifecycle state).

**Version resolution.** A DRAFT unit is absent from `in-flight-units`, which is the only read
surface carrying `version`. The documented client contract is: POST with `expected_version: 0`
and an otherwise **valid** body, read `current_version` off the `version_conflict` error, retry.
(Otherwise-valid matters: FastAPI 422s on schema validation before the service raises
`version_conflict`.) This lives once, in `api.resolve_version(unit_id)`, and every write verb
uses it.

### `factory dispatch --revision <uuid> --unit-key K`

SYSTEM, `POST /work-units/{id}/dispatch`. Two invariants encoded here rather than re-derived:

- **Ordinal.** `runner_attempt` is `max(unit.attempt_count, latest_runner_attempt) + 1`, with the
  prior ordinal read from the last `dispatch.dispatched` event's `payload.runner_attempt` in
  `GET /work-units/{id}/history`. Dispatch and claim ordinals are independent, so
  `attempt_count + 1` is not a safe substitute.
- **Success.** A reused ordinal makes dispatch a silent no-op: `dispatch_unit` returns the
  *existing* record with HTTP 200, `status: "dispatched"`, `reason_code: null`, and triggers no
  `workflow_dispatch`. `factory dispatch` therefore asserts a **new record id** against the prior
  one and reports failure if it matches. It never treats the `status` field as proof.

It prints the reminder that closing the dispatch window restarts the orchestrator and that
terminal means all three of: the Actions run concluded, the unit left `executing`, and
cost-actuals exist.

### `factory verify --revision <uuid> --unit-key K --ac AC-00N --check-name <n> --conclusion <c> --run-id <id> --run-url <url> [--assert name=expected:observed ...]`

Remediation 6.2. VERIFIER role, two calls: `POST verifier-evidence/named-check`, then
`POST /verify`. Prints per-AC outcomes.

The named-check body is the reason this was hand-rolled every time. `factory` derives what it
can and takes the rest as flags:

| field | source |
|---|---|
| `work_package_revision_id` | `--revision` |
| `dispatch_id` | last `dispatch.dispatched` event in `history` |
| `pr_number`, `head_sha` | `traceability?work_unit_id=` → `chains[].pr` |
| `pr_url` | composed from repository + `pr_number` |
| `repository` | the unit's authority envelope `constraints.target_repository`, via the evidence pack |
| `ac_id` | `--ac` — the **human string** (`AC-001`), not the UUID |
| `check_name`, `conclusion`, `run_id`, `run_url`, `assertions` | flags |

Derivation sources marked "via the evidence pack" and "via traceability" must be confirmed
against a live response during the phase-4 drive; if a field is not present where expected, it
becomes a required flag rather than a guess. Note `assertions` is capped at 32 items and each
needs `name`/`expected`/`observed`.

### Human gates get no verbs

`retry` and `cancel` are deferred to increment 2 as link-and-resume only. Where a command's next
step is a human gate, it prints the `/review` URL and the reason. Refusals name the gate and the
form, never a workaround.

## 4. Data flow

One uuid in; everything else derived, every run, from the API:

```
--revision
  ├─ GET /api/v1/package-intakes/{revision}                     intake state, criteria (ac_id ↔ uuid)
  ├─ GET /api/v1/package-intakes/{revision}/decomposition-proposals   proposal ids + states
  └─ GET /api/v1/traceability?revision_id={revision}            per unit: id, unit_key, state,
                                                                authority_fingerprint,
                                                                authority_approved_by/decision, pr hop
        └─ per unit:  GET .../readiness      conditions met
                      GET .../history        dispatch ordinals, events
                      GET .../evidence-pack  envelope, evidence chain
```

Units are addressed by `--unit-key`, never by a second uuid. `--revision` may also come from
`$FACTORY_REVISION`. Nothing is cached to disk; there is no flow file, and no second source of
truth to go stale.

## 5. Error handling

`ApiError` carries the orchestrator's `code`, `message` and `hint` verbatim — the orchestrator's
error envelope is already good, and paraphrasing it would lose the hint. On top of that:

- **401 is annotated and never retried**: *"this route is M2M-only at the proxy — check the
  credential role for this command."* There is no first-POST-retry branch anywhere in this tool;
  that quirk was speculation, is disproven, and must not be reintroduced.
- **`version_conflict`** is handled by `resolve_version`, not surfaced, on the probe path only.
  A conflict on a real write is surfaced.
- **Timeouts / connection failures** are distinct codes from HTTP errors, so "production is down"
  never reads as "your request was wrong".
- Only `DomainError` and `APIAuthenticationError` have handlers on the orchestrator side, so a
  bare 500 means an unhandled exception there. `factory` says so rather than implying user error.

## 6. Testing

- **Every command through the real entrypoint.** `main(argv)` against an `httpx.MockTransport` —
  the argparse analogue of CliRunner. Testing a command function directly would not catch a
  broken parser wiring, which has shipped a broken launcher before.
- **Credentials.** Env path tested directly; BWS path tested with an injected fake runner. No
  test fetches a real secret, and a test asserts no token appears in any rendered error string.
- **Scaffold guard.** `test_every_registered_profile_scaffolds_and_validates` — every registered
  profile must scaffold, and the scaffold must validate clean. This is what keeps `create` honest
  as profiles change; it is the `create`-side analogue of WS-P2.10's no-silent-noop guard.
- **Ordinal guard.** A test that a dispatch returning the prior record id is reported as failure,
  not success.
- **Existing guards stay green**: registry↔routing bidirectional consistency, no registered
  profile is a silent no-op, the 19-package regression with its locked hash snapshot.
- `make check` green with the **collected count read**, not inferred. Baseline is 295 passed.

## 7. Phasing

1. `api.py` + `credentials.py` + `links.py`, with tests. Migrate `decompose`'s two API shell-outs.
2. `create` + `validate` + `scaffolds.py` (remediation 6.3).
3. `submit` + `status` + `evidence` + `ready` + `dispatch` (`journey.py`), then `verify.py`
   (remediation 6.2).
4. Full local-orchestrator drive of every verb; `make check`; adversarial whole-branch review.
5. **Production drive** — real intake, browser gates, dispatch window, verifier.

Phase 4 ends with a clean checkpoint. Phase 5 opens the bounded dispatch window on production and
is the only phase that mutates it; if budget tightens, stopping before phase 5 leaves a
mergeable branch rather than a strand inside an open window. Holding the window open is bounded
by construction — dispatch admission requires a READY unit with its authority approval — so the
window stays open until the run is terminal in all three senses, never closed to save time.

## 8. Out of scope

- `retry` / `cancel` link-and-resume — increment 2.
- Any orchestrator repo change, including CLI-only additions.
- A scoped read-mostly credential. It would need a security-standards commit plus an image
  rebuild, and could not cover `ready`/`dispatch`/`verify` anyway, so it adds a deploy without
  removing either existing credential. Recorded as a follow-up against the end-of-Wave-3 BWS
  plan.
- Package lifecycle verbs (`transition`, `approve`, `revise`, `supersede`) — they stay in
  `intent_packages`.
- Remediations 6.1 (`profile_fields.branch` is decoration), 6.4 (lane-blind envelope), 6.5
  (factory-runner pilot workflow). Untouched here.

## 9. Definition of done

Increment-1 commands shipped; every command tested through the entrypoint; no orchestrator
changes; `make check` green with the collected count read; a real flow driven end to end against
production with only `factory` plus browser clicks; adversarial whole-branch review; Devon
merges; closeout evidence in `~/docs/software-delivery-system/` updating the Phase-2 plan and
saying plainly what remains felt-gap versus closed.
