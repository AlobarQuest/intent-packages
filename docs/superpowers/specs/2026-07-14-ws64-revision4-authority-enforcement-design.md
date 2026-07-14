# WS-6.4 Revision 4 — Authority Enforcement and Change Manager Proof

**Date:** 2026-07-14  
**Status:** Approved design  
**Target repository:** `AlobarQuest/change-manager`  
**Governing package:** `ws-6.4-dependency-update-fanout`

## 1. Purpose

Continue the six-repository dependency-update fan-out one repository at a time. Prior
attempts and the later validation-harness project do not establish that the six-repository
factory path completed correctly. Each repository remains incomplete until its current
work unit reaches terminal, independently adjudicated state with artifact-matched evidence.

Revision 4 uses `AlobarQuest/change-manager` as the next production proof. Before that unit
is approved or dispatched, repair three defects exposed by the `intent-packages` attempt:

1. Orchestrator accepts a dependency-update authority envelope that declares no mutation.
2. Factory-runner presents `constraints.allowed_commands` as prompt text but gives the coding
   agent unrestricted Bash authority.
3. A coding action may exit the turn loop with a non-success terminal result while its GitHub
   step is successful, causing finalization to mask the coding failure.

This work repairs the authority boundary. It does not revive or retry the cancelled
revision-1 `intent-packages` unit, claim that earlier repositories are complete, automate
merge, or rebuild the abandoned production-validation harness.

## 2. Current Evidence

The failed `intent-packages` run demonstrated the three defects directly:

- the served `allowed_commands` list contained only `make check`;
- attempt 4 nevertheless performed a dependency mutation through unrestricted Bash;
- attempt 5 exhausted its turn limit with terminal subtype `error_max_turns` and
  `is_error: false`, after which finalization reported `no changes to submit`.

The obsolete unit is cancelled. Package revision 3 already has an active approved
decomposition and cannot produce a replacement unit through the supported lifecycle.
Revision 4 is therefore the supported route forward.

The historical documents that label WS-6.4 “6/6 complete” are not current status authority.
They describe earlier attempts, not six trustworthy end-to-end proofs.

## 3. Design Principles

- Authority must be mechanically enforced, not communicated only as prose.
- Invalid authority must fail before a human is asked to approve it.
- The consumer independently validates the authority it receives.
- Existing approved envelopes and fingerprints are immutable.
- The coding agent may edit repository files, but Bash commands are exact and enumerated.
- The runner, not agent-writable workspace state, owns finalization authority.
- Semantic coding failure must remain attributable as coding failure.
- Every repository keeps its own human merge gate and named CI gate.
- A routine operator or tool invocation mistake is recoverable. Incorrect factory behavior is
  a stop condition.

## 4. Shared Authority Contract

### 4.1 New constraint

Add `constraints.mutation_commands` to the shared Orchestrator/factory-runner envelope.

For an envelope where:

- `change_class == "dependency-update"`; and
- `capabilities["repo.edit"] == "allowed"`;

both systems require:

1. `capabilities["command.run"] == "allowed"`;
2. `constraints.allowed_commands` is a non-empty ordered list of non-empty strings;
3. `constraints.mutation_commands` is a non-empty ordered list of non-empty strings; and
4. every mutation command appears in `allowed_commands`.

`mutation_commands` declares which authorized commands are expected to change the target.
It does not attempt to infer shell semantics or prove that a command really mutates. The
clean-clone preflight and human review prove that claim.

The complete constraints map remains fingerprinted by value. Adding the field therefore
changes every new envelope fingerprint that carries it. Existing units retain their stored
envelopes and fingerprints; no data migration or in-place rewrite is permitted.

### 4.2 Coordinated contract update

Update both repositories together:

- byte-identical `tests/fixtures/runner_authority_envelope.json`;
- pinned canonical contract SHA-256 constants;
- exact constraint-key assertions;
- Orchestrator ADR 0001; and
- consumer and producer validation tests.

The shared fixture must use a real mutation-first, verifier-last example. `make check` alone
must no longer be accepted as a dependency-update `repo.edit` envelope.

## 5. Orchestrator Admission and Human Review

### 5.1 Proposal admission

Orchestrator validates the new constraint during decomposition proposal submission, before
the proposal is persisted or displayed for approval. Invalid payloads receive stable,
specific domain error codes for:

- missing or malformed `allowed_commands`;
- missing or malformed `mutation_commands`;
- mutation commands outside `allowed_commands`; and
- missing `command.run` capability.

### 5.2 Dispatch defense

Dispatch revalidates the stored envelope. A legacy dependency-update unit that lacks the new
contract is not rewritten or grandfathered into execution; it fails closed with a stable
blocked reason. This prevents an old approved-but-non-executable envelope from reaching a
runner after the repair is deployed.

