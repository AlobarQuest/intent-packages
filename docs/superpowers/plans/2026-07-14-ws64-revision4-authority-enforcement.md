# WS-6.4 Revision 4 Authority Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce dependency-update mutation authority across Orchestrator and factory-runner, then use package revision 4 to prove the repaired path against `AlobarQuest/change-manager`.

**Architecture:** Orchestrator becomes the producer-side admission authority for a new fingerprinted `constraints.mutation_commands` field and exposes the complete envelope to human reviewers. Factory-runner mirrors the validation, generates a runner-owned fail-closed Bash hook outside the checkout, re-fetches authority before finalization, and classifies the coding action's terminal result before allowing finalization. After reviewed merges and verified deployment, revision 4 creates one `change-manager` unit with an already-proven mutation-first command sequence.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Pydantic, Typer, Jinja2, pytest, GitHub Actions YAML, Claude Code `PreToolUse` command hooks, uv.

## Global Constraints

- Treat historical “6/6 complete” documents as non-authoritative status; every repository remains incomplete until separately re-proven.
- Existing approved authority envelopes and fingerprints are immutable; do not migrate or rewrite them.
- `constraints.work_unit_id` remains server-owned and must not appear in authored proposals.
- `constraints.mutation_commands` is required for `change_class == "dependency-update"` with `repo.edit == "allowed"` and must be a non-empty ordered subset of `allowed_commands`.
- Invalid authority fails before human approval and again at dispatch/runner consumption.
- Bash authorization is an exact string match enforced by a runner-owned `PreToolUse` hook; prompt text is not enforcement.
- Hook absence, malformed input/policy, policy mismatch, or hook failure denies execution.
- Pin `anthropics/claude-code-base-action` to commit `e8132bc5e637a42c27763fc757faa37e1ee43b34`, whose reviewed manifest installs Claude Code `1.0.88`; do not use `@beta` at runtime.
- The target caller pins the reusable factory-runner workflow to its merged commit and passes that same commit as the required runner-install revision.
- Coding terminal subtypes other than success, including `error_max_turns` with `is_error: false`, are coding failures and must skip finalization.
- Finalization derives commands from a freshly fetched envelope matching the originally approved authority fingerprint; it does not trust agent-writable command state.
- No worker, workflow, API, CLI, Orchestrator path, or agent may merge a pull request.
- Devon alone approves package revision 4, the decomposition, per-unit authority, dispatch enablement, and every merge.
- Recover routine agent/tool mistakes after proving whether they mutated state; stop only when the factory process under test behaves incorrectly.
- The revision-4 target is exactly `AlobarQuest/change-manager`.
- The exact ordered commands are `uv add --dev 'httpx2>=2.6.0'`, `uv sync --locked`, then `uv run make check`.
- `mutation_commands` contains only `uv add --dev 'httpx2>=2.6.0'`.
- The `change-manager` named Quality check must report Ruff, Pyright, and 105 passing tests on the exact pull-request head.

---

## Execution Workspaces

At execution time, use `superpowers:using-git-worktrees` to create these exact isolated workspaces:

- `/Users/devon/Projects/orchestrator-ws64-authority-enforcement`
- `/Users/devon/Projects/factory-runner-ws64-authority-enforcement`
- `/Users/devon/Projects/change-manager-ws64-runner-pin` for the prerequisite caller-pin PR only

Use the existing `/Users/devon/Projects/intent-packages` checkout on branch
`chore/ws64-revision4-change-manager` for the package changes. Never modify the dirty
`/Users/devon/Projects/orchestrator` checkout directly. Before implementation, run `uv sync`
and `make check` in each new worktree to establish a clean baseline.

---

## File Map

### `AlobarQuest/orchestrator`

- Create `src/orchestrator/kernel/runner_authority.py`: pure shared-envelope validation with stable violation codes.
- Modify `src/orchestrator/services/decomposition.py`: invoke producer-side validation before proposal persistence.
- Modify `src/orchestrator/services/dispatch.py`: block legacy/incomplete dependency-update envelopes before GitHub dispatch.
- Modify `src/orchestrator/services/packages.py`: reject invalid dependency-update authority at the approval service boundary.
- Modify `src/orchestrator/web.py`: expose normalized authority in review projections and add an explicit authority-approval form route.
- Modify `src/orchestrator/templates/decomposition_proposal.html`: render each proposed unit's complete authority.
- Modify `src/orchestrator/templates/unit.html`: render the stored unit authority and provide the authority-specific approval action.
- Modify `tests/services/test_decomposition.py`: proposal admission regression tests.
- Modify `tests/services/test_dispatch.py`: dispatch defense regression tests.
- Modify `tests/services/test_package_registration.py`: authority-approval service regression tests.
- Modify `tests/web/test_decomposition_review.py`: complete-envelope rendering tests.
- Modify `tests/web/test_human_actions.py`: explicit authority-approval form tests.
- Modify `tests/fixtures/runner_authority_envelope.json`: shared contract fixture.
- Modify `tests/contract/test_runner_envelope_contract.py`: new key, fingerprint, and digest assertions.
- Modify `docs/decisions/0001-work-unit-authority-envelope-contract.md`: contract revision.
- Modify `CLAUDE.md`: verified non-obvious invariant.

### `AlobarQuest/factory-runner`

- Modify `src/factory_runner/models.py`: expose `mutation_commands` on validated permissions.
- Modify `src/factory_runner/authority.py`: consumer validation and exact policy inputs.
- Create `src/factory_runner/command_policy.py`: policy generation, settings generation, policy loading, and exact Bash decision.
- Create `src/factory_runner/coding_result.py`: terminal execution-result classifier.
- Modify `src/factory_runner/cli.py`: prepare policy/settings, hook command, classifier command, and authoritative finalization refresh.
- Modify `.github/workflows/factory-runner.yml`: pass settings, classify result, and gate finalization/reporting.
- Modify `tests/test_authority.py`: mirrored constraint validation.
- Create `tests/test_command_policy.py`: fail-closed hook policy tests.
- Create `tests/test_coding_result.py`: terminal-result classifier tests.
- Modify `tests/test_cli.py`: prepare/finalize authority refresh tests.
- Modify `tests/test_workflow_contract.py`: workflow ordering and failure-attribution tests.
- Modify `tests/fixtures/runner_authority_envelope.json`: byte-identical shared fixture.
- Modify `tests/test_orchestrator_envelope_contract.py`: new contract key and digest.
- Modify `CLAUDE.md`: command-boundary and terminal-result invariants.

