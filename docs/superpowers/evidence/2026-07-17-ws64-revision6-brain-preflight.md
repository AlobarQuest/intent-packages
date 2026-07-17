# WS-6.4 revision 6 — Brain (AC-002) preflight

Date: 2026-07-17. Purpose: validate the Brain AC-002 dependency-update authority envelope
against executable reality **before** authoring and approving revision 6, per the package's
own `scope.included` preflight requirement and the CLAUDE.md invariant that authored intent
must be validated against executable reality first.

## Target repository facts

- `AlobarQuest/brain` is a **pip / `requirements.txt`** repository, not a uv/pyproject
  project. Its `pyproject.toml` carries only tool config (no `[project]`, no dependencies).
  Its `quality.yml` explicitly documents that `uv sync` resolves an empty project and
  uninstalls the environment. Therefore AC-001's `uv sync / uv add / uv lock` envelope does
  **not** transfer.
- Dependencies are pinned in `requirements.txt` (runtime) and `requirements-dev.txt` (dev).

## Available upgrade (proves the mutation is not a no-op)

Checked each `==`-pinned runtime dependency against PyPI latest:

| package | pinned | latest | upgrade |
|---|---|---|---|
| fastapi | 0.139.0 | 0.139.2 | **available** |
| uvicorn | 0.51.0 | 0.51.0 | none |
| sqlalchemy | 2.0.51 | 2.0.51 | none |
| asyncpg | 0.31.0 | 0.31.0 | none |
| alembic | 1.18.5 | 1.18.5 | none |
| pgvector | 0.5.0 | 0.5.0 | none |
| httpx | 0.28.1 | 0.28.1 | none |

Chosen target: **fastapi 0.139.0 → 0.139.2**. `fastapi` appears **only** in
`requirements.txt` (not in `requirements-dev.txt`), so it is single-site — no "name every
pin site" hazard.

## Mutation mechanism (deterministic, idempotent)

There is no `uv add` equivalent for a plain `requirements.txt`. The fingerprinted
`mutation_commands` contract requires a non-empty deterministic mutator that is an ordered
subset of `allowed_commands`, so the mutator is a deterministic text edit:

```
sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt
```

Validated on a COPY (brain's real `requirements.txt` untouched, still `0.139.0`):

- First pass yields a real diff: `fastapi==0.139.0` → `fastapi==0.139.2`.
- Idempotent by construction: the anchored literal `^fastapi==0.139.0$` cannot match after
  the first pass, so `finalize-run`'s second execution of the ordered list leaves the
  identical diff — satisfying the "every command idempotent under a second execution"
  constraint.

## Verifier (runner-honest)

brain's `make check` runs `pyright` + `pytest`, and `tests/conftest.py` requires
`POSTGRES_*` / `DATABASE_URL`. The bare GitHub-hosted factory runner supplies none of these,
so — exactly as for orchestrator — `make check` must **not** appear in brain's envelope. The
envelope's verifier is a deterministic, non-tool-guarded assertion that the pin actually
moved:

```
grep -qx 'fastapi==0.139.2' requirements.txt
```

Because this is not a tool-guarded check that can exit zero having verified nothing, the
envelope is honest without an install-first step (Devon-approved interpretation of the
install-first constraint, 2026-07-17). brain's real tests are gated by its own named
**Quality** check on the pull-request head, which is where AC-002's evidence already lives.

## Resulting authority envelope (for the AC-002 decomposition)

- `target_repository`: `AlobarQuest/brain`
- `change_class`: `dependency-update`
- `required_capability`: `repo.edit`
- `allowed_commands`: `["sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt", "grep -qx 'fastapi==0.139.2' requirements.txt"]`
- `mutation_commands`: `["sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt"]`
- conformance: computed from brain's live repo state via `security_scan.cli.scan` and
  `portfolio.compliance.build_rows`.

## Open pre-dispatch checks (not blockers to authoring)

- Confirm `AlobarQuest/brain` hosts `.github/workflows/factory-runner-pilot.yml` on its
  default branch and carries the `FACTORY_RUNNER_TOKEN`, `FACTORY_RUNNER_CREDENTIAL_KEY_ID`,
  and `ANTHROPIC_API_KEY` Actions secrets, and that the Alobar SDS Dispatch GitHub App is
  installed on it — prerequisites for dispatch, verified before enablement.
