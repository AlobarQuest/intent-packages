# WS-6.4 Revision 8 InfraOps MCP Server Preflight

This is the first real npm run of the dependency-update factory tooling. The uv and
pip tooling profiles were proven by revisions 4–7; the npm profile
(`intent_packages.profiles.dependency_update._npm_*`) is exercised here for the first
time against a live target.

## Dependency-update proof

The preflight used a clean `git clone` of `AlobarQuest/infraops-mcp-server` at merged
`main` commit `1a86271887b4083a1eb17b41944d66d6e99b36d5`. The checkout began with
`vitest` pinned at a **single site** in `package.json` — `devDependencies` — as
`"vitest": "^4.1.4"`. `vitest 4.1.10` is the target: a patch bump within the 4.1.x
line, the lowest-risk available update.

### Why vitest, and why not the other available updates

The registry offered three clean single-site devDependency bumps as of 2026-07-22:
`prettier ^3.4.2 → 3.9.6`, `tsx ^4.19.2 → 4.23.1`, and `vitest ^4.1.4 → 4.1.10`. The
major bumps in the repo (`typescript → 7`, `eslint → 10`, `zod → 4`) were avoided
because they risk reddening the repository's own checks. Among the safe three:

- `prettier` was avoided because the named check runs `prettier --check`; a 3.4 → 3.9
  jump can change formatting defaults and fail the very check that gates the PR.
- `tsx` was avoided because Dependabot PR #51 (the open `minor-and-patch` group) already
  bumps `tsx`, so it is not a genuinely clean, uncontended site.
- `vitest 4.1.4 → 4.1.10` is a same-minor patch bump, is touched by **no** open
  Dependabot PR, and is the test runner (not a linter/formatter), so it carries the
  least risk of reddening the acceptance check.

### Single-site npm profile

`_npm_discover` finds `vitest` only in `devDependencies`, so the profile emits a single
`--save-dev --save-exact` mutator and a deterministic grep verifier:

```console
npm install vitest@4.1.10 --save-exact --save-dev
grep -q '"vitest": "4.1.10"' package.json
```

`--save-exact` writes the bare pinned version (`"vitest": "4.1.10"`, no caret), which is
exactly what the grep verifier asserts.

### Ordered command list (run twice against the same checkout)

```console
npm install vitest@4.1.10 --save-exact --save-dev
grep -q '"vitest": "4.1.10"' package.json
```

Both passes completed successfully (the grep verifier exited 0 each time). After each
pass, the only persistent changed files were:

- `package.json` (`vitest` moved to the exact pin `4.1.10`)
- `package-lock.json`

The SHA-256 of the persistent diff (`git diff -- package.json package-lock.json`) after
each pass was
`b1427a6a4b8da5898fa63b0fa20e743eae6ce0bc22cb9420f4e4087c249cc609` (byte-identical
across both passes — the sequence is idempotent).

The mutation command authorized by this proof is only:

```console
npm install vitest@4.1.10 --save-exact --save-dev
```

## Bumping the dependency does not red its own check

InfraOps MCP Server's named check (`Lint, type-check, and test`) runs the vendored
portfolio `make check`, which for this repository executes `eslint .`, `tsc --noEmit`,
and `prettier --check` over `src/**`, `tests/**`, `*.ts`, `*.mjs`, and **`package*.json`**.
The prettier step is the real npm-specific risk: `npm install` rewrites both
`package.json` and `package-lock.json`, and a rewrite that diverges from Prettier's style
would fail the check. Verified against the mutated tree:

```console
$ ./node_modules/.bin/eslint .
(rc=0, no findings)
$ ./node_modules/.bin/tsc --noEmit
(rc=0)
$ ./node_modules/.bin/prettier --check 'src/**/*.ts' 'tests/**/*.ts' '*.ts' '*.mjs' 'package*.json'
Checking formatting...
All matched files use Prettier code style!
(rc=0)
```

`make check` does not itself run vitest, but for completeness the suite was run under the
new version and stayed green:

```console
$ ./node_modules/.bin/vitest run
 Test Files  56 passed (56)
      Tests  475 passed (475)
```

(Preflight ran on Node 26 locally; the acceptance gate runs on Node 22 in GitHub Actions.
The steps affected by the bump — package.json formatting, eslint, tsc — are stable across
those versions, and the authoritative gate remains the named check on the pull-request
head.)

## Verification boundary

The reusable runner provides only a checkout — no additional service, migrated database,
or environment. The authority sequence therefore verifies the dependency edit
deterministically (`grep` that the exact pin moved) and names no tool-guarded check that
would exit zero in a bare runner having verified nothing. Because the only verifier is a
deterministic grep, the envelope needs no dependency-install step.

InfraOps MCP Server's repository-owned `Lint, type-check, and test` check remains the
acceptance gate on the pull-request head. On the preflight base commit
`1a86271887b4083a1eb17b41944d66d6e99b36d5` the check completed successfully in GitHub
Actions run `29131755866`.

## Factory prerequisites (verified 2026-07-22)

- InfraOps MCP Server hosts `.github/workflows/factory-runner-pilot.yml` on its default
  branch, calling `AlobarQuest/factory-runner/.github/workflows/factory-runner.yml@main`.
- The four required Actions secrets are present: `FACTORY_RUNNER_TOKEN`,
  `FACTORY_RUNNER_CREDENTIAL_KEY_ID`, `ANTHROPIC_API_KEY`, `FACTORY_PR_TOKEN`.
- The repository is **public**, so a caller's `GITHUB_TOKEN` can install `factory-runner`.
- **The repository is not otherwise clean:** eight open Dependabot pull requests (#4, #5,
  #6, #45, #47, #48, #50, #51) and their branches exist. None can collide with this proof:
  the factory opens its pull request on a fresh `sds/<unit-id>-attempt-1` branch (no
  Dependabot branch shares that name), and none of the open Dependabot PRs touch `vitest`
  (the `minor-and-patch` group bumps `@anthropic-ai/sdk`, `fast-xml-parser`, `tsx`, and
  `typescript-eslint`; the singletons touch `@types/node`, `typescript`, `zod`, and GitHub
  Actions). A merge-time conflict on `package.json`/`package-lock.json` with a later
  Dependabot merge is possible, but that is Devon's decision at the merge gate (AC-011) and
  does not affect the factory run or the named check on the PR head.
- The production target allowlist still names only Security Standards (revision 7). It is
  not authority for InfraOps MCP Server and must be replaced only after the revision-8
  package, decomposition, unit authority, conformance, kill-switch, and dispatch-scope
  gates.

These facts support authoring revision 8. They do not constitute package approval,
decomposition approval, per-unit authority approval, dispatch authority, verifier
evidence, or permission to merge.

## Proof boundary

The accepted trusted-pilot limitation remains: `repo.edit` can change the semantics of a
repository-owned executable wrapper. This run is not hostile-agent-safe and must not be
cited as hardened semantic command proof. No validation-harness work is part of revision 8.