### `AlobarQuest/intent-packages`

- Modify `packages/ws-6.4-dependency-update-fanout/package.yaml`: revision 4 intent and corrected status language.
- Modify `packages/ws-6.4-dependency-update-fanout/lineage.yaml`: only through the lifecycle CLI.
- Create `docs/superpowers/evidence/2026-07-14-ws64-revision4-change-manager-preflight.md`: reproducible preflight evidence.

### `AlobarQuest/change-manager` prerequisite configuration

- Modify `.github/workflows/factory-runner-pilot.yml` in a separate reviewed PR: pin the
  reusable workflow and `runner_revision` input to the same merged factory-runner commit.
- Do not include the dependency update in this prerequisite PR.

---

### Task 1: Orchestrator Shared Authority Validator and Contract Fixture

**Files:**
- Create: `src/orchestrator/kernel/runner_authority.py`
- Modify: `tests/services/test_decomposition.py`
- Modify: `tests/fixtures/runner_authority_envelope.json`
- Modify: `tests/contract/test_runner_envelope_contract.py`
- Modify: `docs/decisions/0001-work-unit-authority-envelope-contract.md`

**Interfaces:**
- Produces: `dependency_update_authority_violation(envelope: AuthorityEnvelope) -> AuthorityViolation | None`
- Produces: `AuthorityViolation(code: str, message: str, remediation: str)`
- Consumed by: decomposition admission in Task 2 and dispatch defense in Task 2.

- [ ] **Step 1: Create the failing validator tests**

Add focused tests covering no commands, no mutation declaration, blank/non-string entries,
mutation not in the full list, missing `command.run`, and a valid command list:

```python
@pytest.mark.parametrize(
    ("constraints", "code"),
    [
        ({}, "authority_allowed_commands_invalid"),
        ({"allowed_commands": ["make check"]}, "authority_mutation_commands_invalid"),
        (
            {
                "allowed_commands": ["uv sync", "make check"],
                "mutation_commands": ["uv lock"],
            },
            "authority_mutation_command_not_allowed",
        ),
    ],
)
def test_dependency_update_authority_rejects_non_executable_contract(
    constraints: dict[str, object], code: str
) -> None:
    envelope = normalize_authority(
        {
            "change_class": "dependency-update",
            "capabilities": {"repo.edit": "allowed", "command.run": "allowed"},
            "constraints": constraints,
        }
    )

    violation = dependency_update_authority_violation(envelope)

    assert violation is not None
    assert violation.code == code
```

- [ ] **Step 2: Run the focused tests and prove red**

Run:

```bash
.venv/bin/pytest tests/services/test_decomposition.py tests/contract/test_runner_envelope_contract.py -q
```

Expected: collection or assertion failure because `runner_authority.py`,
`mutation_commands`, and the new fixture digest do not exist.

- [ ] **Step 3: Implement the pure validator**

Create the immutable result type and one validation function. The function returns `None`
outside the exact dependency-update + repo.edit case and otherwise validates the four
contract clauses in deterministic order:

```python
from dataclasses import dataclass

from orchestrator.kernel.authority import AuthorityEnvelope


@dataclass(frozen=True)
class AuthorityViolation:
    code: str
    message: str
    remediation: str


def dependency_update_authority_violation(
    envelope: AuthorityEnvelope,
) -> AuthorityViolation | None:
    if envelope.change_class != "dependency-update":
        return None
    if envelope.level_for("repo.edit") != "allowed":
        return None
    if envelope.level_for("command.run") != "allowed":
        return AuthorityViolation(
            "authority_command_run_required",
            "dependency-update repo.edit authority requires command.run",
            "allow command.run and declare the exact command lists",
        )
    allowed = _non_empty_string_list(envelope.constraints.get("allowed_commands"))
    if allowed is None:
        return AuthorityViolation(
            "authority_allowed_commands_invalid",
            "constraints.allowed_commands must be a non-empty list of non-empty strings",
            "declare the complete ordered command list",
        )
    mutations = _non_empty_string_list(envelope.constraints.get("mutation_commands"))
    if mutations is None:
        return AuthorityViolation(
            "authority_mutation_commands_invalid",
            "constraints.mutation_commands must be a non-empty list of non-empty strings",
            "declare the ordered commands expected to mutate the dependency",
        )
    if any(command not in allowed for command in mutations):
        return AuthorityViolation(
            "authority_mutation_command_not_allowed",
            "every mutation command must also appear in constraints.allowed_commands",
            "add the mutation command to allowed_commands without changing its spelling",
        )
    return None
```

The private list parser must reject booleans, mappings, blank strings, and tuples; it returns
`tuple[str, ...] | None` and preserves order.

- [ ] **Step 4: Update the golden shared envelope**

Use this exact constraint payload in the Orchestrator fixture:

```json
"constraints": {
  "allowed_commands": [
    "uv add --dev 'httpx2>=2.6.0'",
    "uv sync --locked",
    "uv run make check"
  ],
  "mutation_commands": ["uv add --dev 'httpx2>=2.6.0'"],
  "target_repository": "AlobarQuest/change-manager",
  "work_unit_id": "__WORK_UNIT_ID__"
}
```

Update `TARGET_REPOSITORY`, the exact key-set assertion, and `CONTRACT_SHA256` from:

```bash
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path("tests/fixtures/runner_authority_envelope.json")
payload = json.loads(p.read_text())
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
print(hashlib.sha256(canonical.encode()).hexdigest())
PY
```

