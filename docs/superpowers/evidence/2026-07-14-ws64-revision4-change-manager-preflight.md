# WS-6.4 Revision 4 Change Manager Preflight

## Original dependency-update proof

The reproducible dependency-update preflight used a clean clone of
`AlobarQuest/change-manager` at base commit
`25fa8dade1f1b27f05c2444e6598801ed9486e20`. At that base, `httpx2` was outdated:
version `2.5.0` resolved before the proof and version `2.6.0` resolved after it.

The following ordered commands were run twice against the same checkout:

```console
uv add --dev 'httpx2>=2.6.0'
uv sync --locked
uv run make check
```

Both passes completed successfully. Each pass ran Ruff, Pyright, and 105 tests, with all
105 tests passing. After both passes, the only persistent changed files were:

- `pyproject.toml`
- `uv.lock`

`git diff --check` passed. The SHA-256 of the persistent diff was
`095a203b047d1910e55baa4c81e08db085b9894109ffab7a6a08de406a221d61`.

The mutation command authorized by this proof is only:

```console
uv add --dev 'httpx2>=2.6.0'
```

## Later caller-pin prerequisite merge

The dependency proof above predates and is distinct from the later caller-workflow pin
change. Change Manager prerequisite PR #25 was squash-merged as
`1f64d0166614574c57663f21dfa33a48682e4a3d`. Its caller pins the reusable workflow `uses`
reference to the full factory-runner commit
`c88a3199df80ccd8d90f752edc57cc8b93ff6354`. It intentionally has no
`runner_revision` input because the merged reusable workflow removed that input.

Because this caller-pin merge changed Change Manager's default-branch head after the original
clean-clone preflight, the original base and diff digest above are reproducibility evidence,
not authorization to dispatch against the later head. The exact three-command sequence must
be rerun twice against the current dispatch base before any production proposal or dispatch.

## Authority-contract prerequisites

- Orchestrator PR #57 merged as `a52d3d2fa46fef1bcdc5aa51cc08d10a2b570f82` and is
  deployed and healthy in Coolify deployment `fyka2gqr856k6fuo0tlrax96` using Linux/amd64
  image repository digest
  `sha256:16d07ce00e762b7fe3f6fe6f26b0ad67155efa963bf9a0808e2a4adacd1f66d3` with
  Alembic head `0014_wsp21_recovery_controls`.
- factory-runner PR #18 merged as `c88a3199df80ccd8d90f752edc57cc8b93ff6354`.

These facts establish the approved `mutation_commands` contract and the target caller
prerequisite for authoring package revision 4. They do not constitute package approval,
decomposition approval, per-unit authority approval, dispatch authority, or terminal
Change Manager evidence.

## Proof boundary

The accepted trusted-pilot limitation remains: `repo.edit` can change the semantics of a
repository-owned executable wrapper. This run is not hostile-agent-safe and must not be cited
as hardened semantic command proof. No validation-harness work is part of revision 4.
