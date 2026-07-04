# WS-2.2 — Domain Profiles for Intent Packages

**Status:** Design approved 2026-07-04 (Devon). Ready for planning.
**Workstream:** Software Factory Phase 2, WS-2.2.
**Repo:** `~/Projects/intent-packages` (`AlobarQuest/intent-packages`, default branch `main`).
**Intent package:** `packages/ws-2.2-domain-profiles` (revision 2, approved — includes AC-004, added via
`revise` during this design session; see §7).
**Authoritative sources:** master plan Phase 2 (`~/docs/software-delivery-system/2026-07-02-software-factory-master-plan.md`)
+ D3; architecture doc §4 (`~/docs/software-delivery-system/2026-06-30-foundation-intent-orchestration-architecture.md`);
WS-2.1 spec (`docs/superpowers/specs/2026-07-03-ws21-intent-package-schema.md`), the universal envelope this extends.

---

## 1. Goal and scope

Extend the WS-2.1 universal intent-package envelope with the first two **domain profiles** —
**software-delivery** and **infrastructure-change** — without modifying the universal schema, hash
semantics, or lifecycle. A profile adds domain-specific required fields (under the reserved
`profile_fields` key) and domain-specific acceptance-criteria evidence rules, layered on top of the
existing `validate_package()` entrypoint.

### In scope
1. A `profiles/` module: an in-repo registry dispatching on `package['profile']`.
2. The **software-delivery** profile: field schema + evidence-tag validation.
3. The **infrastructure-change** profile: field schema + evidence-tag validation.
4. Example packages (valid + deliberately-broken) per profile, as test fixtures.
5. Proof the universal envelope is unchanged (AC-002).

### Explicitly out of scope
- The real-estate listing-launch profile and any pilot packages (WS-2.4).
- The conversational intent-authoring skill (WS-2.3) — though WS-2.3 will be authored as the next real
  intent package under the new `software-delivery` profile once this workstream ships (dogfood ladder).