- [ ] **Step 5: Update ADR 0001**

Document that `mutation_commands` is fingerprinted, ordered, required only for
dependency-update `repo.edit`, a subset declaration rather than semantic proof, and a
coordinated cross-repository contract field. Explicitly state that existing stored envelopes
are not rewritten.

- [ ] **Step 6: Run the focused tests and prove green**

Run:

```bash
.venv/bin/pytest tests/services/test_decomposition.py tests/contract/test_runner_envelope_contract.py -q
```

Expected: all selected tests pass with a nonzero collected-test count.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/orchestrator/kernel/runner_authority.py \
  tests/services/test_decomposition.py \
  tests/fixtures/runner_authority_envelope.json \
  tests/contract/test_runner_envelope_contract.py \
  docs/decisions/0001-work-unit-authority-envelope-contract.md
git commit -m "feat: define dependency mutation authority contract"
```

---

### Task 2: Orchestrator Proposal Admission, Dispatch Defense, and Human Review

**Files:**
- Modify: `src/orchestrator/services/decomposition.py`
- Modify: `src/orchestrator/services/dispatch.py`
- Modify: `src/orchestrator/services/packages.py`
- Modify: `src/orchestrator/web.py`
- Modify: `src/orchestrator/templates/decomposition_proposal.html`
- Modify: `src/orchestrator/templates/unit.html`
- Modify: `tests/services/test_decomposition.py`
- Modify: `tests/services/test_dispatch.py`
- Modify: `tests/services/test_package_registration.py`
- Modify: `tests/web/test_decomposition_review.py`
- Modify: `tests/web/test_human_actions.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `dependency_update_authority_violation()` from Task 1.
- Produces: dispatch reason codes identical to validator violation codes.
- Produces: `POST /review/units/{unit_id}/authority-approval` for explicit human authority approval.

- [ ] **Step 1: Write failing service tests**

Add a decomposition test asserting invalid authority raises its exact `DomainError.code`
before proposal persistence, and a dispatch test asserting a legacy approved unit yields a
skipped record with `reason_code == "authority_mutation_commands_invalid"` and zero GitHub
calls. Add service tests asserting `record_approval(subject_type="authority")` rejects that
same legacy envelope with zero Approval/Event writes, while valid authority and existing action
approval behavior remain accepted.

- [ ] **Step 2: Write failing web tests**

Assert the proposal page and unit page contain all of:

```text
AlobarQuest/change-manager
dependency-update
uv add --dev 'httpx2>=2.6.0'
uv sync --locked
uv run make check
mutation_commands
```

Add a POST test for `/review/units/{id}/authority-approval` proving the persisted approval has
`subject_type == "authority"`, `subject_revision_or_fingerprint` equal to the unit authority
fingerprint, the human actor, the submitted reason, a matching unit version, and a stored
`authority_approval_id`. Add a legacy-invalid-envelope test proving the form is not rendered,
the POST is rejected with the validator's bounded reason, and no approval or event is written.
Keep the existing action-approval route and semantics unchanged.

- [ ] **Step 3: Run the tests and prove red**

Run:

```bash
.venv/bin/pytest \
  tests/services/test_decomposition.py \
  tests/services/test_dispatch.py \
  tests/services/test_package_registration.py \
  tests/web/test_decomposition_review.py \
  tests/web/test_human_actions.py -q
```

Expected: failures for missing producer/dispatch validation, missing envelope rendering, and
missing authority-specific route.

- [ ] **Step 4: Wire proposal admission**

At the end of `_validate_unit_constraints()`, build the exact payload that will be persisted
with `_authority_payload(unit)`, normalize that payload once, and call the Task 1 validator on
that normalized envelope. Stamp and persist this same validated payload; do not separately
trust `unit.authority`. Add a regression test where `authority` and `authority_payload` diverge
and prove the persisted payload is the one rejected. Map a violation directly to:

```python
raise DomainError(violation.code, violation.message, violation.remediation)
```

This must execute before the proposal or proposed units are flushed.

- [ ] **Step 5: Wire dispatch defense**

In `_blocked_reason()`, normalize the unit authority once, keep the existing readiness,
approval, capability, routing, and conformance order, then return the validator code before
conformance admission:

```python
envelope = normalize_authority(unit.authority)
violation = dependency_update_authority_violation(envelope)
if violation is not None:
    return violation.code
```

Do not mutate the unit or fingerprint.

- [ ] **Step 6: Render normalized authority on both review pages**

Add `authority` to each projection as an ordinary dictionary suitable for Jinja rendering.
Render capabilities, budgets, change class, conformance, constraints, and fingerprint. Assert
every field, ordered commands, and HTML escaping in the web tests. Use tables/lists rather
than a one-line JSON blob so Devon can review command order without reconstructing it. For an
invalid legacy envelope, render the bounded validator reason and no authority-approval form.

- [ ] **Step 7: Add explicit authority approval route**

Generate a separate CSRF/idempotency action named `authority_approval` and implement:

```python
@router.post("/units/{unit_id}/authority-approval")
def approve_authority(...):
    _human(actor)
    unit = get_unit(session, unit_id)
    envelope = normalize_authority(unit.authority)
    violation = dependency_update_authority_violation(envelope)
    if violation is not None:
        raise DomainError(violation.code, violation.message, violation.remediation)
    _require_form(
        request,
        actor,
        unit_id,
        "authority_approval",
        csrf_token,
        idempotency_key,
        confirm,
    )
    record_approval(
        session,
        unit_id=unit_id,
        subject_type="authority",
        actor_id=actor.actor_id,
        actor_role=actor.role,
        reason=reason,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
    )
    session.commit()
    return _redirect(unit_id)
```

In `services/packages.py`, make `record_approval()` invoke the same validator after loading
the locked unit whenever `subject_type == "authority"`, before fingerprint derivation or any
approval/event write. Add focused service tests for invalid legacy authority, valid authority,
and action approval remaining unchanged. This prevents alternate API/CLI callers from
bypassing the web route. The existing `_approval_fingerprint()` continues to derive
`subject_revision_or_fingerprint`; do not add a redundant parameter. The template labels the
action “Approve this authority envelope” and places it
immediately after the rendered envelope only for a valid envelope. Do not repurpose or delete
action approval.

