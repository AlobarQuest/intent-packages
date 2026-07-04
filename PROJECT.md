---
name: intent-packages
tier: active
status: active
purpose: 'Universal intent-package schema, lifecycle, and validate/hash/approve CLI (software factory WS-2.1).'
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
---

## Backlog

- [ ] (P2) validate: wrap the check-H `package_hash` call so a malformed (non-str-key) package in a drift-locked status returns a clean field-pathed error instead of raising CanonicalError (check J already flags it) — added 2026-07-04
- [ ] (P2) loader: raise LoadError (not raw FileNotFoundError) when package.yaml/lineage.yaml is missing, so `validate --all` fails cleanly rather than tracebacking — added 2026-07-04
- [ ] (P2) do_transition re-snapshot on →ready_for_review overwrites the revision `created_at`; preserve original creation time and add a separate `snapshotted_at` — added 2026-07-04
- [ ] (P2) validate: enforce `created_at` ISO-8601 regex; validate `risk.escalation_target` as registry-id-or-`external:`; vocab-check `dependencies.required_capabilities` — added 2026-07-04
- [ ] (P2) verify-approval / CLI: raise clean errors (not KeyError tracebacks) on malformed `approvals[]` entries — added 2026-07-04
- [ ] (P3) `validate --all` is cwd-anchored (`Path("packages")`) — resolve relative to the repo root to avoid the estate cwd gotcha — added 2026-07-04
- [ ] (P3) do_supersede `--by`: verify the superseding package exists and its `supersedes:` points back — added 2026-07-04
- [ ] (P3) emitter `_parse_event_id` uses a `len>3` heuristic; formalize the event_id format contract with factory_events — added 2026-07-04
- [ ] (P3) set_status_in_file drops an inline trailing comment on the `status:` line — added 2026-07-04
- [ ] (P3) Phase-3: chain-based approve idempotency (currently lineage-based; docstring-scoped as MVP) and crash-atomic revise — added 2026-07-04
- [ ] (P3) CI: no security-standards checkout means vocabulary/registered-approver checks never enforce on PRs (spec-endorsed degradation); consider a vendored capability-vocab snapshot or token checkout — added 2026-07-04
- [ ] (P3) Spec §8 sync: non-approval transitions emit before the lineage write (code order); reconcile the "torn state still verifies" wording; `--no-emit` is in the spec but not implemented — added 2026-07-04

## Future plans

- WS-2.2 (done): domain profiles (software-delivery + infrastructure-change) shipped in `src/intent_packages/profiles/` — dispatch registry (check P), per-profile `profile_fields` schemas, and a shared tag-prefix evidence-vocabulary check (AC-004). Universal envelope proven unchanged (`tests/test_profiles_compat.py`). Next: WS-2.3, authored as the next intent package under `profile: software-delivery` (dogfood ladder).