### 5.3 Approval surfaces

Both decomposition approval and per-unit authority approval surfaces display the complete,
normalized authority envelope in a readable form, including:

- target repository;
- change class;
- capabilities;
- `allowed_commands` in order;
- `mutation_commands` in order;
- budgets;
- conformance claim; and
- authority fingerprint.

The UI must not reduce authority review to a fingerprint-only decision.

## 6. Factory-Runner Enforcement

### 6.1 Consumer validation

Factory-runner mirrors the Orchestrator validation rules before it claims a unit. Any
contract violation ends preparation without starting the coding action.

### 6.2 Exact Bash boundary

The runner generates a policy file outside the repository checkout from the approved
`allowed_commands` list. The coding action receives:

- repository read/search tools;
- repository edit tools when `repo.edit` is allowed; and
- Bash only under a runner-owned `PreToolUse` command hook.

For every Bash tool call, the hook reads `tool_input.command` and permits it only when the
string exactly equals one approved command. Prefixes, suffixes, pipelines, redirections,
compound commands, environment-variable prefixes, embedded newlines, and unlisted commands
are denied. Hook absence, malformed input, malformed policy, or hook failure also denies.

The hook is the enforcement boundary. Command-scoped Bash permission rules may be emitted as
defense in depth, but they are not the sole authority check.

The generated policy and run metadata live outside the checkout. The coding agent cannot
change the authority used by finalization. Finalization re-fetches the runner brief and
requires the original authority fingerprint and command lists to match before executing any
command.

### 6.3 Finalization

The runner executes `allowed_commands` in their approved order using shell semantics that
preserve the authored command string. Mutation commands precede the final verifier. Only
after every command succeeds does the runner inspect the tree, create its commit, push the
branch, open the pull request, and submit evidence.

No worker, action, or Orchestrator path may merge the pull request.

## 7. Coding-Result Classification

Add a runner CLI command that classifies the coding action's `execution_file` before
finalization. It must find one well-formed terminal result and accept only a successful
terminal subtype with `is_error` not true.

It fails closed for:

- `error_max_turns` even if `is_error` is false;
- any other error subtype;
- `is_error: true`;
- missing or malformed output;
- no terminal result; or
- conflicting terminal results.

Workflow order becomes:

```text
prepare → coding action → classify coding result → finalize
```

Finalization runs only when the coding step and classifier succeed. Classifier failure is
reported through the existing bounded `coding_action_failed` reason. A genuine successful
coding run that leaves no diff remains a finalization failure; this preserves the existing
change-detection guard.

## 8. Revision 4 Change Manager Unit

### 8.1 Proven outcome

The unit outcome is:

> Raise `AlobarQuest/change-manager`'s direct development dependency floor for `httpx2` from
> `2.5.0` to `2.6.0` in `[dependency-groups].dev` of `pyproject.toml`, regenerate `uv.lock`
> so `httpx2` and its `httpcore2` dependency resolve to `2.6.0`, and prove the repository's
> full quality gate passes.

No application or test source change is expected.

### 8.2 Authority commands

The authored envelope uses:

```yaml
constraints:
  target_repository: AlobarQuest/change-manager
  allowed_commands:
    - "uv add --dev 'httpx2>=2.6.0'"
    - "uv sync --locked"
    - "uv run make check"
  mutation_commands:
    - "uv add --dev 'httpx2>=2.6.0'"
```

`constraints.work_unit_id` remains server-owned and is omitted from the proposal.

### 8.3 Preflight evidence

The exact ordered list ran twice back-to-back in a disposable clean clone of
`change-manager` commit `25fa8da`.

Both passes succeeded. Each verifier run executed:

- Ruff lint: passed;
- Ruff formatting: 59 files formatted correctly;
- Pyright: 0 errors, 0 warnings, 0 information messages; and
- Pytest: 105 passed.

The persistent diff contains only `pyproject.toml` and `uv.lock`. It updates the direct
`httpx2` floor, the corresponding lockfile requirement metadata, and the resolved
`httpx2`/`httpcore2` versions and artifacts. Running the list a second time is idempotent and
leaves the same intended diff.

## 9. Revision 4 Lifecycle

1. Land and deploy the coordinated authority repair through ordinary reviewed PRs.
2. Revise the governing package from approved revision 3 to draft revision 4.
3. Update revision 4 to describe the repository-by-repository proof posture and the new
   shared authority contract.
4. Validate the package and transition it to `ready_for_review`.
5. Devon approves the exact revision/hash and merges its PR.
6. Register a fresh production intake for revision 4.
7. Submit a one-unit decomposition mapping AC-006 to the `change-manager` unit and retain
   every other acceptance criterion with explicit rationale.