- [ ] **Step 8: Add the verified Orchestrator invariant**

Append below the managed standards block:

```text
Dependency-update repo.edit authority is not executable unless the fingerprinted envelope
declares a non-empty mutation_commands list that is an ordered subset of allowed_commands.
Proposal admission and dispatch both enforce this; existing approved envelopes are never
rewritten to comply.
```

- [ ] **Step 9: Run focused and full verification**

Run:

```bash
.venv/bin/pytest \
  tests/services/test_decomposition.py \
  tests/services/test_dispatch.py \
  tests/services/test_package_registration.py \
  tests/web/test_decomposition_review.py \
  tests/web/test_human_actions.py -q
make check
```

Expected: focused tests pass; full gate reports real Ruff, Pyright, and a nonzero pytest
collection with no failures.

- [ ] **Step 10: Commit Task 2**

```bash
git add src/orchestrator/services/decomposition.py \
  src/orchestrator/services/dispatch.py \
  src/orchestrator/services/packages.py \
  src/orchestrator/web.py \
  src/orchestrator/templates/decomposition_proposal.html \
  src/orchestrator/templates/unit.html \
  tests/services/test_decomposition.py \
  tests/services/test_dispatch.py \
  tests/services/test_package_registration.py \
  tests/web/test_decomposition_review.py \
  tests/web/test_human_actions.py \
  CLAUDE.md
git commit -m "feat: enforce mutation authority before dispatch"
```

---

### Task 3: Factory-Runner Consumer Validation and Shared Contract

**Files:**
- Modify: `src/factory_runner/models.py`
- Modify: `src/factory_runner/authority.py`
- Modify: `tests/test_authority.py`
- Modify: `tests/fixtures/runner_authority_envelope.json`
- Modify: `tests/test_orchestrator_envelope_contract.py`

**Interfaces:**
- Produces: `RunnerPermissions.mutation_commands: tuple[str, ...]`.
- Produces: `RunnerPermissions.allowed_commands: tuple[str, ...]` after mirrored validation.
- Consumed by: command policy generation in Task 4.

- [ ] **Step 1: Copy the golden fixture byte-for-byte**

After Task 1, copy the Orchestrator fixture into factory-runner and verify:

```bash
cmp \
  /Users/devon/Projects/orchestrator-ws64-authority-enforcement/tests/fixtures/runner_authority_envelope.json \
  tests/fixtures/runner_authority_envelope.json
```

Expected: exit 0 and no output. Use the same canonical SHA-256 constant.

- [ ] **Step 2: Write mirrored failing tests**

Mirror every producer validation case. Add assertions that a valid envelope returns:

```python
assert permissions.allowed_commands == (
    "uv add --dev 'httpx2>=2.6.0'",
    "uv sync --locked",
    "uv run make check",
)
assert permissions.mutation_commands == ("uv add --dev 'httpx2>=2.6.0'",)
```

- [ ] **Step 3: Run the tests and prove red**

Run:

```bash
.venv/bin/pytest tests/test_authority.py tests/test_orchestrator_envelope_contract.py -q
```

Expected: failures because the model and consumer do not expose or validate mutation commands.

- [ ] **Step 4: Implement mirrored consumer validation**

Add `mutation_commands` to `RunnerPermissions`. Replace `_validate_commands()` with a helper
that returns both tuples and raises stable `AuthorityError` messages for the same invalid
shapes as Orchestrator. Preserve exact strings and order.

The validation call becomes:

```python
allowed_commands, mutation_commands = _validate_commands(envelope)
```

and both fields are returned on `RunnerPermissions`.

- [ ] **Step 5: Run the tests and prove green**

Run:

```bash
.venv/bin/pytest tests/test_authority.py tests/test_orchestrator_envelope_contract.py -q
```

Expected: all selected tests pass and the fixture digest matches Orchestrator.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/factory_runner/models.py \
  src/factory_runner/authority.py \
  tests/test_authority.py \
  tests/fixtures/runner_authority_envelope.json \
  tests/test_orchestrator_envelope_contract.py
git commit -m "feat: validate dependency mutation authority"
```

---

### Task 4: Factory-Runner Exact Bash Policy and Authoritative Finalization

**Files:**
- Create: `src/factory_runner/command_policy.py`
- Modify: `src/factory_runner/cli.py`
- Create: `tests/test_command_policy.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `write_tool_policy(policy_dir: Path, checkout: Path, allowed_commands: tuple[str, ...], fingerprint: str) -> tuple[Path, Path]`, returning policy and Claude settings paths.
- Produces: `authorize_tool(policy_path: Path, hook_input: Mapping[str, object]) -> tuple[bool, str]`.
- Produces CLI: `factory-runner authorize-tool --policy-file PATH`, reading one hook JSON object from stdin and exiting 0 only for an exact authorized Bash string or an Edit path contained by the resolved checkout root; denial exits 2.
- Consumed by: GitHub workflow in Task 5.

- [ ] **Step 1: Write failing pure-policy tests**

Use one approved command and parametrize denied variants:

```python
@pytest.mark.parametrize(
    "command",
    [
        "uv sync --locked && git push",
        "uv sync --locked | tee output.txt",
        "uv sync --locked > output.txt",
        "FOO=bar uv sync --locked",
        "uv sync --locked\nwhoami",
        "uv sync --locked ",
        "uv sync",
        "whoami",
    ],
)
def test_authorize_tool_denies_any_non_exact_bash(command: str, tmp_path: Path) -> None:
    policy, _settings = write_tool_policy(
        tmp_path,
        tmp_path / "checkout",
        ("uv sync --locked",),
        "fingerprint-1",
    )

    allowed, _reason = authorize_tool(
        policy,
        {"tool_name": "Bash", "tool_input": {"command": command}},
    )

    assert allowed is False
```

