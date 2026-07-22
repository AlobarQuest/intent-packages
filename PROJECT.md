---
name: intent-packages
tier: active
status: active
purpose: Universal intent-package schema, lifecycle, and validate/hash/approve CLI
  (software factory WS-2.1).
version: 0.1.0
version_source: pyproject
updated: '2026-07-04'
foundation: true
foundation_contract: 1
applicable_standards:
  project: '1.0'
  security: '1.0'
  code: '1.0'
required_checks:
- id: intent-package-validate
  executor: github-actions:validate.yml
- id: quality
  executor: github-actions:quality.yml
---

## Backlog

- [x] (P2) Onboard to code-standards immediately after WS-2.4 exposed the day-one portfolio gap. The repo now has the standard manifest, vendored Quality CI, deterministic Makefile, empty regression baseline, and a genuinely green full-repo `make check`. — resolved 2026-07-04

- [x] (P2) Check H converts canonicalization failures into validation errors instead of raising `CanonicalError`. — added/resolved 2026-07-04
- [x] (P2) Missing package/lineage files raise `LoadError` with file context, so validation fails cleanly without a traceback. — added/resolved 2026-07-04
- [x] (P2) Re-snapshotting preserves revision `created_at` and records `snapshotted_at` separately. — added/resolved 2026-07-04
- [x] (P2) Validation enforces timezone-qualified ISO-8601 `created_at`, registered-or-external escalation targets, and capability vocabulary on dependencies. — added/resolved 2026-07-04
- [x] (P2) Approval and verification paths handle malformed `approvals[]` entries without `KeyError` tracebacks. — added/resolved 2026-07-04
- [x] (P3) `validate --all` resolves `packages/` from the installed module's repository root, independent of cwd. — added/resolved 2026-07-04
- [x] (P3) `supersede --by` requires an existing replacement package with a matching reverse `supersedes` link. — added/resolved 2026-07-04
- [ ] (P3) emitter `_parse_event_id` uses a `len>3` heuristic; formalize the event_id format contract with factory_events — added 2026-07-04
- [x] (P3) `set_status_in_file` preserves inline trailing comments on the `status:` line. — added/resolved 2026-07-04
- [ ] (P3) Phase-3: chain-based approve idempotency (currently lineage-based; docstring-scoped as MVP) and crash-atomic revise — added 2026-07-04
- [ ] (P3) CI: no security-standards checkout means vocabulary/registered-approver checks never enforce on PRs (spec-endorsed degradation); consider a vendored capability-vocab snapshot or token checkout — added 2026-07-04
- [ ] (P3) Spec §8 sync: non-approval transitions emit before the lineage write (code order); reconcile the "torn state still verifies" wording; `--no-emit` is in the spec but not implemented — added 2026-07-04
- [ ] (P3) profiles: no test locks evidence-tag case-sensitivity (e.g. `"CI: ..."` must be rejected as unrecognized) or the optional-space-after-colon convention across tags other than the one already covered — added 2026-07-04
- [x] (P3) A package carrying `profile_fields` without `profile` now fails validation. — added/resolved 2026-07-04
- [ ] (P3) tests/conftest.py: three ~80-line near-duplicate package-YAML templates (`_VALID_PACKAGE_YAML`, `_SOFTWARE_DELIVERY_PACKAGE_YAML`, `_INFRASTRUCTURE_CHANGE_PACKAGE_YAML`) — acceptable for now (matches the pre-existing fixture pattern and doubles as readable documentation); extract a builder once a 4th profile fixture is added (rule of three) — added 2026-07-04
- [x] (P2) Recognized profile evidence tags without a declared profile now emit a targeted validation warning; historical superseded packages remain valid but no longer pass silently. — added/resolved 2026-07-04
- [ ] (P3) software-delivery profile's `profile_fields.repo` is a single string; a workstream whose mutation spans two repos (e.g. WS-2.3: a skill in `claude-control-plane` + this repo's packages/specs) has no schema-native way to express the split — currently documented as a `rollback_plan` text note rather than a second field (design spec 2026-07-04-ws23-intent-authoring-skill.md D-Q4, deliberate, not silently worked around). Consider a `related_repos: [str]` optional profile_field if this recurs. — added 2026-07-04

- [ ] (P2) `approve` records lineage.approvals[].commit as git HEAD at approval time, not the commit containing the approved content. Revision 2 was approved at hash 4e7a40a3… but recorded commit 3584ff0, which predates the package.yaml edits; revision 1 did the same. The field reads as provenance it does not carry. Either record the commit that contains the approved hash, or drop the field. — added 2026-07-10
- [ ] (P2) Approval-bearing PRs in intent-packages must NOT be squash-merged: the squash drops the approval_ledger_commit that lineage.yaml records, so the intake payload's provenance points at a commit not on main (it survives only while the branch does). WS-P2.1 used a merge commit; WS-P2.15 PR #21 was squashed and needed a rescue tag (wsp215-approval-rev1). Either require merge commits on this repo, or have the CLI stamp a durable ref at approve time — added 2026-07-12
- [ ] (P2) Build the dependency-update delivery profile + `factory decompose` command encapsulating the hand-built WS-6.4 decomposition (criterion-UUID resolution, ac_mappings/retained_acs, conformance-from-real-scanners, per-tooling envelope templates [uv + pip proven, npm TBD], dry-run mutator fail-closed on no-diff, runner-honest verifier, name-every-pin-site, submit). Maps to WS-P2.10 (profiles) + WS-P2.9 (factory CLI). Design: ~/docs/software-delivery-system/2026-07-17-dependency-update-profile-and-decompose-tool-spec.md Plan: docs/superpowers/plans/2026-07-17-factory-decompose.md — added 2026-07-17
## Future plans

- WS-2.2 (done): domain profiles (software-delivery + infrastructure-change) shipped in `src/intent_packages/profiles/` — dispatch registry (check P), per-profile `profile_fields` schemas, and a shared tag-prefix evidence-vocabulary check (AC-004). Universal envelope proven unchanged (`tests/test_profiles_compat.py`). Next: WS-2.3, authored as the next intent package under `profile: software-delivery` (dogfood ladder).
- WS-2.3 (done): `project-initiation` skill upgraded into the intent-authoring front door (factory-bound fork, classify-before-generate, structural sources trust classification, pre-emission checklist, corrected approval boundary) — shipped in `claude-control-plane`. Package `ws-2.3-intent-authoring-skill` superseded by `ws-2.3-intent-authoring-skill-v2` after a final-review catch (profile never declared; three sources over-trusted); v2 closed. Live dogfood pilot draft `ws-2.4-brain-approver-gate` left in Draft, feeding WS-2.4.
