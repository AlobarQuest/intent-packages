# Readiness fixtures — provenance

`gap-repo.v1.json` was captured from a LIVE kit run (never hand-typed):

    uv run --project ~/Projects/project-standards portfolio onboard <constructed gap repo>

against a minimal git repo (README only, file:// origin, current and clean) on
2026-07-30, project-standards main at 6d47319 (WS-P2.11 Inc 1). Regenerate the
same way after any schema change — a hand-edited fixture defeats the
cross-repo contract this consumer exists to honour. The Inc-3 validation pass
refreshes it from the live brain run.

`brain.v1.json` is the LIVE Inc-3 capture: `portfolio onboard ~/Projects/brain`
(kit at project-standards fix/ci-executed-quiet-mode, 2026-07-30). Its queue
(runner.caller @main, profile.declared absent) produced
`packages/brain-onboarding-remediation` via `factory create --from-readiness`.