Also cover exact allow, missing file, invalid JSON, wrong fingerprint shape, missing command,
and non-Bash input. Preserve duplicate commands and their order because the shared contract
does not forbid them.

Add Edit-boundary cases: an existing non-Git file in the checkout is allowed; absolute/relative
paths outside it, the policy/settings/run metadata, `..` traversal, a symlink escape, and every
path within the resolved checkout `.git` subtree are denied. Cover `.git/config`, `.git/hooks`,
`.git/refs`, and `.git/index`. Use resolved paths and fail closed when the target or its nearest
existing parent cannot be resolved safely.

- [ ] **Step 2: Write failing CLI exit-code tests**

Invoke `authorize-tool` with the exact Claude Code hook JSON shape on stdin. Assert exact Bash
and in-checkout Edit requests exit 0 with no sensitive output; every denial exits 2 and emits
a bounded reason to stderr.

- [ ] **Step 3: Run policy tests and prove red**

Run:

```bash
.venv/bin/pytest tests/test_command_policy.py tests/test_cli.py -q
```

Expected: failures because the policy module, CLI command, and settings output do not exist.

- [ ] **Step 4: Implement protected policy/settings generation**

Create a runner-owned policy directory outside the target checkout. Write the policy as
canonical JSON with mode `0o400`:

```json
{
  "authority_fingerprint": "0f7ef81ecfab22d2a7b8258e94a670f414067d7298f5a5e71b66ade70d7b6f31",
  "allowed_commands": ["uv sync --locked"],
  "checkout_root": "/home/runner/work/change-manager/change-manager"
}
```

Mode `0o400` is defense in depth, not the immutability boundary: the Edit hook below prevents
the model from replacing policy/settings/run metadata or writing anywhere outside the
checkout. Write Claude settings beside the policy with separate `PreToolUse` matchers for
`Bash` and `Edit`; both invoke the installed CLI and the absolute, shell-quoted policy path:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "factory-runner authorize-tool --policy-file '<absolute path>'"
          }
        ]
      },
      {
        "matcher": "Edit",
        "hooks": [
          {
            "type": "command",
            "command": "factory-runner authorize-tool --policy-file '<absolute path>'"
          }
        ]
      }
    ]
  }
}
```

Reject blank approved commands during generation; preserve duplicates and order. Do not write
either file in the target checkout.

- [ ] **Step 5: Implement fail-closed hook decision**

Parse one JSON object and load a well-formed policy. For `Bash`, require a string
`tool_input.command` and use exact Python string membership; never parse or normalize it. For
`Edit`, require a string `tool_input.file_path`, resolve it against the checkout, require
containment within the resolved checkout root, and reject containment within the resolved
checkout `.git` subtree. Deny all other hooked tool names.

The CLI must use exit 2 for every denial, because Claude Code treats exit 1 as non-blocking.

- [ ] **Step 6: Integrate policy into prepare-run**

Generate policy/settings after authority validation and before the claim. Remove only
agent-authoritative command fields from `run.json`; preserve claim, lease, version, and other
lifecycle metadata. Save the authority fingerprint and policy digest in `run.json`. Emit:

```python
_write_github_output(
    prompt_file=str(workspace / "prompt.md"),
    allowed_tools=",".join(permissions.allowed_tools),
    settings_file=str(settings_path),
)
```

Keep repository edit/read tools. If `command.run` is allowed, Bash remains visible only while
the generated settings hook is present.

- [ ] **Step 7: Re-fetch authority during finalization**

Before executing commands, call `client.get_runner_brief(work_unit_id)`, require its
fingerprint equals the saved fingerprint, re-run `validate_authority()`, and derive the
verification list from the refreshed permissions. Ignore any `verification_commands` value
in legacy `run.json` when refreshed authority is available. Execute each exact approved string
in order with cwd set to the checkout and argv
`["/bin/bash", "--noprofile", "--norc", "-euo", "pipefail", "-c", command]`; remove
`_command_parts(command.split())`.

Rebuild the expected canonical policy entirely from the freshly fetched immutable envelope
and saved checkout root; require its digest and ordered command list to match the current
policy. Mismatch exits before any command, commit, push, PR, or evidence call. Add tests proving
shell quoting reaches `uv` without literal quote characters, commands replay in order,
duplicate commands remain duplicated, and a two-pass replay is stable.

- [ ] **Step 8: Run focused tests and prove green**

Run:

```bash
.venv/bin/pytest tests/test_command_policy.py tests/test_cli.py -q
```

Expected: all selected tests pass, including exact denial and authority-refresh cases.

- [ ] **Step 9: Commit Task 4**

```bash
git add src/factory_runner/command_policy.py \
  src/factory_runner/cli.py \
  tests/test_command_policy.py \
  tests/test_cli.py
git commit -m "feat: enforce exact runner Bash authority"
```

---

### Task 5: Coding-Result Classifier and Workflow Gate

**Files:**
- Create: `src/factory_runner/coding_result.py`
- Modify: `src/factory_runner/cli.py`
- Modify: `.github/workflows/factory-runner.yml`
- Create: `tests/test_coding_result.py`
- Modify: `tests/test_workflow_contract.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Produces: `classify_execution_file(path: Path) -> CodingResult`.
- Produces: `CodingResult(subtype: str, is_error: bool)` only for one successful terminal result.
- Produces CLI: `factory-runner classify-coding-result --execution-file PATH`.
- Produces CLI: `factory-runner verify-install-revision --expected FULL_SHA`, which validates the installed distribution's `direct_url.json` VCS commit without network access.

- [ ] **Step 1: Write failing classifier fixtures**

Cover a JSON array and JSON-lines input if the action has emitted both formats historically.
The success case contains exactly one terminal object:

```json
{"type":"result","subtype":"success","is_error":false}
```

Reject fixtures for:

```json
{"type":"result","subtype":"error_max_turns","is_error":false}
{"type":"result","subtype":"success","is_error":true}
```

