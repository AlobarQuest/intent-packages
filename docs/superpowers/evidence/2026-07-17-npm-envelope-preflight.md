# Task 0 — npm dependency-update envelope preflight (infraops-mcp-server)

Date: 2026-07-17. Purpose: validate, on a scratch copy only, whether an npm
dependency-update envelope shape (mirroring the pip/`requirements.txt` and
uv/pyproject preflights already done for brain and orchestrator) can be used by the
factory — per the recurring CLAUDE.md invariant that authored intent must be
validated against executable reality before it is baked into an authority envelope.
No file in `~/Projects/infraops-mcp-server` was modified; all mutation was run
against throwaway copies (`cp -r` and a separate `git clone`) under the session
scratchpad, both discarded after this evidence was captured.

## Target repository facts

- `AlobarQuest/infraops-mcp-server` is a plain npm project: `package.json` +
  `package-lock.json` at the repo root, `dependencies` and `devDependencies`
  pinned with `^` (caret) ranges throughout.
- It already has its own `.github/workflows/quality.yml` (vendored code-standards
  workflow) which runs `actions/setup-node@v4` (`node-version: "22"`) + `npm ci`
  before `make check` (eslint/prettier/tsc/pytest-equivalent). That is the real
  test surface for this repo — see "Runner-node decision" below for why the
  factory envelope must not depend on it.
- It also already has `.github/workflows/factory-runner-pilot.yml`, which calls
  the reusable `AlobarQuest/factory-runner/.github/workflows/factory-runner.yml@main`
  workflow — the actual dispatch path this preflight is validating for.

## Available upgrade (proves the mutation is not a no-op)

Checked every pinned dependency (`dependencies` + `devDependencies`) against the
npm registry (`npm view <pkg> version`):

| package | section | pinned | latest | upgrade class |
|---|---|---|---|---|
| @anthropic-ai/sdk | dependencies | ^0.104.1 | 0.112.1 | minor (0.x — semver-risky) |
| @modelcontextprotocol/sdk | dependencies | ^1.6.1 | 1.29.0 | minor, large span |
| axios | dependencies | ^1.7.9 | 1.18.1 | minor, large span |
| fast-xml-parser | dependencies | ^5.5.8 | 5.10.1 | minor |
| minisearch | dependencies | ^7.2.0 | 7.2.0 | none |
| ssh2 | dependencies | ^1.16.0 | 1.17.0 | minor |
| zod | dependencies | ^3.23.8 | 4.4.3 | **major** |
| zod-to-json-schema | dependencies | ^3.25.2 | 3.25.2 | none |
| @types/node | devDependencies | ^22.10.0 | 26.1.1 | major |
| @types/ssh2 | devDependencies | ^1.15.0 | 1.15.5 | **patch** |
| tsx | devDependencies | ^4.19.2 | 4.23.1 | minor |
| typescript | devDependencies | ^5.7.2 | 7.0.2 | major |
| vitest | devDependencies | ^4.1.4 | 4.1.10 | **patch** |
| eslint | devDependencies | ^9.18.0 | 10.7.0 | major |
| typescript-eslint | devDependencies | ^8.20.0 | 8.64.0 | minor |
| prettier | devDependencies | ^3.4.2 | 3.9.5 | minor |

Two genuine patch-level (same major.minor, lowest risk) candidates exist:
`@types/ssh2` (pure ambient types, no runtime behavior) and `vitest` (a real dev
tool with an actual patch release). Chose **vitest 4.1.4 → 4.1.10** — a real,
non-trivial dev-dependency bump, single-site (appears only in `devDependencies`,
not duplicated anywhere else in `package.json`), so there is no "name every pin
site" hazard.

## Mutation mechanism (deterministic, idempotent)

```
npm install vitest@4.1.10 --save-exact --save-dev
```

(The runtime-dependency form, for the record, is the same without `--save-dev`:
`npm install <pkg>@<new> --save-exact`.)

Validated twice, independently:

1. **Dirty-copy run** (`cp -r` of the working repo, which already had
   `node_modules/` present from local dev) — first pass produced a diff touching
   both `package.json` and `package-lock.json`; second pass (same command,
   re-run) produced a byte-identical diff.
2. **Fresh-clone run** (`git clone` of the repo — i.e. no `node_modules/` at all,
   matching what a GitHub Actions checkout actually looks like, since
   `node_modules/` is gitignored) — same result: first pass installed all 277
   packages fresh and produced a diff touching both tracked files; second pass
   (`node_modules/` now present) produced a **byte-identical diff** to the first
   (`diff fresh-pass1.diff fresh-pass2.diff` → no output). Idempotent under a
   second execution, which matters because `finalize-run` re-executes the whole
   `allowed_commands` list before committing.

Diffs, exactly as produced:

`package.json` (`devDependencies` block only; note npm re-sorted keys
alphabetically as a side effect — `eslint`/`prettier` moved ahead of `tsx`, and
the exact-pinned `vitest` moved after `typescript-eslint` — and separately
re-serialized the top-level `description` field's `—` escape to a literal
em dash, an unrelated npm JSON-serialization side effect, not a mutator bug):

```diff
   "devDependencies": {
     "@types/node": "^22.10.0",
     "@types/ssh2": "^1.15.0",
+    "eslint": "^9.18.0",
+    "prettier": "^3.4.2",
     "tsx": "^4.19.2",
     "typescript": "^5.7.2",
-    "vitest": "^4.1.4",
-    "eslint": "^9.18.0",
     "typescript-eslint": "^8.20.0",
-    "prettier": "^3.4.2"
+    "vitest": "4.1.10"
   }
```

`package-lock.json` — despite npm reporting "added 277 packages" on the
fresh-clone run (that count is `node_modules/` reconciliation, not lockfile
entries), the tracked lockfile diff is a single pin line:

```diff
-        "vitest": "^4.1.4"
+        "vitest": "4.1.10"
```

`--save-exact` writes the bare version string (`4.1.10`), not `^4.1.10` — the
caret is dropped, confirming the pin is written verbatim as intended.

**Caveat on lockfile churn**: none observed beyond the single expected pin line.
No unrelated transitive-dependency rewrites, no `lockfileVersion` bump, no
`packageIntegrity`/resolved-hash churn on other packages. This is a clean,
minimal diff — better than the pip/requirements case had any right to expect.

## Runner-node decision: node/npm NOT provided to factory-runner's execution environment

`~/Projects/factory-runner/.github/workflows/factory-runner.yml` (the reusable
workflow the pilot calls) runs a single `ubuntu-latest` job whose only toolchain
setup step is `astral-sh/setup-uv@…` (Python/uv, for installing and running the
`factory-runner` CLI itself). There is **no** `actions/setup-node`, no
`node-version` input, and no `npm ci`/`npm install` step anywhere in that
workflow or anywhere else in the factory-runner repo
(`grep -rn -i "setup-node\|node-version" ~/Projects/factory-runner/` → zero hits).

By contrast, `infraops-mcp-server`'s own `quality.yml` explicitly runs
`actions/setup-node@v4` (`node-version: "22"`) + `npm ci` before its `make check`
— i.e. the repo's real CI does not rely on whatever Node happens to ship in the
bare runner image; it pins and installs deliberately. The factory's
`allowed_commands`, however, execute inside the SAME job as the coding action,
with no such step ever run.

