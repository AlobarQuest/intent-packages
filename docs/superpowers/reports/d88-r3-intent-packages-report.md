Outcome: done

# D-88 R3 build report: the reissue grant in intent-packages

Worker W-347. Task R3 of orchestrator ADR-0055 amendment 39, read at orchestrator `73b77ea7`. The
amendment's R3 text matches the handoff, so no stop point applied.

- **PR:** [AlobarQuest/intent-packages#207](https://github.com/AlobarQuest/intent-packages/pull/207),
  branch `hq/d88-r3-reissue-grant`. It's open and not merged.
- **Base:** `origin/main` `c0cb0a930391911e010f2fa28ce7fbaa79c6e0e2`.
- **Code head:** `ef59959` (the grant) and `2c4b7dc` (the `created_by` type guard). This
  report is committed after them on the same branch.

## What I built

### Schema 5 and its loader

`approval-policy.toml`:

- Line 71 is the SCHEMA 5 header paragraph, and line 97 sets `version = 5`.
- The rotation grant's rationale (from line 163) cites sds-hq `standing-answers.md`, "2026-11-28: a
  reissue of an SDS-used credential the executor rotates end to end is approved by this answer
  (D-88 A)", as the lane grant cites D-34's. It also states what this repository can't check.
- Line 197 is `reissue_created_by = ["factory-create", "rotation-proposer"]` (amendment 39,
  reading 1).
- Line 199 is `reissue_revision_1_approvers = ["devon"]` (HQ's settled change 1). The fixed list is
  the approvers in the covered packages' lineages; every revision-1 approval in them is `devon`.
- Line 226 is `reissue_types.orchestrator`, with `destinations_allowed` = `bws-secret`,
  `coolify-env-hash`, `gh-actions-secret`, `provider` and `runtime-fetch`.
- Line 234 is `reissue_types.change-manager`, with `destinations_allowed` = `bws-secret`,
  `coolify-env-hash`, `coolify-env-held`, `provider` and `runtime-fetch`.
- Both types share one `authority_options` entry, the standard set measured in amendment 39's "The
  eight packages" section. Allowed: `credential_create`, `credential_revoke`, `secret_read`,
  `secret_write` and `infra_mutation`. Prohibited: `repository_write`, `outward_publish` and
  `email_send`. Three attempts.
- The `dependency-update` grant is unchanged, apart from its approver string becoming `@v5`.

`src/intent_packages/approval_policy.py`, the loader:

- Line 82: `SUPPORTED_SCHEMA_VERSIONS` gains 5. The target and reach tables gain key 5.
- Line 160: `REISSUE_MIN_SCHEMA = 5`. The three reissue fields are all-or-none at schema 5 and
  unknown fields at schema 4.
- Line 243: `ReissueType` (`destinations_allowed`, `authority_options`). `RotationGrant` gains
  `reissue_types`, `reissue_created_by` and `reissue_revision_1_approvers`; they're empty when the
  document has no reissue fields.
- Line 390, `_rotation_grant`, and line 447, `_reissue_type`: kinds must be known destination
  kinds, unrepeated, and include `provider`. The authority sets reuse `_authority_set`.

### The refusals

Line 745, `_rotation_refusals`, branches at line 750. It takes the reissue branch only when the
grant has `reissue_types` and the revision is an int (not a bool) of 2 or more. Every other
package, including any reissue under a grant without the fields, takes `_first_issue_refusals`,
which is the schema-4 code unchanged.

`types` and `reissue_types` are separate maps, each read by one branch. A reissue type's revision 1
therefore refuses `rotation_type_not_permitted` (D88-A stays Devon's), and so does a lane type at
revision 2.

The reissue branch, `_reissue_refusals` (line 781), checks the following:

| Condition | Refusal | Line |
|---|---|---|
| Standing | `not_a_standing_package` | 795 |
| Lineage readable; every approval entry has an int revision from 1 to the tip and a string approver | `lineage_unreadable` | 825, 841 |
| The lineage lists revisions 1 to the tip, in order, with no bools | `lineage_not_revisions_1_to_n` | 831 |
| No approval on the tip | `revision_already_approved` | 843 |
| Revision 1 has an approval | `revision_one_not_approved` | 846 |
| Every revision-1 approver is on `reissue_revision_1_approvers` | `revision_one_approver_not_permitted` | 848 |
| `created_by` is a string on `reissue_created_by` | `not_proposer_generated` | 799 |
| One `provider name=` destination naming a reissue type | `rotation_type_not_permitted` | 800 |
| Every destination parses and is of an allowed kind, any count | `destinations_not_permitted` | 857, 859 |
| The authority equals an option (three lists and both budgets) | `authority_terms_not_permitted` | 802 |
| No `human_review` criterion | `acceptance_not_permitted` | 803 |

A revision between revision 1 and the tip may be approved by anyone (a policy included) or by
nobody, which is R1's `reissue_lineage` rule.

### Measured against the live packages

I measured the live packages with the shipped document. These are the copies in
`tests/fixtures/standing_reissue/`, taken at `c0cb0a9`:

- The seven covered packages draw no objection: the operator, observer, drift-reporter, full, read,
  propose and observe bearers.
- `rotation-orchestrator-factory-runner-bearer` (revision 1) and
  `rotation-change-manager-execute-bearer` (revision 1) each draw `("rotation_type_not_permitted",)`.

## Tests and checks

- **`make check`:** ruff, format, pyright (0 errors) and pytest. pytest collected 1503 items,
  deselected 10, and passed all 1493 selected.
- **`tests/test_approval_policy_rotation.py`:** 166 tests pass.
- **`code-standards risk --repo .`:** the verdict is `normal`, so `vendor-review` didn't apply.
- **Security scanner** (`--category security`, from the repo root): 0 BLOCK findings.
- **`/code-review` (high):** it found five issues. I fixed one, and the remaining four are listed
  under Self-review.

### Each exclusion, and how I proved it fails when removed

The script `/tmp/w347/mutate.py` (outside the worktree) applies each mutation alone, runs
`tests/test_approval_policy_rotation.py`, and restores the file with `git checkout`. I ran it twice,
the second time on the final code. Every mutation turned at least one test red, and `git status`
was clean afterward. The following table shows the final run.

| Mutation (exclusion removed) | Tests that fail |
|---|---|
| M1 revision-1 branch also reads `reissue_types` | `test_a_reissue_type_s_revision_1_is_refused` (2) |
| M2 reissue branch also reads `types` | `test_a_lane_type_at_revision_2_is_refused` |
| M3 drop the reissue type check | lane-at-rev-2, `test_a_type_not_in_reissue_types_is_refused` (openrouter, postgres-role, github-pat), `test_two_providers_are_refused_on_a_reissue` (5) |
| M4 drop standing on the reissue branch | `test_a_reissue_not_declared_standing_is_refused`, `test_every_reissue_refusal_is_reported` |
| M5 drop the 1-to-N check | `test_a_lineage_not_listing_revisions_1_to_the_tip_is_refused` (6) |
| M5b accept `True` as revision 1 | the same test, `(True, 2)` case |
| M6 drop the unapproved-tip check | `test_a_tip_already_approved_is_refused`, `test_a_repeated_policy_approval_of_a_reissue_refuses` |
| M7 drop the revision-1-approved check | `test_a_revision_1_never_approved_is_refused` (2), every-refusal |
| M8 read "not `policy:`" instead of the fixed list | `test_a_revision_1_approver_not_on_the_list_is_refused` (agent and case-differs cases) |
| M8b accept any one listed approver among others | the same test, devon-and-a-policy case |
| M9 drop the unreadable-approvals check | `test_an_unreadable_reissue_lineage_is_refused` (5) |
| M9b accept an approval past the tip | the same test, approval-past-the-tip case |
| M10 drop `created_by` | `test_a_reissue_by_another_author_is_refused` (5), every-refusal |
| (type guard) `created_by in set` without `isinstance` | the same test, list and dict cases: `TypeError` (proved separately) |
| M11 drop the destination-kind check | `test_a_destination_of_a_kind_the_type_does_not_allow_is_refused` (6) |
| M12 drop the reissue authority check | `test_a_reissue_authority_other_than_the_standard_set_is_refused` (7), every-refusal |
| M13 drop `human_review` on the reissue branch | `test_a_reissue_with_a_human_review_criterion_is_refused`, every-refusal |
| M14 take the reissue branch without `reissue_types` | `test_the_schema_4_document_still_loads_and_refuses_every_reissue` (7), `test_deleting_the_reissue_fields_refuses_every_reissue` (7) |
| M15 accept the reissue fields at schema 4 | `test_the_reissue_fields_at_schema_4_stop_the_document_loading` |
| M16 TOML: orchestrator drops `gh-actions-secret` | `test_an_allowed_kind_passes_at_any_count` |
| M17 TOML: change-manager drops `coolify-env-held` | that test, and `test_each_covered_reissue_draws_no_objection` (the read bearer) |
| M18 TOML: orchestrator allows `coolify-env` | `test_a_destination_of_a_kind_the_type_does_not_allow_is_refused` |
| M19 TOML: approvers widened | `test_a_revision_1_approver_not_on_the_list_is_refused` |
| M20 TOML: `created_by` widened | `test_a_reissue_by_another_author_is_refused` |

Two pass cases guard against over-tightening. `test_a_revision_between_approved_by_policy_passes`
covers the steady state after the first D-88 approval. `test_a_revision_between_never_approved_passes`
covers R1's "a revision that was never approved doesn't refuse".

Further tests cover the loader: the reissue grant loads at schema 5; a partial grant (missing
approvers, missing `created_by`, or types alone) fails to load; and malformed kinds,
authority fields, or empty lists fail to load. `do_approve` runs end to end at revision 2: the
approvers become `[devon, policy:non-software-operational@v5]`, and a repeat refuses
`revision_already_approved` and writes nothing.

### A schema-4 document still loads and refuses every reissue

`tests/fixtures/approval-policy-schema-4.toml` is a byte copy of the document at `c0cb0a9`. It loads
at version 4, and each of the seven covered packages draws exactly `not_revision_one`,
`lineage_has_approval`, `not_proposer_generated` and `rotation_type_not_permitted`, as it does on
`main`. A schema-5 document with the three reissue fields deleted draws the same refusals.

### Existing assertions I changed

- `tests/test_approval_policy.py`:
  - `policy.version == 4` becomes `5`.
  - `test_approver_is_v4` becomes `test_approver_is_v5` (both profiles at `@v5`; `@v4` is added to
    the recognised list).
  - The unknown-version test moves from 5 to 6.
- `tests/test_create_standing.py:122` and `tests/test_op_approve_by_policy.py:32`: `@v4` becomes
  `@v5`.
- `tests/test_approval_policy_rotation.py`:
  - `APPROVER` becomes `@v5`.
  - `test_a_revision_other_than_1_is_refused` drops `2` and adds `"2"`, because a revision 2 now
    takes the reissue branch.
  - `test_every_refusal_is_reported` uses revision 0 in place of 2, with identical expected
    refusals.
  - `grant.decided` becomes `2026-11-28`, and an assertion on `reissue_types` is added.
  - The other-version approver test uses `@v4` in place of `@v3`.

## The `rotated_by_sds` finding

`approval_policy.py` can't read the credential's registry row. It imports only
`destination_format`, `members` (the SDS member record, for `dependency-update` targets) and
`profiles`. The row and its `rotated_by_sds` key live in the orchestrator's and change-manager's
`.cred-consumers.toml`, which this repository doesn't read, so I added no registry read. As the
handoff directs, the orchestrator command and the carrier (R1 and R2) hold that condition.

## Files changed

- `approval-policy.toml`
- `src/intent_packages/approval_policy.py`
- `tests/test_approval_policy_rotation.py`
- `tests/test_approval_policy.py`, `tests/test_create_standing.py` and
  `tests/test_op_approve_by_policy.py` (the version string only)
- `tests/fixtures/approval-policy-schema-4.toml` (new)
- `tests/fixtures/standing_reissue/<9 packages>/{package,lineage}.yaml` (new copies). Nothing under
  `packages/` was edited, approved or transitioned.

## Self-review

`/code-review` raised five findings:

1. **Fixed (important):** a list or dict `created_by` raised `TypeError` from the frozenset
   membership test, where it needed to refuse. It now refuses `not_proposer_generated`, and a test
   covers both shapes.
2. **Not changed:** reissue destinations aren't pinned by value or count. That's R3 as written
   ("a set of kinds, any count"). `destinations_equal` and `no_new_copy` are R1's checks, against
   the registry and the last approved revision, neither of which this repository can read. The
   rationale says so.
3. **Not changed:** the revision-1 approval's `approved_hash` isn't compared with revision 1's
   `hash`. R3 doesn't list it. R1's `proposer_revised` checks the last approval's hash at its
   commit, and `verify-approval` checks the chain.
4. **Covered here:** only seven of the nine fixture packages pass. The other two are revision-1
   first hand-overs, and the rationale and this report both say so.
5. **Not changed:** the schema-4 fixture duplicates the document. It's deliberately a frozen
   snapshot, so that "a schema-4 document still loads and refuses every reissue" is tested against
   the real document as it stood, and not against one that later edits keep in step.

## Concerns

- **Checks R3 doesn't make here:** the reach, the hand-rotated identities (`orchestrator-system`,
  `orchestrator-verifier` and `rotation-executor` entry prefixes, which are visible in
  `coolify-env-hash`), and infraops' `last_rotated`. Per amendment 39, R1 and R2 hold these. I
  didn't add them, so as not to widen R3 beyond its text. Until R1 and R2 merge, this grant alone
  would withhold objections from a SYSTEM-bearer reissue that matched the shape. The approval path
  still requires the orchestrator command, as the rationale says.
- **Two fields beyond the amendment's named fields:** `reissue_created_by` and
  `reissue_revision_1_approvers` aren't named in the amendment. They carry HQ's settled change 1
  and amendment 39 reading 1 in the document, so that narrowing either stays a one-file edit.
- **`gh-actions-secret` in orchestrator's allowed kinds:** none of the seven covered packages lists
  this kind. I included it because the amendment names it ("one to seven `gh-actions-secret` or
  `runtime-fetch` lines"), for the factory-runner bearer's later reissues. Removing it narrows the
  grant, and the test at M16 would then need to move.
- **The `@v5` bump:** policy approvers become `policy:<profile>@v5`. The orchestrator matches the
  prefix `policy:non-software-operational@` and any `@v<N>`. sds-hq's `standing-approve` reads the
  approver from `load_policy()`. Neither pins `@v4`; I searched with `git grep` at `73b77ea7` and
  read sds-hq `standing_approve.py`.

## Standards followed

- **Code Brain rule 3 (structured JSON logs to stdout):** I added no log line. The module returns
  refusal strings and logs nothing.
- **Code Brain rule 4 (never silently swallow an exception):** a check that can't be made refuses.
  These cases include an unreadable lineage, an unreadable approval entry, an unparseable
  destination, and a non-string `created_by` (the review fix). A malformed document raises
  `ApprovalPolicyError` and never yields an empty policy. No new `except` was added.
- **Code Brain rule 5 (never log secrets, credentials, auth headers or tokens):** nothing is
  logged. The fixtures name credentials by package id, BWS UUID and setting key only, copied from
  the packages already in the repository.
- **Infra Brain 591, 592 and 593 (no BWS token in tracked files, in history, or inline):** nothing
  token-shaped was written. The security scanner reports 0 BLOCK findings.
- **Infra Brain 1032 (`cred.exposure-rotate`):** a scheduled reissue isn't an exposure. This change
  opens and closes none, and runs no production act (no BWS, Coolify, VPS or infraops call).
- **Infra Brain 212 (HTTPS for public FQDNs):** not applicable. No endpoint is added.