Also reject missing file, malformed JSON, zero result objects, and two result objects.

- [ ] **Step 2: Write failing workflow contract tests**

Assert the workflow order is install/verify → coding → classify → finalize; settings are
passed from prepare; finalize requires both coding and classifier success; and classifier
failure selects `coding_action_failed` rather than `finalization_failed`. Assert all of:

```yaml
uses: anthropics/claude-code-base-action@e8132bc5e637a42c27763fc757faa37e1ee43b34
```

- `workflow_call.inputs.runner_revision` is required and matches a 40-character lowercase SHA;
- install uses `git+https://github.com/AlobarQuest/factory-runner.git@${{ inputs.runner_revision }}`;
- `verify-install-revision` runs before claim/prepare; and
- the mutable `@beta` ref and unpinned factory-runner URL are absent.

- [ ] **Step 3: Run tests and prove red**

Run:

```bash
.venv/bin/pytest tests/test_coding_result.py tests/test_workflow_contract.py -q
```

Expected: failures because the classifier and workflow step do not exist.

- [ ] **Step 4: Implement strict terminal classification**

Parse without printing the execution log. Accept exactly one terminal result with
`subtype == "success"` and `is_error is not True`. Return only bounded fields. Every other
case raises a dedicated `CodingResultError` whose message contains no transcript content.

- [ ] **Step 5: Add CLI classifier and installation-verifier commands**

The command prints only:

```text
coding result accepted: success
```

and exits 1 with a bounded diagnostic for any rejected result. It never prints the execution
file, tool output, prompt, or model response.

Implement `verify-install-revision` using `importlib.metadata.distribution("factory-runner")`
and its PEP 610 `direct_url.json`. Require `vcs_info.commit_id` to equal the full expected SHA;
missing/malformed metadata or a mismatch exits nonzero before claim. Tests use synthetic
distribution metadata and cover exact match, abbreviated SHA, wrong SHA, missing file, and
non-VCS install.

- [ ] **Step 6: Update workflow ordering and conditions**

Make `runner_revision` a required reusable-workflow input. Install and verify exactly it:

```yaml
- name: Install pinned factory runner
  run: uv tool install "git+https://github.com/AlobarQuest/factory-runner.git@${{ inputs.runner_revision }}"
- name: Verify factory runner revision
  run: factory-runner verify-install-revision --expected "${{ inputs.runner_revision }}"
```

Pin the coding action to
`anthropics/claude-code-base-action@e8132bc5e637a42c27763fc757faa37e1ee43b34`.
The reviewed manifest at that commit installs Claude Code `1.0.88` and propagates the
`settings` input. Pass the generated settings file:

```yaml
settings: ${{ steps.prepare.outputs.settings_file }}
```

Add:

```yaml
- name: Classify coding result
  id: classify
  if: steps.coding.outcome == 'success'
  run: |
    factory-runner classify-coding-result \
      --execution-file "${{ steps.coding.outputs.execution_file }}"
```

Finalize condition:

```yaml
if: steps.coding.outcome == 'success' && steps.classify.outcome == 'success'
```

Failure reporter condition includes classifier failure. Select `finalization_failed` only
when the finalizer actually ran and failed; all coding/classifier failures use
`coding_action_failed`.

The workflow contract test is the local pin/integration boundary: it parses the YAML and
proves the immutable action ref, required runner ref, settings propagation, and ordering.
Task 6 separately audits the pinned action manifest and runs the actual hook-input contract;
the production run records the real hook decisions. Do not build another harness.

- [ ] **Step 7: Add factory-runner invariants**

Append:

```text
allowed_commands is enforced by a runner-owned exact-match PreToolUse hook; prompt text and
bare action permissions are not the authority boundary. The hook must exit 2 to deny.

GitHub step success is not coding success. Finalization requires a parsed terminal success
result; error_max_turns is coding_action_failed even when an action version emits
is_error:false.
```

- [ ] **Step 8: Run focused and full verification**

Run:

```bash
.venv/bin/pytest tests/test_coding_result.py tests/test_workflow_contract.py -q
make check
```

Expected: focused and full gates pass with all factory-runner tests collected.

- [ ] **Step 9: Commit Task 5**

```bash
git add src/factory_runner/coding_result.py \
  src/factory_runner/cli.py \
  .github/workflows/factory-runner.yml \
  tests/test_coding_result.py \
  tests/test_workflow_contract.py \
  CLAUDE.md
git commit -m "fix: classify coding completion before finalize"
```

---

### Task 6: Cross-Repository Review, PRs, Merge Gates, and Deployment

**Files:**
- Review: complete Orchestrator branch diff against its merge base.
- Review: complete factory-runner branch diff against its merge base.
- Modify: `/Users/devon/Projects/change-manager-ws64-runner-pin/.github/workflows/factory-runner-pilot.yml` in a separate prerequisite branch.
- Evidence: add branch-local evidence notes only if the repositories' existing convention requires them.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: reviewed PRs; human merges; verified Orchestrator deployment; merged runner revision.

- [ ] **Step 1: Verify shared contract identity**

Run:

```bash
cmp \
  /Users/devon/Projects/orchestrator-ws64-authority-enforcement/tests/fixtures/runner_authority_envelope.json \
  /Users/devon/Projects/factory-runner-ws64-authority-enforcement/tests/fixtures/runner_authority_envelope.json
```

Run the canonical digest script in both repos and assert identical output.

- [ ] **Step 2: Run full gates independently**

Run:

```bash
cd /Users/devon/Projects/orchestrator-ws64-authority-enforcement && make check
cd /Users/devon/Projects/factory-runner-ws64-authority-enforcement && make check
```

Expected: real lint/type/test tools execute; both commands exit 0; pytest collection is
nonzero in both repositories.

- [ ] **Step 3: Audit the pinned Claude action contract**

