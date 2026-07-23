# WS-6.4 Revision 9 Intent Packages Preflight

This is the sixth and final repository proof of the fan-out, and the factory mutates the
repository the tooling itself lives in. That is fine: it is an ordinary dependency bump on a
feature branch, gated by the same six human approvals and merged by Devon.

## Dependency-update proof

The preflight used a clean `gh repo clone` of `AlobarQuest/intent-packages` at merged `main`
commit `4ecadfd711b8bffd4d9ea4898c2cc4d7c7a9e64e`. The checkout began with `ruff` pinned at
**two jointly-resolved sites** in `pyproject.toml`:

- `[dependency-groups].dev`: `ruff==0.15.21` (an exact pin)
- `[project.optional-dependencies].dev`: `ruff>=0.1` (a floor)

`ruff 0.15.22` is the only available upgrade for this repository — `pyright==1.1.411`,
`pytest>=9.1.1`, and `pyyaml>=6.0.3` are all already at their latest released versions, so ruff
is the sole clean target (and, being the linter itself, the higher-risk one).

### Why the pin is dual-site and a single `uv add` cannot move it

uv resolves dependency groups and optional-dependency extras jointly. A single
`uv add --dev 'ruff>=0.15.22'` (or `--optional dev`) moves one site and then locks, at which
point the still-`==0.15.21` sibling site makes the tree unsatisfiable. This is the same
jointly-resolved constraint proven for security-standards in revision 7; here the two specs are
asymmetric (`==0.15.21` and `>=0.1`) but both are ruff and both must move together. The
authorized sequence therefore edits every site with `--frozen` (no per-add lock), then resolves
the whole tree once with `uv lock`.

### Ordered command list (run twice against the same checkout)

```console
uv add --frozen --dev 'ruff>=0.15.22'
uv add --frozen --optional dev 'ruff>=0.15.22'
uv lock
uv lock --check
```

Both passes completed successfully (`uv lock --check` exited 0 each time). After each pass the
only persistent changed files were:

- `pyproject.toml` (both ruff sites moved to `ruff>=0.15.22`)
- `uv.lock` (ruff resolved to `0.15.22`)

The SHA-256 of the persistent diff after each pass was
`2a4c528955e3f3c0ef57ea8bfac980fd0af06644bdf11ed5dd04408f6da0c0db` (byte-identical across both
passes — the sequence is idempotent).

The mutation commands authorized by this proof are only:

```console
uv add --frozen --dev 'ruff>=0.15.22'
uv add --frozen --optional dev 'ruff>=0.15.22'
uv lock
```

## Bumping the linter does not red its own check

Intent Packages' named check (`Lint, type-check, and test`) runs `ruff` itself, so bumping ruff
is riskier than a runtime-library bump: a new ruff release can introduce findings that fail the
very check that gates the pull request. Verified against the base commit under the target
version:

```console
$ uvx ruff@0.15.22 check .
All checks passed!
$ uvx ruff@0.15.22 format --check .
48 files already formatted
```

## Verification boundary

The reusable runner provides only a checkout. The authority sequence therefore verifies
dependency edit and lock consistency only (`uv lock --check`). It must not run the tool-guarded
`make check` target in a bare runner environment and interpret skipped checks as proof.

Intent Packages' repository-owned `Lint, type-check, and test` check remains the acceptance gate
on the pull-request head. On the preflight base commit
`4ecadfd711b8bffd4d9ea4898c2cc4d7c7a9e64e` the check completed successfully in GitHub Actions
run `30000305200`.

## Factory prerequisites (verified 2026-07-23)

- Intent Packages hosts `.github/workflows/factory-runner-pilot.yml` on its default branch,
  calling `AlobarQuest/factory-runner/.github/workflows/factory-runner.yml@main`.
- The four required Actions secrets are present: `FACTORY_RUNNER_TOKEN`,
  `FACTORY_RUNNER_CREDENTIAL_KEY_ID`, `ANTHROPIC_API_KEY`, `FACTORY_PR_TOKEN`.
- The repository is **private**. This does not block the factory: the caller workflow runs in
  Intent Packages' own Actions with its own `GITHUB_TOKEN`, and `factory-runner` is public, so
  the reusable-workflow call and console-script install work regardless of the caller's
  visibility.
- **No open pull requests.** Several stale feature branches exist (old `chore/ws64-*`,
  `codex/*`, and one old `sds/874f8758-attempt-1` from a prior era), but none can collide with
  this run: the factory opens its pull request on a fresh `sds/<unit-id>-attempt-1` branch whose
  unit id differs from any existing branch.
- The production target allowlist still names only InfraOps MCP Server (revision 8) and dispatch
  is disabled. That scope is not authority for Intent Packages and must be replaced only after
  the revision-9 package, decomposition, unit authority, conformance, kill-switch, and
  dispatch-scope gates.

These facts support authoring revision 9. They do not constitute package approval, decomposition
approval, per-unit authority approval, dispatch authority, verifier evidence, or permission to
merge.

## Proof boundary

The accepted trusted-pilot limitation remains: `repo.edit` can change the semantics of a
repository-owned executable wrapper. This run is not hostile-agent-safe and must not be cited as
hardened semantic command proof. No validation-harness work is part of revision 9.
