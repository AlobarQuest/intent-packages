Outcome: done

# Build report: ADR-0055 amendment 22, increment 1

Worker W-96, branch `hq/adr-0055-a22-increment-1`, PR
[#171](https://github.com/AlobarQuest/intent-packages/pull/171) (ready, not merged). The PR's final
head is the commit that adds this version of the report, after the code-review fixes; HQ can read
it with `gh pr view 171 --json headRefOid`.

## What I built

`approval-policy.toml` schema 4 and its loader. The schema gives `non-software-operational` a
**rotation grant**, so a lane credential's proposer-generated revision 1 can be approved as
`policy:non-software-operational@v4`. Nothing in the orchestrator changed, and no package was
approved.

### The grant shape

The grant is a second shape beside the existing grant. The loader picks it when a grant table
carries `types`. Only the `non-software-operational` row may carry one, and at schemas 1 to 3
`types` is an unknown field, so an older document can't carry the grant.

```toml
[profile.non-software-operational.grant]
rationale = "..."            # cites the 2026-11-10 standing answer (D-34 A)
decided = "2026-11-10"
created_by = "rotation-proposer"

[profile.non-software-operational.grant.types.bws-lane-token]
destinations = [{ kind = "bws-secret" }, { kind = "coolify-env", redeploy = false }, { kind = "provider" }]
authority_options = [{ allowed = [...], requires_approval = [], prohibited = [...], max_attempts = 3 }]

[profile.non-software-operational.grant.types.healthchecks-ping-url]
destinations = [{ kind = "bws-secret" }, { kind = "provider" }]
authority_options = [{ ... }]
```

A destination pattern names a kind and may pin that kind's identity fields (`redeploy = false`).
The loader refuses a repeated kind, an unknown kind, a field the kind doesn't have, a pinned field
of the wrong type (`redeploy` must be a boolean, other fields non-blank strings), a provider
pattern that pins `name` (the type key is the name), a type with no provider pattern, and an
authority set naming one term in two of its lists. An
authority set has no `max_llm_calls` field, because TOML can't write null. The refusal code
requires `max_llm_calls` to be null, and requires `max_attempts` to equal the set's value
exactly, not as a ceiling.

Each type's set is `generate.authority` for the issue plan (orchestrator
`src/rotation_proposer/generate.py`, lines 215-233 at `671acd1d`; `rotation_worker/types.py` for
the capabilities):

| Type | Allowed | Prohibited | Budgets |
|---|---|---|---|
| `bws-lane-token` | `secret_read`, `secret_write`, `infra_mutation` (its `coolify-env` is in `HOSTED_KINDS`) | `credential_create`, `credential_revoke`, `repository_write`, `outward_publish`, `email_send` | 3 attempts, `max_llm_calls` null |
| `healthchecks-ping-url` | `secret_read`, `secret_write` (`creates=False`, so no `credential_create`) | `credential_create`, `credential_revoke`, `repository_write`, `infra_mutation`, `outward_publish`, `email_send` | 3 attempts, `max_llm_calls` null |