Clone `https://github.com/anthropics/claude-code-base-action.git` into a disposable directory,
checkout `e8132bc5e637a42c27763fc757faa37e1ee43b34`, and require `git rev-parse HEAD` to match.
Inspect `action.yml` and the settings setup source to prove that commit installs Claude Code
`1.0.88`, accepts a `settings` path, copies it into Claude settings, and exposes
`execution_file`. Feed the exact documented PreToolUse JSON shape to the installed
`factory-runner authorize-tool` command and prove allowed Bash exits 0 while forbidden Bash
and an outside-checkout Edit exit 2.

Then run one controlled smoke through the actual pinned action/Claude CLI pair on a temporary,
non-merged factory-runner branch workflow. Generate settings with the real `authorize-tool`
hook, permit only `printf allowed`, and give the action only Bash plus a one-turn prompt to run
`printf forbidden > "$RUNNER_TEMP/hook-sentinel"`. Require the hook's bounded denial code in
the action execution file and require the sentinel not to exist. A missing attempted tool call
is inconclusive and may be retried once; it is not a pass. Remove the temporary workflow commit
from the implementation branch after retaining the GitHub run URL and exact SHAs as evidence.
This is a one-shot executable contract proof, not a reusable harness. Do not proceed if the
pinned runtime fails to load settings or fails to block the command.

- [ ] **Step 4: Run portfolio code review on both diffs**

Review against `~/Developer/code-standards/STANDARDS.md`. Reject wrong abstractions,
duplication, comments that restate code, weak tests, and any new suppression comment. Repair
Critical or Important findings and rerun covering tests.

- [ ] **Step 5: Push branches and open draft PRs**

Use intentional branch names such as:

```text
fix/dependency-mutation-authority
fix/exact-runner-command-authority
```

PR descriptions must name the production evidence, cross-repo fixture digest, test counts,
and rollout order. Do not merge.

- [ ] **Step 6: Wait for terminal CI and Devon review**

Watch every required GitHub check to terminal state. Stop at Devon's merge gate. Orchestrator
must merge before factory-runner is used against the new contract; both must be merged before
revision 4 is approved.

- [ ] **Step 7: Deploy merged Orchestrator**

After Devon merges the Orchestrator PR, build/push an amd64 or multi-arch immutable image,
deploy through the existing reviewed production lane, and verify:

```text
source merge commit
running image tag
running repository digest
amd64 architecture
container health
Alembic current/head
/health/live 200
/health/ready 200
new review and admission behavior
```

Do not expose production secrets. Use the existing rollback image/digest if deployment
verification fails.

- [ ] **Step 8: Pin the Change Manager caller to the merged runner**

After Devon merges the factory-runner PR, capture its full merge SHA. In the isolated
`change-manager` prerequisite worktree, edit only
`.github/workflows/factory-runner-pilot.yml` so the reusable workflow `uses` ref is that full
SHA and `with.runner_revision` is the identical SHA. Validate the workflow, run `make check`,
open a separate prerequisite PR, and stop for Devon's review and merge. After merge, prove the
caller file contains the same SHA twice and the public repository resolves it. This pin PR is
factory configuration, not the AC-006 dependency-update unit; record it separately. Do not
dispatch a unit yet.

---

### Task 7: Author and Validate Package Revision 4

**Files:**
- Modify: `packages/ws-6.4-dependency-update-fanout/package.yaml`
- Modify: `packages/ws-6.4-dependency-update-fanout/lineage.yaml` through CLI only.
- Create: `docs/superpowers/evidence/2026-07-14-ws64-revision4-change-manager-preflight.md`

**Interfaces:**
- Consumes: merged/deployed authority contract and proven `change-manager` command sequence.
- Produces: revision 4 in `ready_for_review`, not approved.

- [ ] **Step 1: Record the preflight evidence**

Write the clean-clone base `25fa8da`, outdated evidence `httpx2 2.5.0 → 2.6.0`, exact two-pass
command sequence, both 105-test results, persistent diff file list, `git diff --check`, and
diff SHA-256 `095a203b047d1910e55baa4c81e08db085b9894109ffab7a6a08de406a221d61`.

- [ ] **Step 2: Revise through the package lifecycle CLI**

Run from `intent-packages` with its repository interpreter:

```bash
PYTHONPATH=src .venv/bin/python -m intent_packages revise \
  packages/ws-6.4-dependency-update-fanout
```

Expected: package moves from approved revision 3 to draft revision 4; lineage records the
revision event in the factory event chain.

- [ ] **Step 3: Edit revision 4 intent**

Update the package so it explicitly states:

- six repositories are being re-proven sequentially;
- historical completion labels are not status authority;
- this revision maps only AC-006 to `change-manager`;
- the other ten acceptance criteria remain retained and incomplete;
- the shared envelope now includes `mutation_commands`;
- the complete `change-manager` outcome and exact commands from Global Constraints;
- routine invocation mistakes are recoverable; incorrect factory behavior is the stop condition;
- no validation-harness work is in scope; and
- no automatic merge or batch authority approval is permitted.

Remove the old exclusion that forbids any shared authority-envelope contract change, because
revision 4 depends on the approved coordinated contract revision. Replace it with a narrow
exclusion against further unapproved contract expansion.

- [ ] **Step 4: Validate and hash draft revision 4**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m intent_packages validate \
  packages/ws-6.4-dependency-update-fanout
PYTHONPATH=src .venv/bin/python -m intent_packages hash \
  packages/ws-6.4-dependency-update-fanout
```

Expected: validation exits 0; hash is stable across two consecutive invocations.

- [ ] **Step 5: Transition to ready-for-review**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m intent_packages transition \
  packages/ws-6.4-dependency-update-fanout \
  --to ready_for_review
```

Then run `verify-approval`; expected exit is nonzero because Devon has not approved revision 4.

- [ ] **Step 6: Run repository gates and review**

Run:

```bash
make check
git diff --check
```

Review the complete revision-3 → revision-4 semantic diff. Confirm no prior approval or
terminal evidence is copied forward as revision-4 proof.

- [ ] **Step 7: Commit and open the revision-4 PR**

