# WS-6.4 revision 4 Change Manager run evidence

Status: **BLOCKED at Task 8 Step 11, before verifier invocation.** The single dispatch, runner, pull request, and exact-head Quality proof succeeded. Canonical AC-006 is stored with `evidence_type=automated_check`, but the deployed WS-5.1 verifier does not recognize that vocabulary as deterministic. Invoking it would route the unit to `awaiting_review` instead of producing the required verifier adjudication and terminal completion. The pull request remains open and unmerged at Devon's gate.

## Execution boundary

- Evidence source branch: `docs/ws64-revision4-change-manager-run`
- Evidence source commit at branch creation: `644fcaa8b9f03c8ca69d864f3efbf8e9b730c652`
- Package: `ws-6.4-dependency-update-fanout`, revision 4
- Authorized target: `AlobarQuest/change-manager`
- Authorized criterion: AC-006 only
- Mandatory stop: before Task 8 Step 6, Devon's decomposition decision

## Step 1: merged package approval and identity

Observed from the isolated worktree created directly from merged `origin/main`:

- `intent_packages validate`: exit 0
- `intent_packages hash`, run twice: `c21f7aafc9c5790b410a8510e434711d33570adf616b8931a2566845b2463da7` both times
- `intent_packages verify-approval`: exit 0
- Package revision: 4
- Approval event: `evt-3b2b1d51ad7b41eab2731bdcf603fa13`
- Approval ledger commit: `14a5f9dd4590e1bbea0825f5890495a2edb2b312`
- Merged source commit: `644fcaa8b9f03c8ca69d864f3efbf8e9b730c652`
- The merge has two parents and preserved the approval-bound commit.

The evidence worktree baseline also passed Ruff, Pyright, and 159 tests.

## Step 2: prepared intake payload and human-authentication gate

The offline payload was generated with the exact deployed/current Orchestrator source `a52d3d2fa46fef1bcdc5aa51cc08d10a2b570f82` from a sibling worktree under `/Users/devon/Projects`, so the CLI could resolve the intent-packages source and verify the factory approval chain.

- Payload path: `/tmp/ws64-r4-change-manager-intake-9f6fdeac-5ce2-4ddb-b8a2-52b2ea650671.json`
- Idempotency key: `ws64-r4-change-manager-intake-9f6fdeac-5ce2-4ddb-b8a2-52b2ea650671`
- Payload SHA-256: `383d22cc8a19f39b28770988b68f64293edf3acda073b5256bf798d270204f82`
- Payload package hash: `c21f7aafc9c5790b410a8510e434711d33570adf616b8931a2566845b2463da7`
- Payload source repository: `AlobarQuest/intent-packages`
- Payload source commit: `644fcaa8b9f03c8ca69d864f3efbf8e9b730c652`
- Payload approval event: `evt-3b2b1d51ad7b41eab2731bdcf603fa13`
- Payload acceptance criteria: 11

Independent approval checks under that exact Orchestrator source:

- The exact intent-packages verification subprocess exited 0.
- Factory event-chain verification exited 0 over 965 events.
- `FACTORY_EVENTS_HOME` resolved to the default `~/.factory/events.jsonl`.
- A sanitized event lookup found the exact approval event and matched package, hash, revision, approver, and approval-bound commit.

One diagnostic run from a `/tmp` Orchestrator worktree failed closed with `package_source_error: approval verification failed`. Root cause was the CLI's deliberate sibling-source lookup: `/tmp/intent-packages/src` did not exist. Repeating from an exact-source worktree under `/Users/devon/Projects` succeeded and produced a byte-identical payload. The relevant package-source, CLI, and intake-operation files have no diff between local `258e97d` and deployed/current `a52d3d2`; this was a routine local layout error, not factory behavior.

The in-app Browser backend was unavailable. Per the human-only intake contract, no machine credential was substituted and no SSO credential entry was attempted. Devon submitted this exact payload from his normal authenticated browser and received HTTP 201.

Canonical intake state was then refreshed read-only from the production Orchestrator container:

- HTTP status: 201
- Intake UUID: `f5bfa951-0b21-46d3-a24a-035d105d5a74`
- Package/revision/hash/source repository/source commit/approval event: all exact matches to the verified payload
- Criteria: exactly 11
- AC-006 database UUID: `6682254e-307d-43e8-9b09-0379df80a4ff`
- Existing proposal count before submission: 0

The intake was not replayed after the successful human POST.

## Step 3: refreshed Change Manager preflight

Fresh remote state was observed before cloning:

- `AlobarQuest/change-manager` `origin/main`: `1f64d0166614574c57663f21dfa33a48682e4a3d`
- This is the required caller-pin squash commit.

In a disposable clone at that exact base, the exact sequence was run twice in succession:

1. `uv add --dev 'httpx2>=2.6.0'`
2. `uv sync --locked`
3. `uv run make check`

Both passes reported:

- Ruff: all checks passed
- Formatting: 59 files already formatted
- Pyright: 0 errors, 0 warnings, 0 informations
- Tests: exactly 105 passed

Persistent result after both passes:

- Changed files only: `pyproject.toml`, `uv.lock`
- `git diff --check`: exit 0
- Git binary-diff SHA-256: `af4a6026dbe114787cc7ed0a146ae11dc350317c9e7f1f9d676512bcb125e230`
- Resolved versions: `httpx2==2.7.0`, `httpcore2==2.7.0`

No real Change Manager checkout or remote branch was changed.

## Step 4: measured conformance at the exact target base

Conformance was computed against a separate clean clone at `1f64d0166614574c57663f21dfa33a48682e4a3d`.

Security scanner:

- Tool source commit: `65655ddf58b8f4401262f3192270515ef88b14f7`
- Rules source: cache
- Rules evaluated: 8
- BLOCK: 0
- WARN: 0
- INFO: 1, judgment-only `bws.least-privilege-scope`
- Allowlisted: 0
- Exit: 0

Project-standards compliance claim:

- Tool source commit: `8d12eeeb900b29be6d627725043b8a1af2a90d0a`
- Status: `green`
- `standards_touched`: `code`, `infra`, `project`, `security`
- `accepted_standards`: empty

The conformance fields above are direct tool output. No standard was copied from `standards_touched` into `accepted_standards`.

## Routine execution repair

An initial preflight command was launched from the wrong working directory and briefly changed only `pyproject.toml` and `uv.lock` in the Orchestrator primary checkout. The check was stopped, those agent-created changes were reversed with a targeted patch, and fresh `git diff --exit-code` plus `git status --short` proved the primary checkout clean before work continued. The successful preflight evidence above comes only from the disposable Change Manager clone.

## Step 5: exactly one decomposition proposal

The proposal payload was built from the canonical intake criterion UUIDs and locally validated against the exact deployed/current Orchestrator source `a52d3d2fa46fef1bcdc5aa51cc08d10a2b570f82`.

- Payload path: `/tmp/ws64-r4-change-manager-proposal-1090dc4e-d9e2-4462-8360-2639355dacf1.json`
- Payload SHA-256: `d641cb020838dd900a2a93c7c64f2129dc8d7b84c2e226d5ee7aac7d71024656`
- Idempotency key: `ws64-r4-change-manager-proposal-1090dc4e-d9e2-4462-8360-2639355dacf1`
- Local schema/service validation: passed
- Proposed units: 1
- AC mappings: 1, AC-006 only
- Retained criteria: 10, AC-001–005 and AC-007–011
- Authored `constraints.work_unit_id`: absent

Exactly one authenticated machine proposal submission returned HTTP success. Canonical production state was then refreshed read-only:

- Proposal ID: `5d40ae31-7d3a-4a05-991e-87e328c58680`
- Proposal number: 1
- Proposal state: `proposed`
- Proposed by/role: `orchestrator-system` / `system`
- Proposal count for revision: exactly 1
- Proposed deterministic unit ID: `4c8c2af4-f963-5511-b3c3-330da81f6373`
- Unit key: `update-change-manager-httpx2`
- Target repository: `AlobarQuest/change-manager`
- Change class: `dependency-update`
- Required capability: `repo.edit`
- Authority fingerprint: `8728149d394cd02c30d1275ff69f21016a997f640c3f02ababd2cbf1903f78df`
- Allowed commands, in order: `uv add --dev 'httpx2>=2.6.0'`; `uv sync --locked`; `uv run make check`
- Mutation commands: only `uv add --dev 'httpx2>=2.6.0'`
- Conformance: `green`; touched `code`, `infra`, `project`, `security`; accepted empty
- Authority budgets: `max_attempts=3`, `max_llm_calls=4`
- Unknown authority fields: empty in the API response
- AC mapping: only AC-006 database UUID `6682254e-307d-43e8-9b09-0379df80a4ff`
- Retained count: 10
- Created work unit IDs: null, as required before approval

Normal-browser review URL:

`https://sds.alobar.net/review/decomposition-proposals/5d40ae31-7d3a-4a05-991e-87e328c58680`

Because the in-app Browser was unavailable, the rendered page was not visually inspected in this session. Before approving, Devon must visually confirm that the page renders the exact repository, change class, three commands in order, one mutation command, capability, measured conformance, deterministic unit ID, fingerprint, AC-006-only mapping, and 10 retained criteria recorded above.

## Current gate

Devon approved the decomposition through the normal SSO-authenticated review page. No agent submitted or replayed that decision.

## Step 6: post-decomposition-approval verification

Canonical production state was refreshed read-only after Devon reported approval:

- Proposal ID: `5d40ae31-7d3a-4a05-991e-87e328c58680`
- Proposal state: `approved`
- Decided by: `devon`
- Decided at: `2026-07-15T12:29:03.391679+00:00`
- Decision reason: `Matches`
- Proposal count for the revision: exactly 1
- Active approved decompositions: exactly 1
- Approved decomposition ID: `9abb151d-def3-45fa-8107-581f91715765`
- Created work units: exactly 1
- Created unit mapping: `update-change-manager-httpx2` → `4c8c2af4-f963-5511-b3c3-330da81f6373`
- Unit state/version: `draft` / 1
- Unit decomposition approver/time: `devon` / `2026-07-15T12:29:03.391679+00:00`
- `constraints.work_unit_id`: `4c8c2af4-f963-5511-b3c3-330da81f6373`, exactly equal to the unit's own ID
- AC mapping: only AC-006 database UUID `6682254e-307d-43e8-9b09-0379df80a4ff`

No duplicate proposal, approved decomposition, or work unit exists.

## Step 7: pre-authority-approval inspection

The unit's canonical stored authority remains identical to the proposed envelope:

- Authority fingerprint: `8728149d394cd02c30d1275ff69f21016a997f640c3f02ababd2cbf1903f78df`
- Target repository: `AlobarQuest/change-manager`
- Change class: `dependency-update`
- Required capability: `repo.edit`
- Capabilities: `command.run`, `github.pr.create`, `orchestrator.claim`, `orchestrator.evidence.write`, `repo.edit`, and `repo.read`, all `allowed`
- Allowed commands, in order: `uv add --dev 'httpx2>=2.6.0'`; `uv sync --locked`; `uv run make check`
- Mutation commands: only `uv add --dev 'httpx2>=2.6.0'`
- Conformance: `green`; touched `code`, `infra`, `project`, `security`; accepted empty
- Budgets: `max_attempts=3`, `max_llm_calls=4`

Approval and readiness state:

- `authority_approval_id`: null
- Approval rows for this unit: 0
- Distinct authority approval: absent
- Action approval: absent; it has not been substituted for authority approval
- Readiness: `not_authorized`
- Sole readiness reason: `authority_not_approved` — `no exact authority approval is recorded`

Normal-browser unit review URL:

`https://sds.alobar.net/review/units/4c8c2af4-f963-5511-b3c3-330da81f6373`

Before approving authority, Devon must visually confirm the unit ID, Draft state, exact target repository, change class, six capabilities, all three commands in order, one mutation command, measured conformance, budgets, AC-006 relationship, and fingerprint recorded above. Stop before posting authority approval or any other action.

