# `factory decompose` + dependency-update delivery profile — design

**Date:** 2026-07-17. **Status:** approved design (feeds WS-P2.10 profiles + the `decompose`
slice of WS-P2.9 factory CLI). **Home repo:** `intent-packages`.
**Source spec:** `~/docs/software-delivery-system/2026-07-17-dependency-update-profile-and-decompose-tool-spec.md`
(the defect-informed design captured after hand-authoring the WS-6.4 decomposition twice).
**Backlog:** intent-packages `PROJECT.md` item `23cdbf9c` (P2).

## Goal

One command turns *(intaken revision + mapped acceptance criterion + target repo + chosen
dependency + tooling)* into a **validated, optionally-submitted decomposition proposal**, so the
four WS-6.4 defect classes become **structurally impossible** rather than avoided by care. The
value is making the failure modes impossible, not saving keystrokes.

The dependency-update decomposition was hand-built twice (orchestrator AC-001, uv, revision 5;
brain AC-002, pip/requirements.txt, revision 6). Every WS-6.4 defect came from hand-authoring:
hand-typed conformance, `make check` in an envelope the bare runner can't run, a mutator that
produced no diff, the `ac_id` UUID-vs-string footgun.

### Mechanical vs judgment split

**Mechanical → the tool does it (deterministic):** resolve criterion DB UUIDs and build
`ac_mappings` + `retained_acs`; compute `conformance` from the real scanners; assemble the
authority envelope from the per-tooling profile template; run the fail-closed validations; submit
the proposal (SYSTEM/M2M).

**Judgment → stays authored (the tool validates, a human/agent decides):** which dependency,
which tooling/mutator fits the repo, whether the update is desirable now.

## Non-goals

- No auto-merge, no auto-approve, no new dispatch/verification machinery.
- **No new validation *framework*.** The validations are a handful of small, specific functions —
  not a generic harness. (Building new validation machinery is an explicit WS-6.4 trap.)
- Not the whole WS-P2.9 front door. This is the `decompose` slice only; it *establishes* the
  `factory` console script that the journey verbs later join (see "CLI surface").

## Architecture

- A new **`factory` console script in `intent-packages`**; `decompose` is its first subcommand.
  Argparse with lazy per-subcommand imports, mirroring the existing `intent_packages` CLI
  (`src/intent_packages/cli.py`). Subcommand dispatch is structured so the codex-envisioned front
  door (`create / validate / submit / status / evidence / retry / cancel`,
  `~/docs/software-delivery-system/2026-07-04-codex-post-mvp-recommendations.md`) can join without
  a rewrite.
- **The tool shells out to the existing `orchestrator` CLI** for every orchestrator/scanner touch
  — the same cross-repo-shell pattern the repo already uses in `emitter.py` (which shells
  `factory_events`). This reuses all HTTP/auth and the canonical conformance helper, and keeps
  `intent-packages`' dependency footprint at pyyaml-only (importing `orchestrator` would drag in
  FastAPI/SQLAlchemy/etc.). The `orchestrator` CLI is a documented runtime prerequisite on `PATH`,
  analogous to `SECURITY_STANDARDS_DIR` for the emitter.

  | need | shelled command |
  |---|---|
  | criterion `{ac_id: uuid}` map + criteria | `orchestrator show-package-intake <rev> --json` |
  | real-scan conformance block | `orchestrator conformance-claim <target_repo> --json` |
  | submit the proposal (SYSTEM/M2M) | `orchestrator propose-decomposition <rev> --data @proposal.json` |

  Auth passes through the orchestrator CLI's existing contract: `ORCHESTRATOR_API_URL`,
  `ORCHESTRATOR_API_TOKEN`, `ORCHESTRATOR_API_CREDENTIAL_KEY_ID` (the `X-Credential-Key-Id`
  header — omitting it 401s). For submission use the **system** M2M credential
  (`221a48d5-…`), not the verifier one.

## The dependency-update delivery profile (WS-P2.10)

`src/intent_packages/profiles/dependency_update.py` — a small registry keyed by tooling
(`uv`, `pip`, `npm`). Each variant is a set of pure functions over
`(target_repo_path, package, old, new)`:

1. `discover_pin_sites()` → the list of `(file, section)` where `package` is pinned.
   - **uv:** `pyproject.toml` `[project.dependencies]`, `[dependency-groups.*]`,
     `[project.optional-dependencies.*]`, plus `uv.lock`. (uv resolves groups + extras jointly; a
     partial pin edit makes the lockfile unsatisfiable.)
   - **pip:** `requirements.txt`, `requirements-dev.txt` (a pin duplicated across both must move
     together).
   - **npm:** `package.json` `dependencies` / `devDependencies`, plus `package-lock.json`
     (inherently dual-site).