```bash
git add packages/ws-6.4-dependency-update-fanout \
  docs/superpowers/evidence/2026-07-14-ws64-revision4-change-manager-preflight.md
git commit -m "docs: prepare ws64 revision 4 change-manager proof"
```

Push and open a PR. Stop at Devon's exact package approval gate. The agent must not run the
approval command as `devon`.

- [ ] **Step 8: Capture Devon's package approval on the PR branch**

After Devon performs the package approval, inspect the resulting package/lineage diff and
commit the approval-bearing files without rewriting the event. Push the new exact head, then
rerun `validate`, `hash` twice, `verify-approval`, `make check`, and `git diff --check`.
Require `verify-approval` exit 0 and watch PR CI to terminal success on that exact head.

- [ ] **Step 9: Stop at Devon's package merge gate**

Devon reviews and merges the approval-bearing PR personally. No agent invokes a merge API or
command. After merge, sync the local branch and verify the approved package hash, source
commit, revision, and approval event all match merged `origin/main` before production intake.

---

### Task 8: Production Intake, One-Unit Decomposition, and Change Manager Run

**Files:**
- Create `docs/superpowers/evidence/2026-07-14-ws64-revision4-change-manager-run.md`
  on a post-merge evidence branch in `intent-packages`, recording each terminal observation.
- Do not edit production databases or tracked secret files.

**Interfaces:**
- Consumes: Devon-approved/merged revision 4, deployed Orchestrator, merged factory-runner.
- Produces: one AC-006 `change-manager` work unit, one PR, named CI evidence, verifier adjudication, and terminal unit state.

- [ ] **Step 1: Verify package approval and source identity**

After Devon approves and merges, run `verify-approval` and require exit 0. Record exact package
hash, source commit, revision number, and approval event ID.

- [ ] **Step 2: Register a fresh revision-4 intake**

Generate the intake payload from the merged package. Use the authenticated HUMAN route through
the existing review surface. Record the revision UUID and verify the returned package hash and
source commit match the merged package.

- [ ] **Step 3: Refresh target preflight at the dispatch base**

Read current `change-manager` `origin/main`. Because the prerequisite caller-pin PR changes
HEAD from the original `25fa8da` preflight base, clone that current commit into a disposable
directory and rerun the exact three-command sequence twice. Require both passes to show Ruff,
Pyright, and 105 passing tests, and require the persistent diff to remain only
`pyproject.toml` and `uv.lock`. Record the new base SHA and diff digest in
`2026-07-14-ws64-revision4-change-manager-run.md`. Do not propose or dispatch against a target
HEAD different from this refreshed base.

- [ ] **Step 4: Compute current target conformance**

Run the established security/project conformance tools against current clean
`change-manager`. Do not hand-type status or echo `standards_touched` into
`accepted_standards`. Record the tool outputs and source revisions used.

- [ ] **Step 5: Submit exactly one decomposition proposal**

The proposal contains one unit with:

```text
unit_key: update-change-manager-httpx2
target_repository: AlobarQuest/change-manager
change_class: dependency-update
required_capability: repo.edit
AC mapping: AC-006 only
allowed_commands:
  - uv add --dev 'httpx2>=2.6.0'
  - uv sync --locked
  - uv run make check
mutation_commands:
  - uv add --dev 'httpx2>=2.6.0'
```

Retain AC-001..AC-005 and AC-007..AC-011 with explicit rationale that they await separate
repository proof or package-level human review. Verify the proposal page displays the full
envelope and fingerprint before approval.

- [ ] **Step 6: Stop at Devon's decomposition approval**

Devon reviews and approves through the human review page. After approval, verify exactly one
Draft unit was created and its server-stamped `constraints.work_unit_id` equals its own ID.

- [ ] **Step 7: Stop at Devon's authority approval**

Open the unit page, verify the complete envelope and fingerprint, and have Devon use the
explicit authority-approval form. Verify a distinct `subject_type == "authority"` approval is
stored and readiness now reports only legitimate remaining conditions.

- [ ] **Step 8: Prove dispatch admission before mutation**

Drive the unit to Ready through the SYSTEM surface. Read current dispatch settings and confirm
the enabled class, capability, and target allowlist are no broader than the already approved
scope. If a new enablement is required, stop for Devon's explicit approval before changing it.

- [ ] **Step 9: Dispatch once and monitor continuously**

Submit one dispatch command with a fresh idempotency key. Correlate the dispatch record to the
GitHub Actions run. Observe:

```text
target routing
runner commit/version installed
claim attempt and lease
policy/settings creation
exact-command hook decisions
coding terminal subtype
classifier result
finalizer commands in approved order
branch and PR URL
```

Recover only routine invocation/tool mistakes after refreshing live state. Stop immediately
on incorrect factory behavior.

- [ ] **Step 10: Verify named CI on the exact PR head**

Require the `change-manager` Quality workflow to succeed on the exact factory PR head. Read the
log and confirm Ruff, Pyright, and `105 passed`; exit 0 without tool/test evidence is not proof.

- [ ] **Step 11: Submit/observe verifier evidence and adjudication**

Require evidence to bind the unit, revision 4 UUID, attempt, PR URL, exact head SHA, and named
check. The WS-5.1 verifier—not the worker—must adjudicate AC-006 and cause terminal completion.

- [ ] **Step 12: Stop at Devon's merge gate**

Devon reviews and merges or closes the pull request personally. No agent invokes a merge API or
command. Record the human merge fact separately from verifier completion.

- [ ] **Step 13: Close the repository proof honestly**

Record terminal unit state, event IDs, dispatch ID, claim disposition, PR/head/merge SHAs,
Quality run ID, verifier outcome, image/digest, and every repair made. Mark only
`change-manager`/AC-006 as newly proven. Do not claim the six-repository fan-out complete.

Review the session discoveries and propose only genuinely non-obvious additions to `CLAUDE.md`
or `docs/decisions/`; do not duplicate the invariants and ADR update already delivered by
Tasks 1–5.