## Step 8: authority verification, Ready transition, and dispatch-settings inspection

After Devon reported explicit authority approval, canonical production state was refreshed read-only:

- Approval ID: `b4464f6a-160c-4183-8a52-ffaa098037d8`
- Approval subject type: `authority`
- Approval subject: unit `4c8c2af4-f963-5511-b3c3-330da81f6373`
- Approval fingerprint: `8728149d394cd02c30d1275ff69f21016a997f640c3f02ababd2cbf1903f78df`
- Decision/approver: `approved` / `devon`
- Approval event: `0d994ce6-17fe-48c1-a40c-8aa82d82fb73`
- `unit.authority_approval_id`: exactly the approval ID above
- Action approvals: 0; no action approval was substituted
- Stored authority envelope: unchanged
- Change Manager `origin/main`: still `1f64d0166614574c57663f21dfa33a48682e4a3d`

Readiness then reported `ready` with no reasons while the unit was still Draft/version 1. The proper SYSTEM lifecycle surface transitioned it once:

- Ready idempotency key: `ws64-r4-change-manager-ready-a07b315c-eba9-4e7f-b074-eab22f371c05`
- Transition event: `0cb8a74d-ac75-4070-aeac-67f456305cac`
- Actor/role: `orchestrator-system` / `system`
- State/version: `ready` / 2
- Canonical readiness after transition: `ready`, no reasons
- Dispatch records for the unit: 0

Production dispatch settings were read from the running Orchestrator process without revealing credentials:

- Dispatch enabled: true
- Allowed change classes: only `dependency-update`
- Enabled capabilities: only `repo.edit`
- GitHub App configured: true
- Workflow/ref: `factory-runner-pilot.yml` / `main`
- Failure-signature threshold: 3
- Allowed target repositories:
  - `AlobarQuest/brain`
  - `AlobarQuest/change-manager`
  - `AlobarQuest/infraops-mcp-server`
  - `AlobarQuest/intent-packages`
  - `AlobarQuest/orchestrator`
  - `AlobarQuest/security-standards`

This initial target allowlist was broader than revision 4's approved instruction to enable dispatch for only `AlobarQuest/change-manager`, so execution stopped before dispatch. Devon then explicitly approved the narrow correction below.

The approved correction was to make the effective `dispatch_allowed_target_repositories` set exactly `{AlobarQuest/change-manager}`, while leaving dispatch enabled, allowed change classes exactly `{dependency-update}`, and enabled capabilities exactly `{repo.edit}`. Because settings are process-cached, the environment update was followed by an approved same-image redeploy and fresh readback.

Exact pre-change and approved non-secret environment values for Coolify application `eqj5l7k705fhi12x9i74fqf0`:

| Key | Pre-change | Approved/effective |
| --- | --- | --- |
| `ORCHESTRATOR_DISPATCH_ENABLED` | `true` | unchanged |
| `ORCHESTRATOR_DISPATCH_ALLOWED_CHANGE_CLASSES` | `["dependency-update"]` | unchanged |
| `ORCHESTRATOR_DISPATCH_ENABLED_CAPABILITIES` | `["repo.edit"]` | unchanged |
| `ORCHESTRATOR_DISPATCH_ALLOWED_TARGET_REPOSITORIES` | `["AlobarQuest/orchestrator", "AlobarQuest/brain", "AlobarQuest/security-standards", "AlobarQuest/infraops-mcp-server", "AlobarQuest/intent-packages", "AlobarQuest/change-manager"]` | `["AlobarQuest/change-manager"]` |

Approved mutation sequence executed:

1. Updated only `ORCHESTRATOR_DISPATCH_ALLOWED_TARGET_REPOSITORIES` on production Coolify application `eqj5l7k705fhi12x9i74fqf0` to `["AlobarQuest/change-manager"]`.
2. Preserved the existing environment record and flags: UUID `egdblurkb2lkprjsk92sso0d`, runtime true, build-time false, preview false.
3. Force-redeployed the existing pinned image through Coolify deployment `a12tkyoe7umtlkjf2w8skkey` so process-cached settings reloaded.
4. Waited for terminal Coolify completion and Docker healthy state, then completed all post-change gates below.

