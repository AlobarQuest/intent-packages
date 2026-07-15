# WS-6.4 Revision 5 Orchestrator Preflight

## Dependency-update proof

The preflight used an isolated worktree of `AlobarQuest/orchestrator` at merged
`main` commit `9444a9adc02dccbd29b10a9b0c99bd589648922d`. The checkout began clean with
`httpx2>=2.5.0` in the `dev` dependency group and `httpx2==2.5.0` in `uv.lock`.

The following ordered commands were run twice against the same checkout:

```console
uv sync --locked
uv add --dev 'httpx2>=2.7.0'
uv lock --check
```

Both passes completed successfully. The first pass installed `httpx2==2.7.0` and
`httpcore2==2.7.0`. The second pass resolved and audited the same environment without
changing the persistent diff. After each pass, `git diff --check` succeeded and the
only persistent changed files were:

- `pyproject.toml`
- `uv.lock`

The SHA-256 of the persistent diff after each pass was
`d3ae0cc614b92312538a2d60d0aa725305dc57fded0874c6fe06eea6a1729984`.

The mutation command authorized by this proof is only:

```console
uv add --dev 'httpx2>=2.7.0'
```

## Verification boundary

The reusable runner does not provide the PostgreSQL service, migrated database, or
test environment used by Orchestrator's full Quality workflow. The authority sequence
therefore verifies dependency installation and lock consistency only. It must not run
the tool-guarded `make check` target in a bare runner environment and interpret skipped
or database-dependent checks as proof.

Orchestrator's repository-owned `Quality` check remains the acceptance gate on the
pull-request head. On the preflight base commit, the check completed successfully in
GitHub Actions run `29428789356`, job `87398062583`.

## Factory prerequisites

- Orchestrator hosts `.github/workflows/factory-runner-pilot.yml` on its default branch.
- The active factory-runner reusable workflow installs and verifies implementation
  commit `5ac7981dfd8be17e74d7a62c7a677c089a48ba3a`.
- The production target allowlist still names only Change Manager. It is not authority
  for Orchestrator and must be replaced only after the revision-5 package,
  decomposition, unit authority, conformance, kill-switch, and dispatch-scope gates.

These facts support authoring revision 5. They do not constitute package approval,
decomposition approval, per-unit authority approval, dispatch authority, verifier
evidence, or permission to merge.

## Proof boundary

The accepted trusted-pilot limitation remains: `repo.edit` can change the semantics of
a repository-owned executable wrapper. This run is not hostile-agent-safe and must not
be cited as hardened semantic command proof. No validation-harness work is part of
revision 5.