2. `mutation_commands()` → the ordered mutator(s).
   - **pip:** anchored idempotent `sed`: `sed -i 's/^PKG==OLD$/PKG==NEW/' <file>`.
   - **uv:** `uv add [--dev] 'PKG>=NEW'` — the `--dev` flag chosen from where the pin lives
     (pin-site discovery decides).
   - **npm:** **TBD — hand-proven against infraops-mcp-server as implementation step 0** (see
     "npm preflight"). Must move `package.json` *and* `package-lock.json`, idempotently.
3. `verifier_command()` → a **deterministic, non-tool-guarded pin-assertion** (structural
   runner-honesty; see validation #2).
   - **pip:** `grep -qx 'PKG==NEW' requirements.txt` (proven).
   - **uv:** a grep-style assertion the new constraint is present in the pinned site.
   - **npm:** grep-style assertion the new version is present in `package.json` (proven in
     preflight).
4. `envelope(...)` → fills the byte-pinned envelope skeleton and returns the authority dict.

### Envelope skeleton (the byte-pinned cross-repo contract)

The shape is fixed by `orchestrator/tests/fixtures/runner_authority_envelope.json` (and its
byte-identical twin in `factory-runner`, pinned by `CONTRACT_SHA256`). The tool emits exactly
this, **omitting `work_unit_id`** (the orchestrator stamps `uuid5(proposal_id, unit_key)`; an
author-supplied `work_unit_id` is rejected with `authority_work_unit_id_forbidden`):

```json
{
  "budgets": {"max_attempts": 3, "max_llm_calls": 4},
  "capabilities": {
    "command.run": "allowed", "github.pr.create": "allowed",
    "orchestrator.claim": "allowed", "orchestrator.evidence.write": "allowed",
    "repo.edit": "allowed", "repo.read": "allowed"
  },
  "change_class": "dependency-update",
  "conformance": {"accepted_standards": [...], "standards_touched": [...], "status": "..."},
  "constraints": {
    "allowed_commands": [<mutation_commands...>, <verifier>],
    "mutation_commands": [<mutation_commands...>],
    "target_repository": "AlobarQuest/<repo>"
  }
}
```

**Command ordering is uniform across all tooling: `allowed_commands = mutation_commands + [verifier]`
— mutators first, the deterministic assertion last.** `finalize-run` re-executes the whole ordered
list before inspecting the tree, so a verifier placed before a mutator would attest to a tree that
is not the one pushed. This uniform shape also resolves a latent inconsistency between the source
spec's uv example (which listed `uv sync --locked` first) and the mutator-first fixture: with a
grep-style assertion verifier, no `uv sync` / install step is needed, so every tooling collapses to
the same two-part shape.

The orchestrator enforces, for `change_class == dependency-update` with `repo.edit` allowed:
`capabilities["command.run"] == "allowed"`; `allowed_commands` non-empty; `mutation_commands`
non-empty and a verbatim ordered subset of `allowed_commands`
(`orchestrator/kernel/runner_authority.py`).

## `decompose` command flow

1. **Fetch criteria** — `show-package-intake <rev> --json`; build `{ac_id_string: uuid}` from each
   criterion's `ac_id` (human string) and `id` (DB UUID).
2. **Build AC disposition** —
   - `ac_mappings = [{ac_id: <uuid of --ac>, unit_key}]` (the `ac_id` field wants the **DB UUID**,
     not the string — the footgun this kills).
   - `retained_acs = [{ac_id: <uuid>, rationale} for every OTHER criterion]`. The orchestrator
     enforces **full coverage**: every criterion mapped-or-retained exactly once, union == all.
     Default retained rationale auto-generated; `--rationale` overrides.
3. **Conformance** — `conformance-claim <target_repo> --json`. Never hand-typed; the tool has no
   code path that accepts an author-supplied conformance.
4. **Envelope** — the profile variant assembles the one proposed unit's authority envelope.
5. **Validate** — run the owned validations (below). Any failure → non-zero exit, nothing written
   or submitted.
6. **Emit** — write the full proposal JSON (`--out <file>`, default stdout). Body fields:
   `idempotency_key`, `expected_version: 0`, `rationale`, `proposed_units: [one unit]`,
   `dependencies: []`, `ac_mappings`, `retained_acs`.
7. **Submit (only with `--submit`)** — `propose-decomposition <rev> --data @<file>`. Self-correcting
   version pattern is unnecessary here (`expected_version` must be `0`). Default is assemble +
   validate only; submission is explicit.

## The four fail-closed validations

| # | validation | kind | how |
|---|---|---|---|
| 1 | **Dry-run proves a real diff + idempotency** | active | `git clone --local` the target repo at HEAD into a temp dir (the honest "clean clone"); run the ordered `allowed_commands`; `git diff` → **fail closed on empty diff**; run the list a **second time** → **fail closed if the diff changed** (non-idempotent, would break `finalize-run`'s re-execution). One focused function. |
| 2 | **Verifier is runner-honest** | structural | the profile only ever emits the deterministic assertion; the tool **rejects** any `allowed_commands` entry matching a denied tool-guarded check (`make check`, `pytest`, `uv run make check`, `npm test`, …). Real tests stay on the target repo's own named check on the PR head, which is where AC evidence already lives. |
| 3 | **Conformance from a real scan** | structural | conformance comes only from the shelled `conformance-claim`; no hand-typed path exists. `accepted_standards` therefore originates from the real waiver source the scanner reads, never echoed from `standards_touched`. |
| 4 | **Name every pin site** | active | `discover_pin_sites()` vs. the files the `mutation_commands` touch; if the pin is multi-site and any site is untouched → **fail closed**. (fastapi in brain was single-site; httpx was dual-site; uv groups+extras and npm json+lock are multi-site by nature.) |

Environment discipline folded in: validation #1 already runs the list **twice in one checkout** and
against a **clean clone**, so a runner-environment failure is never read as an update-induced one.

## CLI surface

```
factory decompose \
  --revision <revision_id> \
  --ac AC-002 \
  --target-repo AlobarQuest/brain \
  --tooling pip \
  --package fastapi --from 0.139.0 --to 0.139.2 \
  [--unit-key <key>] [--rationale <retained-rationale>] \
  [--out proposal.json] [--submit]
```

- One invocation = one proposed unit (one AC → one repo → one dependency). Multi-unit fan-out is
  out of scope for this slice.
- `--submit` is the only orchestrator write; without it the tool is read-only + local.

**Vocabulary coherence with the front door:** `decompose` is not one of the seven journey verbs —
it is an internal mechanical step. Its `--submit` submits the **decomposition proposal**; the future
`factory submit` verb submits the **intent revision** (a different object, an earlier journey step).
No collision.

## Human gates: untouched

`decompose` performs exactly one orchestrator write (the SYSTEM/M2M proposal submit), and the
proposal is **non-canonical until Devon approves it**. Untouched, human, and out of scope:

- **Intake** — `POST /api/v1/package-intakes` (forward-auth router, browser `fetch`). HUMAN.
- **Decomposition approval** — the `/review/decomposition-proposals/{id}` **GUI form** only; the
  raw `/api` approve route is M2M-only and 401s a browser by design. HUMAN.
- **Authority approval** — `POST …/work-units/{id}/approvals`, `subject_type:"authority"`
  (forward-auth router, browser `fetch`). HUMAN. (Then the separate SYSTEM `commands/ready` edge.)
- **Merge** — Devon, permanent.

## npm preflight (implementation step 0)

The npm envelope is unproven, so — exactly as uv and pip were proven before use — the first
implementation step is a hand-proof against `AlobarQuest/infraops-mcp-server` (package.json +
package-lock.json), recorded as evidence like the rev-6 Brain preflight
(`intent-packages/docs/superpowers/evidence/2026-07-17-ws64-revision6-brain-preflight.md`). It must
establish: a mutator that moves **both** `package.json` and `package-lock.json` idempotently under a
second execution, a real available upgrade (so the diff is non-empty), and a deterministic
grep-style verifier. Its result feeds `dependency_update.py`'s npm variant. **If the npm shape
cannot be proven idempotent/dual-site cleanly, npm ships as a documented extension point and AC-004
waits** — the tool never emits an unvalidated template.

## Testing

- Profile variants: assert the assembled envelope matches the byte-pinned fixture shape
  (minus `work_unit_id`) for uv, pip, npm.
- `discover_pin_sites()`: fixture repos exercising single-site and multi-site pins per tooling.
- Validations: fixture repos where the mutator yields no diff (#1 fails), is non-idempotent
  (#1 fails), leaves a pin site untouched (#4 fails), and a denied verifier (#2 fails).
- Do not stand up a live orchestrator in tests; the orchestrator/scanner touches are shelled and
  mocked at the subprocess boundary.

## Operational facts reused

- BWS creds by UUID: verifier `660d5846-…`, system `221a48d5-…`. Use **system** for the submit.
- Dispatch ordinals count decisions (skipped + blocked). Not relevant to `decompose`, but relevant
  when the produced unit is later dispatched.
- `sds.alobar.net` is not Cloudflare-proxied; a `401` there is an M2M-only-path/routing issue,
  never broken forward-auth.
- MERGED ≠ DEPLOYED: before relying on any orchestrator route the tool shells, confirm production
  serves it (`curl -s https://sds.alobar.net/openapi.json`). `show-package-intake`,
  `conformance-claim`, and `propose-decomposition` are stable pre-existing CLI commands, but the
  production image must actually serve their endpoints.

## Scope note (why this matters now)

The WS-6.4 re-prove is 3/6. Remaining: AC-003 security-standards (uv), AC-004 infraops-mcp-server
(npm), AC-005 intent-packages (uv). This tool makes each cheap. Production is healthy on
`5c8b0e8-pr60` with **dispatch disabled**; this build does not change that — `decompose` only
authors and submits a proposal for human approval.