`ubuntu-latest` GitHub-hosted runner images do ship a pre-installed Node.js/npm
toolchain (required for the runner's own JS-based actions), so a bare
`npm install <pkg>@<new> --save-exact[--save-dev]` command may well succeed
without an explicit setup step — this preflight cannot prove or disprove that
from a local machine; it can only confirm no such step is provisioned
deliberately, and that the repo's own maintainers judged an explicit, pinned
`setup-node` necessary for real work rather than trusting the ambient image.

This is the same shape of gap as the pip case (WS-6.4 revision 6 preflight):
there, `make check` needed Postgres + `SECURITY_STANDARDS_DIR` the bare runner
doesn't have, so it was excluded from the envelope. Here, the equivalent
uncertainty is Node's presence/version rather than a hard dependency, but the
same rule applies: **the envelope must not depend on an unconfirmed toolchain**.
`npm install` itself is the load-bearing action and needs only the `npm` binary
(no `node_modules` precondition — confirmed by the fresh-clone run above); if
`npm` truly is absent this specific command fails loudly (`command not found`),
it does not silently no-op, which is a materially safer failure mode than a
`command -v`-guarded skip.

## Verifier (deterministic, non-tool-guarded)

```
grep -q '"vitest": "4.1.10"' package.json
```

Confirmed against both states:

- **Before** mutation (unmodified `~/Projects/infraops-mcp-server/package.json`,
  still `"vitest": "^4.1.4"`): `grep -q` returns non-zero — **FAILS**, proving
  the check is not a vacuous pass.
- **After** mutation (either scratch copy, both passes): `grep -q` returns
  zero — **PASSES**.

This is grep-style and non-tool-guarded — no `npm test`, no `command -v`
fallback, no dependency on `node_modules` being present or on any toolchain
beyond a POSIX shell + `grep`, so it does not inherit the runner-node
uncertainty above.

## Pin sites

- `package.json` → `devDependencies["vitest"]` (single site; not duplicated
  elsewhere in the manifest).
- `package-lock.json` → root-level `packages[""].devDependencies.vitest` pin
  line (the one line shown in the diff above; no other `vitest` version strings
  changed anywhere else in the lockfile).

## Resulting authority envelope shape (for an npm dependency-update unit)

- `target_repository`: `AlobarQuest/infraops-mcp-server`
- `change_class`: `dependency-update`
- `required_capability`: `repo.edit`
- `allowed_commands`: `["npm install vitest@4.1.10 --save-exact --save-dev", "grep -q '\"vitest\": \"4.1.10\"' package.json"]`
- `mutation_commands`: `["npm install vitest@4.1.10 --save-exact --save-dev"]`
- mutator ordered before verifier (per the existing invariant that
  `finalize-run` executes `allowed_commands` in order and only then checks
  `git status`).

## Decision

**GO, with one blocking pre-dispatch check** — the npm profile is usable on the
same footing as the pip/uv profiles (deterministic, idempotent, tool-guard-free
verifier), **provided** the factory-runner reusable workflow adds a
`actions/setup-node` step (or an equivalent pinned Node install) before the
coding-action step. Until that step exists, dispatching an npm-shaped unit is a
gamble on ambient runner image contents rather than a confirmed capability — the
same category of mistake the "authored intent never validated against
executable reality" invariant exists to prevent. This preflight found the
mutator and verifier sound; it did **not** find proof that Node is provisioned
to the job that would run them, and that gap should be closed (one
`setup-node` step in `factory-runner.yml`) before the first real npm dispatch,
not discovered by a failed live run.

## Open pre-dispatch checks (not blockers to authoring)

- Add `actions/setup-node@v4` (pin a node-version, e.g. `"22"` to match
  `infraops-mcp-server`'s own `quality.yml`) to
  `factory-runner/.github/workflows/factory-runner.yml`, ahead of the coding
  action step, OR confirm empirically (via a real dispatched run, not a local
  guess) that the ambient `ubuntu-latest` Node satisfies `engines.node >= 18`
  for every repo the npm profile will target.
- Confirm `AlobarQuest/infraops-mcp-server` carries the same
  `FACTORY_RUNNER_TOKEN` / `FACTORY_RUNNER_CREDENTIAL_KEY_ID` /
  `ANTHROPIC_API_KEY` / `FACTORY_PR_TOKEN` Actions secrets and Dispatch GitHub
  App installation as the other piloted repos — it already has
  `factory-runner-pilot.yml`, which is a good sign but was not itself verified
  as functioning end-to-end by this preflight.