- Any orchestrator / work-unit execution machinery (Phase 3).
- Profile versioning (no packages depend on a specific profile shape yet — see §6).
- The pre-existing check-H/`CanonicalError` robustness backlog item — real but unrelated to profiles;
  stays a separate small fix, not bundled here (keeps AC-002's "universal suite unchanged" claim clean).

---

## 2. Module layout and dispatch

```
src/intent_packages/profiles/
  __init__.py              # PROFILES registry + validate_profile(package) entrypoint
  software_delivery.py      # validate(package) -> list[str]
  infrastructure_change.py  # validate(package) -> list[str]
```

```python
# profiles/__init__.py
PROFILES: dict[str, Callable[[dict], list[str]]] = {
    "software-delivery": software_delivery.validate,
    "infrastructure-change": infrastructure_change.validate,
}

def validate_profile(package: dict) -> list[str]:
    name = package.get("profile")
    if name is None:
        return []  # universal-only package: unaffected (AC-003)
    if name not in PROFILES:
        return [f"profile: unknown profile {name!r}; valid: {sorted(PROFILES)}"]
    return PROFILES[name](package)
```

`validate_profile()` is called from the existing `validate_package()` (in `schema.py`) as one more
check in the list alongside A/T/J/K/H/O/L — **check P** — after the universal structural and semantic
checks pass. This is a plain function addition; no change to any existing check, the hash, or the
lifecycle.

Each profile's `validate(package)`:
1. Validates its own `profile_fields` sub-schema (required keys present, correctly typed/enumerated).
2. Runs the evidence-tag check (§5) over the existing universal `acceptance[]` list.

No new top-level `package.yaml` keys are introduced. Everything a profile needs either lives under
`profile_fields` (opaque to universal validation) or is a validation rule over fields the universal
schema already has (`acceptance[].evidence`).

---

## 3. Software-delivery profile

### 3.1 `profile_fields` schema
```yaml
profile_fields:
  repo: "AlobarQuest/intent-packages"          # non-empty string
  branch: "feat/ws22-domain-profiles"          # non-empty string
  deploy_target: "coolify:intent-packages-prod" # string or null (pre-deploy)
  required_checks:                              # non-empty list of non-empty strings
    - "ci:validate.yml"
    - "ci:pytest"
  rollback_plan: "git revert; redeploy prior image"  # non-empty string
```

Validation: `repo`, `branch`, `rollback_plan` non-empty strings; `deploy_target` string or `null`;
`required_checks` a non-empty list of non-empty strings. Missing/mistyped key → field-pathed error
(matching the universal validator's actionable-message convention, §6 of the WS-2.1 spec).

### 3.2 Evidence tags
Every `acceptance[].evidence` string in a `profile: software-delivery` package must start with one of
the exact prefixes `ci:`, `gate:`, `scan:`, `review:`, `human:` (case-sensitive; text after the colon —
with or without a leading space — is free-form, e.g. `ci: validate.yml passes on PR` and
`ci:validate.yml passes` both match). An evidence string starting with none of these five is a hard
error listing the valid prefixes. This is what AC-004 requires: an evidence type with no real producer
behind it (the five tags map respectively to CI checks, code-standards Gate A/B results, security-scan
results, `/code-review` verdicts, and human review) cannot pass.

---

## 4. Infrastructure-change profile

### 4.1 `profile_fields` schema
```yaml
profile_fields:
  blast_radius: "single-app"        # enum: single-app | shared-service | portfolio-wide
  change_window: null                # string or null
  backup_evidence: "vps-backup recipe D run 2026-07-04"  # string or null
  rollback_plan: "restore from pre-change snapshot"       # non-empty string
```

Validation: `blast_radius` must be one of the three enum values; `change_window`/`backup_evidence`
string-or-null; `rollback_plan` non-empty string.

### 4.2 Evidence tags
Every `acceptance[].evidence` string in a `profile: infrastructure-change` package must start with one
of the exact prefixes `health:`, `backup:`, `change-log:`, `human:`. Same matching rule as §3.2
(case-sensitive prefix; optional space after the colon). An evidence string starting with none of these
four is a hard error naming them.

---

## 5. Evidence-type vocabulary (AC-004) — design rationale

The master plan's WS-2.2 description centers on mapping acceptance-criteria evidence to concrete
producers the stack already has. The approved package's original scope didn't say this explicitly; it
was added via `revise` during this design session (§7) as AC-004, at Devon's direction, specifically so
the acceptance criteria — not just prose scope — carry the constraint.

Mechanism: a **tag-prefix convention** on the existing `acceptance[].evidence` string (already part of
the universal schema — no new field). Each profile owns a small fixed set of tags corresponding to real
producers in this stack:

| Profile | Tags | Real producer |
|---|---|---|
| software-delivery | `ci:` | a named CI check (e.g. GitHub Actions job) |
| | `gate:` | a code-standards Gate A/B result |
| | `scan:` | a security-scan result |
| | `review:` | a `/code-review` verdict |
| | `human:` | human review |
| infrastructure-change | `health:` | a health-gate URL |
| | `backup:` | a backup/restore verification |
| | `change-log:` | a recorded infra change log entry |
| | `human:` | human review |

This is deliberately **an enum of producers, not an evidence framework** — per Devon's explicit
guardrail, the profile validator checks for a recognized tag prefix; it does not define per-producer
payload schemas (e.g. a typed CI-check-result object). That richer verification layer is Phase-5
territory, not WS-2.2.

---

## 6. Profile versioning — deferred (YAGNI)

No profile-version field today. Two profiles, day one; nothing pins to a specific profile shape yet.
Matches the WS-2.1 precedent of deferring machinery until something actually needs it (package DB,
crypto signing). When a profile's field shape needs to change under packages that already depend on
the old shape, add `profile_fields.profile_version` then — it costs nothing on the universal envelope
since `profile_fields` is already opaque to universal validation.

---

## 7. Dogfood: revise of the WS-2.2 package itself

During this design session, Devon identified that the approved package (revision 1) didn't include an
acceptance criterion for the evidence-type vocabulary, even though the master plan treats it as central
to WS-2.2. Per his direction:
1. `revise packages/ws-2.2-domain-profiles` → revision 2, status back to `draft`.
2. Added a `scope.included` line naming the evidence-type vocabulary explicitly.
3. Added **AC-004**: *"Each profile constrains acceptance-criteria evidence to a vocabulary of producers
   the stack actually has ... and the profile validator rejects an evidence type no real producer can
   satisfy."* (`evidence_type: automated_test`, `approver: policy`.)
4. `transition --to ready_for_review` (re-snapshots the hash), then `approve --approver devon`.
5. `verify-approval` passed (ledger + chain, revision 2, hash `7e3e296e625b41c43dbc2c8e4a2adb00a241e2330a835c6317a248adc7ef417b`).

This is the first real exercise of the `revise` flow (previously only tested synthetically in WS-2.1).

---

## 8. Example packages and test surface

Example packages (one valid + one deliberately-broken per profile) live as **test fixtures**, not real
intents:
```
tests/fixtures/packages/
  example-software-delivery/{package.yaml,lineage.yaml}          # valid
  example-software-delivery-broken/{package.yaml,lineage.yaml}   # e.g. missing required_checks,
                                                                  # or an evidence string with no tag
  example-infrastructure-change/{package.yaml,lineage.yaml}       # valid
  example-infrastructure-change-broken/{package.yaml,lineage.yaml}
```
Kept out of `packages/` deliberately — `packages/` is the log of real intents; CI's `validate --all`
(cwd-anchored to `Path("packages")`, a documented existing quirk) must never sweep sample data, and
there's no risk of an example being mistaken for a real package awaiting approval. Pytest calls
`validate_package()` directly on these fixture paths.

### Test surface
- `profiles/__init__.py` dispatch: unknown profile name → error; `profile: null`/absent → `[]`.
- Each profile's `profile_fields` schema: valid fixture passes; broken fixture fails with an actionable,
  field-pathed message.
- Evidence-tag check: a tagged `evidence` string passes; an untagged/unrecognized-tag one fails, per
  profile's own tag set.
- **AC-002 compatibility proof:**
  1. The full pre-existing WS-2.1 test suite runs unmodified — still 123 passing, no test edited.
  2. A universal-only fixture package (no `profile` key) validates with zero errors and its hash is
     unaffected by the profiles module existing (check P returns `[]` immediately for it).

---

## 9. CI / repo conformance

No changes to `.github/workflows/validate.yml`: it already runs `validate --all` (unaffected, since
fixtures live outside `packages/`) then `pytest` (which picks up the new profile tests automatically,
since they're standard pytest files under `tests/`). `foundation_contract`/`PROJECT.md` frontmatter is
unchanged — no new `required_checks` entry needed.

---

## 10. Exit criteria (WS-2.2 slice)

- [ ] Both profiles validate their own valid example fixture with zero errors, and their broken fixture
      fails with an actionable error (AC-001).
- [ ] The universal envelope is provably unchanged: WS-2.1 suite unmodified and still green; a
      universal-only package's hash and validation are unaffected (AC-002).
- [ ] Devon confirms no software/infra assumption leaked into the universal envelope (AC-003).
- [ ] Each profile's evidence-tag check rejects an evidence string with no recognized producer tag
      (AC-004).
- [ ] Repo stays standards-conformant; no CI file changes needed (§9).
- [ ] Dogfood ladder continues: author WS-2.3 as the next intent package under `profile:
      software-delivery`.