Post-change proof:

- Coolify deployment: `a12tkyoe7umtlkjf2w8skkey`, terminal `finished`
- Application/container status: running and healthy
- Image tag: `ghcr.io/alobarquest/orchestrator:a52d3d2fa46fef1bcdc5aa51cc08d10a2b570f82-ws64-authority-amd64`, unchanged
- Container image ID: `sha256:6462e3c396a50e1584d3d50fc79ed275f95e19ae670dab4edd746cf0433422d3`, unchanged
- Repository digest: `sha256:16d07ce00e762b7fe3f6fe6f26b0ad67155efa963bf9a0808e2a4adacd1f66d3`, unchanged
- Alembic: `0014_wsp21_recovery_controls`, unchanged
- `/health/live`: HTTP 200, `status=ok`
- `/health/ready`: HTTP 200, `status=ok`
- Effective dispatch enabled: true
- Effective allowed change classes: exactly `["dependency-update"]`
- Effective enabled capabilities: exactly `["repo.edit"]`
- Effective target repositories: exactly `["AlobarQuest/change-manager"]`
- Unit `4c8c2af4-f963-5511-b3c3-330da81f6373`: Ready/version 2
- Dispatch records for the unit: 0

Rollback was not needed. It remains ready: restore the exact six-repository JSON array shown in the Pre-change column on env UUID `egdblurkb2lkprjsk92sso0d`, redeploy the same pinned image, and repeat the same health/settings/unit gates. These dispatch configuration values contain no secrets; no secret value was read or printed while changing or verifying them.

## Step 9: single dispatch checkpoint

Fresh pre-dispatch verification required and observed:

- Unit: Ready/version 2
- Existing dispatch records: 0
- Change Manager `origin/main`: `1f64d0166614574c57663f21dfa33a48682e4a3d`
- Dispatch enabled: true
- Allowed change classes: exactly `dependency-update`
- Enabled capabilities: exactly `repo.edit`
- Allowed targets: exactly `AlobarQuest/change-manager`
- Orchestrator live/ready: HTTP 200
- Orchestrator repository digest: `sha256:16d07ce00e762b7fe3f6fe6f26b0ad67155efa963bf9a0808e2a4adacd1f66d3`

One SYSTEM dispatch was submitted:

- Dispatch idempotency key: `ws64-r4-change-manager-dispatch-dd33842a-4823-4463-b2ad-1ced2d9f710f`
- Dispatch ID: `14919130-5dd0-438c-8a63-ea65a31832cc`
- Dispatch event: `3fd69311-a056-42c6-a880-56747e987ef3`
- Runner attempt: 1
- Status: `dispatched`
- Target: `AlobarQuest/change-manager`
- Workflow/ref: `factory-runner-pilot.yml` / `main`
- GitHub run: `29416604108`
- GitHub run URL: `https://github.com/AlobarQuest/change-manager/actions/runs/29416604108`
- GitHub event/base: `workflow_dispatch` / `1f64d0166614574c57663f21dfa33a48682e4a3d`

No replay or second dispatch was submitted. Monitoring continues through runner, PR, named Quality, evidence, and verifier adjudication. No merge or close action is authorized.

## Step 9: runner and finalizer result

The correlated runner workflow completed successfully:

- Runner workflow run/job: `29416604108` / `87356212429`
- Terminal conclusion: `success`
- Caller workflow revision: `c88a3199df80ccd8d90f752edc57cc8b93ff6354`
- Installed factory-runner revision: `562fe3cf8e9bc96cacaaf7458842b6d596c0abda`
- Claim: attempt 1, claim ID `c79ae860-9801-4b4f-aa90-ecc1ff4badb1`, claimed by `factory-runner`
- Policy allowed tools: `Read`, `Edit`, `Bash`, and `Glob`
- An attempted unapproved Bash inspection command was denied by the exact-command hook.
- The only authorized commands then executed, in order, were `uv add --dev 'httpx2>=2.6.0'`, `uv sync --locked`, and `uv run make check`.
- The runner check reported Ruff passing, 59 files already formatted, Pyright 0 errors/0 warnings/0 informations, and exactly 105 tests passing.
- Coding terminal subtype: `success`; `is_error=false`
- Classifier: accepted `success`
- Finalizer opened `https://github.com/AlobarQuest/change-manager/pull/26`.