8. Devon reviews and approves the decomposition.
9. Compute conformance from current `change-manager` state.
10. Devon reviews and approves the unit's complete authority envelope.
11. Drive the unit to Ready and dispatch exactly once.
12. Observe claim, execution, branch, pull request, named CI, evidence submission, verifier
    adjudication, and terminal unit state.
13. Devon alone reviews and merges or closes the pull request.
14. Record the observed outcome before selecting the next repository.

No prior revision's terminal facts are copied forward as proof. Revision 4 maps only AC-006;
the remaining criteria stay retained and incomplete until separately re-proven.

## 10. Error Handling and Stop Conditions

Recover and continue after routine operator/tool errors such as:

- a misspelled local command or API route;
- a local interpreter or wrapper mismatch;
- an idempotent read retry; or
- a transient tool invocation failure that does not mutate factory state.

Before recovery, refresh live state and prove whether the failed invocation mutated anything.

Stop when the factory process behaves incorrectly, including:

- an invalid envelope reaches human approval or dispatch;
- an off-envelope Bash command executes;
- the hook or classifier fails open;
- target routing differs from `AlobarQuest/change-manager`;
- coding failure is attributed as finalization failure;
- a claim or lease is stranded;
- evidence is missing, misattributed, or accepted from the worker as canonical completion;
- named CI does not execute its real tools/tests;
- any automatic merge path appears; or
- approved authority changes without a new fingerprint and human approval.

On a stop, preserve the unit and external state, record exact evidence, repair the responsible
component through an ordinary reviewed PR, deploy if needed, and resume only through a valid
lifecycle transition. Do not increase attempt budgets merely to repeat a deterministic defect.

## 11. Testing and Verification

### Orchestrator

- Proposal validation rejects every malformed or incomplete mutation declaration.
- Valid mutation-first/verifier-last envelopes are accepted.
- Dispatch rejects legacy incomplete dependency-update envelopes.
- Mutation command content and order affect the fingerprint.
- Both human review pages render the complete normalized envelope.
- Shared fixture and contract digest match factory-runner.
- Full repository gate passes with a nonzero collected-test count.

### Factory-runner

- Consumer validation mirrors Orchestrator.
- No unrestricted coding-phase Bash survives policy generation.
- Exact commands pass; modified, compound, redirected, prefixed, newline-containing, and
  unlisted commands fail.
- Missing/malformed policy and hook failure deny execution.
- Checkout edits cannot alter finalization authority.
- Coding-result fixtures cover success, `error_max_turns` with false `is_error`, true
  `is_error`, malformed/missing result, and conflicting terminal results.
- Workflow tests prove classification failure skips finalization and reports
  `coding_action_failed`.
- Full repository gate passes.

### Integrated proof

- Orchestrator and factory-runner use byte-identical contract fixtures.
- The repaired Orchestrator image is verified by commit, immutable digest, architecture,
  migration head, and readiness before revision 4 dispatch.
- The merged factory-runner revision is the one installed by the production workflow.
- The `change-manager` pull request's named Quality check succeeds on its exact head commit
  and reports 105 tests, not merely exit code zero.
- Verifier adjudication, not worker output, causes terminal completion.

## 12. Alternatives Rejected

### Prompt plus command-scoped Bash rules only

Smaller, but permission rules alone are not the durable deny boundary and do not protect
against inherited broader settings, compound shell syntax, or mutable finalization state.

### Hard-coded mutator catalog

Orchestrator could recognize `uv add`, `npm update`, and a fixed set of known mutators. That
couples a generic authority service to ecosystem-specific commands and still cannot prove
the command produces the intended diff.

### Remove Bash and expose a command broker

A runner-owned `RunAuthorizedCommand(command_id)` tool backed by immutable argv would provide
the strongest boundary and audit trail. It is a larger runtime redesign than required for
this repair. The exact-match hook closes the observed hole without introducing that new
subsystem.

## 13. Documentation Consequences

After the fixes are verified, propose these durable captures if they are not already present:

- Orchestrator invariant: dependency-update `repo.edit` authority requires a fingerprinted,
  non-empty mutation declaration that is a subset of the full command list.
- Factory-runner invariant: prompt text and action step success are not authority or semantic
  completion; exact PreToolUse enforcement and terminal-result classification are required.
- ADR 0001 update: `mutation_commands` is part of the shared envelope contract.

The false historical “6/6 complete” status should be corrected in the program documentation
only as a separately reviewed documentation change. Revision 4 must not silently rewrite
history while implementing the runtime repair.