`requires_approval` is empty for both. The two fixture packages hold exactly these sets, and they
differ only by `infra_mutation`, which decision item 2 explains (the lane token's Coolify copy).
So no stop point applied.

### Each refusal and its test

All tests are in `tests/test_approval_policy_rotation.py`. Each asserts that one change draws only
its own refusal.

| Condition (decision item 3) | Refusal | Tests |
|---|---|---|
| Standing package | `not_a_standing_package` (reused) | `test_a_package_not_declared_standing_is_refused` (`False`, `"true"`, `None`) |
| Revision 1, and a lineage listing revision 1 alone | `not_revision_one` | `test_a_revision_other_than_1_is_refused` (2, 0, `True`, `"1"`); `test_a_lineage_listing_anything_but_revision_1_alone_is_refused` |
| A lineage that can be read | `lineage_unreadable` | `test_a_missing_or_unreadable_lineage_is_refused` (None, a string, a missing `approvals` or `revisions`, wrong types) |
| No earlier approval in the lineage | `lineage_has_approval` | `test_a_lineage_with_an_earlier_approval_is_refused`; `test_a_repeated_policy_approval_refuses` (through `do_approve`) |
| `created_by` is `rotation-proposer` | `not_proposer_generated` | `test_a_package_the_proposer_did_not_write_is_refused` |
| Exactly one of the two types, by its `provider name=` destination | `rotation_type_not_permitted` | `test_a_third_rotation_type_is_refused`; `test_the_orchestrator_s_github_render_is_refused_as_a_third_type`; `test_no_single_readable_provider_is_refused` (none, two, malformed) |
| Destinations of that type's kinds | `destinations_not_permitted` | `test_destinations_not_of_the_type_s_kinds_are_refused` (8 cases, including `redeploy=true`, a missing Coolify copy, a second keeper, and a malformed keeper) |
| Authority equals one of the type's sets | `authority_terms_not_permitted` (reused) | `test_an_authority_one_capability_away_is_refused` (4 cases); `test_an_authority_missing_a_prohibition_is_refused`; `test_the_other_type_s_authority_is_refused`; `test_budgets_other_than_the_standard_are_refused` (6 cases) |
| No `human_review` criterion | `acceptance_not_permitted` (reused) | `test_a_human_review_criterion_is_refused`; `test_no_readable_criteria_is_refused` |

The destinations and authority checks need the type, so they're skipped when
`rotation_type_not_permitted` already stands. `test_every_refusal_is_reported_not_just_the_first`
pins that every other refusal is reported together. The loader tests cover a rotation grant
before schema 4 (by the missing grant fields, and by `types` beside a complete schema-3 grant as an
unknown field), on another profile, and malformed in nine ways: a repeated kind, an unknown kind, a
field the kind doesn't have, two wrong-typed pinned fields, an extra authority field, a term in two
authority lists, a provider pattern that pins `name`, and a type with no provider pattern.

Through `do_approve`:

- `test_do_approve_takes_the_policy_approval_for_a_lane_credential_s_revision_1`: the approval
  records `policy:non-software-operational@v4` in the lineage and the chain event. If
  `_authorize_approver` stops passing the lineage, this test fails (checked by mutation).
- `test_do_approve_still_takes_a_named_human`: `devon` still approves.
- `test_do_approve_refuses_another_policy_version`: `@v3` is refused.

### Code changes

- `src/intent_packages/approval_policy.py`: schema 4 in `SUPPORTED_SCHEMA_VERSIONS`; key 4 in the
  target and reach field maps (without it, the dependency-update grant raised `KeyError` at
  version 4); the `RotationGrant`, `RotationType`, `DestinationPattern`, and `AuthoritySet`
  dataclasses, with their loader; six new refusal constants; `refusals_for(package, lineage=None)`.
- `src/intent_packages/operations.py`: `_authorize_approver(package, approver, lineage)`, called
  with the lineage `do_approve` reads. The human arm still runs first, and the exact-approver
  check is unchanged.
- `src/intent_packages/destination_format.py`: `parse()` returns a destination's kind and fields,
  or raises `DestinationFormatError`. `destination_error` wraps it, so its behavior doesn't change
  (the shared-format contract tests pass).
- `approval-policy.toml`: `version = 4`, a SCHEMA 4 header paragraph, the grant, the
  `non-software-operational` row's rationale and `decided` updated for the grant, and the section
  comments recounted (three profiles without a grant, two with). The dependency-update grant's
  text and every other row are unchanged.
- `src/intent_packages/factory/scaffolds.py`: the `create_rotation` docstring said a named human
  approves the written package; it now names the rotation grant as the other approver.
- `README.md`: a "Policy approval" section listing the two policy-approvable profiles, and the
  `approve` row, which said "Devon-only" although `--by-policy` already existed.

### The two fixtures' result

`refusals_for(package, lineage)` returns `()` for both packages on `main`
(`rotation-deploy-watcher-ping-url` from `4f57bef`, `rotation-revision-watcher-bws-token` from
`2191e86`), with their real lineage and with a synthetic one. Without a lineage, both return
`('lineage_unreadable',)`. The orchestrator's issue-plan fixtures, which `test_create_rotation`
pins by sha256, also draw no objection. The tests use copies in
`tests/fixtures/standing_approval/`, so HQ approving the live packages later doesn't move them.

## Version skew

Moving the document to version 4 changes the approver the `dependency-update` grant issues from
`@v3` to `@v4`. No reader pins a version. Each source was read at orchestrator `origin/main`
`671acd1d` with `git show`:

- `src/orchestrator/services/intake/bump_policy.py`, line 20: `_BUMP_APPROVER = "policy:dependency-update@"`.
  `is_bump_revision` uses `startswith`. It's a prefix.
- `src/orchestrator/package_sources.py`, line 26: `_POLICY_APPROVER_RE` is
  `^policy:[a-z0-9][a-z0-9-]*@v[1-9][0-9]*$`. It accepts any version.
- `src/orchestrator/services/intake/standing_approval.py`, line 34, `src/rotation_proposer/standing_approval.py`,
  line 45, and `src/work_carrier/standing.py`, line 46: the prefixes `policy:non-software-operational@`
  and `policy:`.
- A `git grep` for `policy:[a-z-]*@v[0-9]` across orchestrator `src/` matches nothing. The literal
  versions are in tests and docs only. `tests/work_carrier/test_standing.py`, line 184, uses `@v5`
  as a lineage that differs from the payload, not as a pinned version.
- In intent-packages, `operations._has_matching_approval` and `verify_approval` recognise any
  approver that `is_policy_approver` matches (`POLICY_APPROVER_RE`, any version), so the `@v3`
  approvals already in lineages stay valid. `approve --by-policy` computes the approver from the
  loaded document (`cli.py`, line 155). The only `@v3` literals were in three tests, which I
  updated to `@v4`.
- Across `~/Projects` (excluding worktrees, `.venv`, and `packages/`), `dependency-update@v<N>`
  appears only in test files and this handoff.

## Tests and checks

- `make check`: ruff lint and format, pyright, and pytest all pass. **1285 tests collected, 1285
  passed.** The new file adds 74 of them.
- PR CI on the first push: "Lint, type-check, and test", "Routing policy compatibility", and
  "validate" all passed.
- Mutation checks: dropping the lineage from `refusals_for` in `_authorize_approver` turns 2 tests
  red. Making `_lineage_approval_refusal` return `None` turns 3 tests red. I restored both.
- The existing dependency-update tests pass at version 4 (`tests/test_approval_policy.py`,
  `tests/test_op_approve_by_policy.py`, and `tests/test_create_standing.py`). The version pins
  moved to 4 and `test_an_unknown_schema_version_is_refused` moved to 5.
- Security scan from the worktree root
  (`security_scan.cli . --category security`): 0 BLOCK, 1 WARN, 1 INFO. The WARN
  (`bws.reference-by-stable-uuid`) is in `tests/factory/fixtures/infra_rules.json`, which this
  change doesn't touch. The INFO is the judgment-only least-privilege rule.

## Files changed

- `approval-policy.toml`
- `README.md`
- `src/intent_packages/approval_policy.py`
- `src/intent_packages/destination_format.py`
- `src/intent_packages/operations.py`
- `src/intent_packages/factory/scaffolds.py` (docstring only)
- `tests/test_approval_policy_rotation.py` (new)
- `tests/fixtures/standing_approval/rotation-deploy-watcher-ping-url/package.yaml` (new copy)
- `tests/fixtures/standing_approval/rotation-revision-watcher-bws-token/package.yaml` (new copy)
- `tests/test_approval_policy.py`, `tests/test_op_approve_by_policy.py`,
  `tests/test_create_standing.py`, `tests/test_profile_non_software_operational.py` (version pins,
  the excluded-profile list, and `isinstance` narrowing for the widened grant type)

## Self-review

- The grant checks only the amendment's conditions. It doesn't check `reach` or `risk.max_impact`,
  because decision item 3's bullet doesn't name them, and the orchestrator's re-render covers every
  field.
- Refusals are independent. A wrong type is one refusal, not three.
- An unreadable lineage is never read as "no approval": a missing key or a wrong type refuses
  `lineage_unreadable`.
- No new suppression comments. Types are narrowed with a `TypeGuard`, not `assert` or
  `# type: ignore`.
- `/code-review` (medium) ran on the branch diff and returned seven findings. I fixed three:
  pinned destination fields are type-checked at load, an authority set can't name a term in two
  lists, and the type guard uses `is not None` instead of truthiness. I left four, with reasons:
  - "`created_by` is self-asserted, and destination values are unchecked": this is the
    amendment's design. This repository can't read the registry, and the orchestrator's command,
    carrier, and gate re-check the render (decision item 3).
  - "A stale lineage hash passes": `do_approve` runs `validate_package` first, which refuses
    hash drift against the lineage.
  - "Only `human_review` is refused among evidence types": the specification names exactly that,
    and validation already restricts evidence types to the vocabulary.
  - "The `@v4` bump breaks a pinned reader": checked, and no reader pins a version (see Version
    skew).
- Readers of the policy document beyond the approver string: `scripts/check_routing_policy_compatibility.py`
  reads the profile's `BUDGETS` constant, not the TOML. Orchestrator `src/bump_proposer/standing.py`,
  line 396, approves with `--by-policy`, which computes the approver from the loaded document. No
  other repository under `~/Projects` reads `approval-policy.toml`.
- Docs: the handoff's grep for `non-software-operational` and `policy-approvable` matched
  `README.md` (updated) and three dated design records under `docs/superpowers/`
  (`plans/2026-07-29-wsp210-profiles-routing-policy.md`,
  `specs/2026-07-29-wsp210-profiles-routing-policy-design.md`,
  `specs/2026-07-29-factory-cli-front-door-design.md`). I left those unchanged, because they
  record decisions as of their dates, and none describes which profiles are policy-approvable
  today.

## Concerns

1. **A repeated policy approval of a rotation revision refuses instead of being a no-op.**
   `do_approve` runs `_authorize_approver` before its idempotency check, and the grant reads any
   lineage approval as an earlier one. So calling `approve --by-policy` again on an approved lane
   revision 1 raises `lineage_has_approval` and writes nothing. A repeated dependency-update
   approval returns quietly instead. This follows the specification's plain reading and fails
   closed. `test_a_repeated_policy_approval_refuses` pins it. A crash between the lineage write
   and the status flip can't be replayed through `do_approve` for any profile, because
   `validate_package` already refuses the status and lineage mismatch. If increment 4's cycle
   retries `approve`, it must treat this refusal on an already-approved revision as done.
2. **I ran `git fetch` once inside `~/Projects/orchestrator`**, before rereading the handoff's
   "never ... run anything in that tree". It changed only the remote-tracking refs; I didn't check
   out, edit, or pull anything, and every read after that used `git show origin/main:<path>`.
   `origin/main` was `671acd1d`, the commit the handoff names.
3. Line numbers in `generate.py` differ slightly from the handoff's (`authority` is at lines
   215-233 at `671acd1d`, not 201-219). The function is the same, so this isn't a contradiction.