Canonical lifecycle events show one claim and the transitions Ready → Claimed → Executing → Submitted. The unit is `submitted`, version 5, attempt count 1. The claim remains unreleased with no terminal reason while verification is pending.

## Step 10: exact-head pull request and named Quality proof

Pull request 26 was verified independently from GitHub:

- State: open, non-draft, unmerged, mergeable
- Base: `main` at `1f64d0166614574c57663f21dfa33a48682e4a3d`
- Head: `sds/4c8c2af4-attempt-1` at `a8297cf18c76549295bf16ae32466fa40e15f19e`
- Changed files: only `pyproject.toml` and `uv.lock`
- Diff summary: 8 additions, 8 deletions

The repository's push and pull-request triggers each launched the same named Quality job. Both were observed to terminal success:

- Push-triggered Quality run: `29416698842`
- Pull-request-triggered Quality run: `29416701779`
- Named job: `Lint, type-check, and test`
- Both logs ran `make check` and reported Ruff passing, 59 files already formatted, Pyright 0 errors/0 warnings/0 informations, and exactly `105 passed`.

The two runs are duplicate CI observations from the repository's normal event triggers, not duplicate factory dispatches. The dispatch record count remains exactly one.

## Step 11: evidence and verifier blocker

The worker recorded exactly one current AC-006 evidence row:

- Evidence ID: `527d5849-5f5a-49c2-bb7f-b64568c6104d`
- Revision UUID: `f5bfa951-0b21-46d3-a24a-035d105d5a74`
- Unit/attempt: `4c8c2af4-f963-5511-b3c3-330da81f6373` / 1
- Evidence type: `runner.pr.opened`
- Stable PR reference: `https://github.com/AlobarQuest/change-manager/pull/26`
- Source/head revision: `a8297cf18c76549295bf16ae32466fa40e15f19e`
- Payload: the PR/head plus successful results for the exact three authorized runner commands
- Recorded by: `factory-runner`

That row was recorded before named CI completed and therefore does not contain the Quality run name, run ID, or check conclusion required by AC-006. More importantly, the canonical acceptance criterion itself is stored as:

- AC: `AC-006`
- Criterion database UUID: `6682254e-307d-43e8-9b09-0379df80a4ff`
- Evidence type: `automated_check`
- Required evidence: the Change Manager PR's named Quality check must report Ruff, Pyright, and 105 passing tests on the exact head, and dispatch must name `AlobarQuest/change-manager`.

The deployed WS-5.1 evaluator's deterministic vocabulary does not include `automated_check`. Its evaluation order classifies any unrecognized criterion evidence type as `judgment_required` before examining whether evidence is present or sufficient. The verifier service then routes any such result to `awaiting_review`. It cannot produce the plan-required verifier pass adjudication or terminal completion for this criterion, even though the external Quality proof is green.

No verifier request was submitted: doing so after this preflight would knowingly create the wrong canonical lifecycle result. There are currently zero adjudications. Resolving this requires a separately reviewed contract change—either an approved criterion vocabulary the deployed verifier already evaluates, or deployed deterministic evaluator support with an evidence shape that binds the named check. It is not safe to improvise either change during this production run.

## Step 12: merge gate

No merge or close API/command was invoked. Pull request 26 remains open and unmerged. Devon's human merge gate is preserved, but the run cannot honestly proceed to merge review as a completed factory proof until the Step 11 verifier contract blocker is resolved.

## Routine observation repair

One read-only criterion query initially used two incorrect column names and failed without changing state. The model definition was refreshed and the corrected query returned the canonical AC-006 fields above. No production write was attempted by either query.
