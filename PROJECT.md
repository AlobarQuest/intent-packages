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
- [ ] (P3) profiles: no test locks evidence-tag case-sensitivity (e.g. `"CI: ..."` must be rejected as unrecognized) or the optional-space-after-colon convention across tags other than the one already covered — added 2026-07-04
- [ ] (P3) profiles: a package carrying `profile_fields` but no `profile:` key validates clean and silently ignores the fields — likely an authoring mistake (forgot `profile:`); worth a one-line error — added 2026-07-04
- [ ] (P3) tests/conftest.py: three ~80-line near-duplicate package-YAML templates (`_VALID_PACKAGE_YAML`, `_SOFTWARE_DELIVERY_PACKAGE_YAML`, `_INFRASTRUCTURE_CHANGE_PACKAGE_YAML`) — acceptable for now (matches the pre-existing fixture pattern and doubles as readable documentation); extract a builder once a 4th profile fixture is added (rule of three) — added 2026-07-04
- [ ] (P2) validate/check A: an `acceptance[].evidence` string using a recognized profile tag prefix (`ci:`/`gate:`/`scan:`/`review:`/`health:`/`human:`) with no `profile:` key declared at all validates clean and silently never dispatches the tag-consistency check — the tags just read as ordinary text to the universal validator. Distinct from the already-filed sibling case (line above: `profile_fields` present but no `profile:`) — this one has neither. Caught live 2026-07-04: both `ws-2.3-intent-authoring-skill` and `ws-2.4-brain-approver-gate` were authored this way and "validated" without ever exercising the profile they were written against; fixed via a direct edit (still-Draft ws-2.4) and a `supersede` (already-approved ws-2.3, see `ws-2.3-intent-authoring-skill-v2`). Worth a check: a package with no `profile:` whose `acceptance[].evidence` strings match a known tag-prefix vocabulary should at least warn. — added 2026-07-04
- [ ] (P3) software-delivery profile's `profile_fields.repo` is a single string; a workstream whose mutation spans two repos (e.g. WS-2.3: a skill in `claude-control-plane` + this repo's packages/specs) has no schema-native way to express the split — currently documented as a `rollback_plan` text note rather than a second field (design spec 2026-07-04-ws23-intent-authoring-skill.md D-Q4, deliberate, not silently worked around). Consider a `related_repos: [str]` optional profile_field if this recurs. — added 2026-07-04

## Future plans

- WS-2.2 (done): domain profiles (software-delivery + infrastructure-change) shipped in `src/intent_packages/profiles/` — dispatch registry (check P), per-profile `profile_fields` schemas, and a shared tag-prefix evidence-vocabulary check (AC-004). Universal envelope proven unchanged (`tests/test_profiles_compat.py`). Next: WS-2.3, authored as the next intent package under `profile: software-delivery` (dogfood ladder).
- WS-2.3 (done): `project-initiation` skill upgraded into the intent-authoring front door (factory-bound fork, classify-before-generate, structural sources trust classification, pre-emission checklist, corrected approval boundary) — shipped in `claude-control-plane`. Package `ws-2.3-intent-authoring-skill` superseded by `ws-2.3-intent-authoring-skill-v2` after a final-review catch (profile never declared; three sources over-trusted); v2 closed. Live dogfood pilot draft `ws-2.4-brain-approver-gate` left in Draft, feeding WS-2.4.
