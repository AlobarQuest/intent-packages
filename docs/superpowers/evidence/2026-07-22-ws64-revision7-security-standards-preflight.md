# WS-6.4 Revision 7 Security Standards Preflight

## Dependency-update proof

The preflight used a clean `git clone --local` of `AlobarQuest/security-standards`
at merged `main` commit `3435ed2ec105e73c2d74b23525c36e65bb939f34`. The checkout
began with `ruff==0.15.21` pinned at **two jointly-resolved sites** in
`pyproject.toml` — `[project.optional-dependencies].dev` and
`[dependency-groups].dev` — and `ruff==0.15.21` in `uv.lock`. `ruff 0.15.22` is the
only available upgrade for this repository (pyright, pytest, jsonschema, pyyaml, and
psycopg[binary] are all already at their latest pinned versions).

### Why the pin is dual-site and a single `uv add` cannot move it

uv resolves dependency groups and optional-dependency extras jointly. A single
`uv add --optional dev 'ruff>=0.15.22'` (or `--dev`) moves one site and then locks,
at which point the still-`==0.15.21` sibling site makes the tree unsatisfiable:

```
Because security-scan:dev depends on ruff==0.15.21 and security-scan[dev]
depends on ruff>=0.15.22, we can conclude that ... your project's requirements
are unsatisfiable.
help: If you want to add the package regardless of the failed resolution,
      provide the `--frozen` flag to skip locking and syncing.
```

The authorized sequence therefore edits every site with `--frozen` (no per-add
lock), then resolves the whole tree once with `uv lock`.

### Ordered command list (run twice against the same checkout)

```console
uv add --frozen --dev 'ruff>=0.15.22'
uv add --frozen --optional dev 'ruff>=0.15.22'
uv lock
uv lock --check
```

Both passes completed successfully (`uv lock --check` exited 0 each time). After each
pass, `git diff --check` succeeded and the only persistent changed files were:

- `pyproject.toml` (both ruff sites moved to `ruff>=0.15.22`)
- `uv.lock`

The SHA-256 of the persistent diff after each pass was
`d6bcda884bb42a65d1f7a42dc5feffef25394bf2bb6a2f114f90156875470930` (byte-identical
across both passes — the sequence is idempotent).

The mutation commands authorized by this proof are only:

```console
uv add --frozen --dev 'ruff>=0.15.22'
uv add --frozen --optional dev 'ruff>=0.15.22'
uv lock
```

## Bumping the linter does not red its own check

Security Standards' named check runs `ruff` itself, so bumping ruff is riskier than a
runtime-library bump: a new ruff release can introduce findings that fail the very
check that gates the pull request. Verified against the base commit under the target
version:

```console
$ uvx ruff@0.15.22 check .
All checks passed!
$ uvx ruff@0.15.22 format --check .
58 files already formatted
```

## Verification boundary

The reusable runner does not provide any service, migrated database, or environment
beyond a checkout. The authority sequence therefore verifies dependency edit and lock
consistency only (`uv lock --check`). It must not run the tool-guarded `make check`
target in a bare runner environment and interpret skipped checks as proof.

Security Standards' repository-owned `Lint, type-check, and test` check remains the
acceptance gate on the pull-request head. On the preflight base commit, the check
completed successfully in GitHub Actions run `29591269881`.

## Factory prerequisites (verified 2026-07-22)

- Security Standards hosts `.github/workflows/factory-runner-pilot.yml` on its default
  branch, calling `AlobarQuest/factory-runner/.github/workflows/factory-runner.yml@main`.
- The four required Actions secrets are present: `FACTORY_RUNNER_TOKEN`,
  `FACTORY_RUNNER_CREDENTIAL_KEY_ID`, `ANTHROPIC_API_KEY`, `FACTORY_PR_TOKEN`.
- The repository is clean: no open pull requests and only the `main` branch, so the
  revision-7 pull request cannot collide with in-flight work. (The two pilot runs on
  2026-07-10 belong to the non-authoritative rev-3 era and left no artifacts.)
- The production target allowlist still names only Brain (revision 6). It is not
  authority for Security Standards and must be replaced only after the revision-7
  package, decomposition, unit authority, conformance, kill-switch, and dispatch-scope
  gates.

These facts support authoring revision 7. They do not constitute package approval,
decomposition approval, per-unit authority approval, dispatch authority, verifier
evidence, or permission to merge.

## Proof boundary

The accepted trusted-pilot limitation remains: `repo.edit` can change the semantics of
a repository-owned executable wrapper. This run is not hostile-agent-safe and must not
be cited as hardened semantic command proof. No validation-harness work is part of
revision 7.