## Standards followed

- **Code Brain rule 3 (structured JSON logs to stdout, not files):** the change adds no log line
  and no file logging. Refusals are return values, as before.
- **Code Brain rule 4 (never swallow an exception silently):** a policy that can't be read still
  raises `ApprovalPolicyError`, which `_authorize_approver` turns into an `OperationError`, and a
  malformed grant raises at load. A lineage that can't be read refuses with `lineage_unreadable`.
  The one new `except` (`DestinationFormatError` in `_granted_type` and `_parsed_destinations`)
  turns the failure into a named refusal. There's no bare `except ...: pass`.
- **Code Brain rule 5 (never log secrets, credentials, auth headers, tokens, or full bodies):**
  refusals are fixed condition names. No refusal or error message includes a destination value or
  any package body.
- **Infra Brain 591, 592, 593 (no BWS token in tracked files or history; no inline
  `BWS_ACCESS_TOKEN` value; fixture values are obvious placeholders):** no token was written. The
  fixture copies hold the BWS secret UUIDs and the Coolify resource id already tracked in
  `packages/`, which are identifiers, not secrets. Test-only values are placeholders such as
  `11111111-1111-4111-8111-111111111111`. The security scan reports 0 BLOCK.
- **Infra Brain 1032 (exposure means rotate):** I saw no secret value in any file, output, or
  transcript, so there's nothing to rotate.
- **Infra Brain 212 (HTTPS for public FQDNs):** doesn't apply. The change touches no endpoint or
  domain.
