Outcome: done

# FE-2 build report: the emitter and the chain checker on the database chain

Handoff: `lanes-inc-4-fe-2-intent-packages-chain` (goal step 3f-fe, FE-2, fix round 0). Branch
`hq/lanes-inc-4-fe-2-intent-packages-chain` from `origin/main` `97e817d`. Sources read at
orchestrator `4953fe10`: ADR-0059 amendment 7 (FE-2) and ADR-0055 amendment 24 (items 5, 7, 8, 9,
10, and 13). FE-1 read at security-standards `origin/main` `e89f69b`.

## What was built

### The emitter (item 7)

`FactoryEventsEmitter.emit` already copied the whole environment into the `factory_events emit`
subprocess at `97e817d`, so `FACTORY_EVENTS_APPEND_DSN` already reached FE-1's `emit`. No behavior
changed in what reaches the subprocess. The environment construction moved into one helper, `emitter._events_env`, which the
emitter, the file-chain verify, and the database reader share; its docstring states that copying
the whole environment is what passes the chain DSNs through. A failed append (non-zero exit) stays
an `EmitError`, so `do_approve` aborts before the lineage is written. The `EmitError` message
still carries the child's stderr, which FE-1 limits to the error's type. It now also passes
through `redact_chain_dsns`, which replaces any set chain DSN and its password (URL or key=value
form) with a marker, so the rule doesn't rest on FE-1's contract alone. Tests pin the passthrough
(DSN in `env`, never in argv) and the failure, both with a faked subprocess and against a real
database (the read role's refused `INSERT`).

### The chain checker (items 8 and 10)

`default_chain_checker` in `src/intent_packages/operations.py` has three modes:

- **`FACTORY_EVENTS_READ_DSN` set:** it runs `python -m intent_packages.chain_db <hash> <revision>`
  under security-standards' events interpreter. Exit 0 returns True, exit 10 (a verified chain
  with no match) returns False, and anything else, including a timeout or `OSError`, raises
  `ChainUnavailable`. The file is never read.
- **Only `FACTORY_EVENTS_APPEND_DSN` set:** it raises `ChainUnavailable` and reads nothing. See
  the first concern.
- **Neither set:** the file path, exactly as before (`factory_events verify`, then the JSONL
  scan).

### Where the one-snapshot read lives, and why

The read lives in `src/intent_packages/chain_db.py`, run as a subprocess under
`<security-standards>/.venv-events/bin/python` with security-standards `src` and intent-packages
`src` on `PYTHONPATH`. It opens one connection, sets it read-only at repeatable read, and in one
transaction streams FE-1's documented reader `SELECT` (`seq, prev_hash, hash, event_id, event
ORDER BY seq`, from FE-1's README) through a named cursor into **FE-1's own walker,
`factory_events.store.walk_records`**. While the rows stream past, it notes any `package.approved`
event whose evidence matches the hash and revision (the same `evidence_matches` the file path uses,
moved into `chain_db` so there's one copy). A match counts only if the walk reports no error.

The design follows from these facts:

- **FE-1's walk can't do the match.** `db.verify` returns only a `WalkResult` (errors, head,
  count, anchor hash). Calling it and then querying again would be two snapshots, which item 8
  forbids.
- **No security-standards change is needed.** `store.walk_records` is public, and the `SELECT` is
  the documented contract for readers in other repositories. The reader imports none of FE-1's
  private names (`db._connect`, `db._rows_as_records`).
- **It's a subprocess, not an import.** intent-packages' runtime has no psycopg, and the repo runs
  zero-install (`PYTHONPATH=src python3 -m intent_packages`). The events interpreter holds psycopg
  and `factory_events`, and the file path and the emitter already shell out to it. ADR-0055 item 9
  also describes intent-packages' chain read as a subprocess.
- **The result is an exit code.** stdout carries only the JSON log record (item 13), so no output
  parsing is needed, and an unknown exit code fails closed.

**Duplicated code, and the smallest FE-1 addition that would remove it:** `chain_db` repeats FE-1's
connect settings and its row-to-record adapter (about 20 lines). A match hook on `db.verify` would
let `chain_db` call FE-1's transaction directly, for example `db.verify(dsn, visit=callback)`,
where `visit` is called with each record in the same snapshot. That addition is optional; FE-2
doesn't depend on it.

## Tests and checks run

All runs were in this worktree.

- **`make check`:** green. ruff, ruff format, and pyright report 0 errors. pytest reports
  **1,332 passed, 9 deselected** (the 9 are the integration tests). The 1,332 include 20 new
  default-run tests in `tests/test_chain_checker_database_mode.py`.
- **Database tests:** `SECURITY_STANDARDS_DIR=<FE-1 checkout> scripts/check-integration.sh` reports
  **9 passed, 1,332 deselected** against a throwaway `postgres:16-alpine` container. The
  container listened on a random `127.0.0.1` port with a random password and was removed on exit.
  The local security-standards main checkout is at `1baec77`, before FE-1, so the run used
  `git archive e89f69b` extracted to a scratch directory with `.venv-events` symlinked in.
- **Mutation checks:** with `chain_db`'s `if errors:` branch disabled, the broken-chain
  integration test failed. With `conn.read_only = True` deleted, the default-run transaction test
  failed. I restored the file after each.
- **`/code-review` (medium) on the diff:** 9 items, none changed. See the self-review.

The integration tests cover the following cases: match; no match (wrong revision, wrong hash); an
empty chain returns False; a broken chain raises even with the match present; an unreachable
database raises with the password absent from the error, stdout, and stderr; a refused role (wrong
password) raises; with the read DSN set and a real FE-1 file chain holding the approval, the check
returns False because the database lacks it (the same file returns True with neither DSN set); the
emitter appends through the append role and returns the id that `emit` printed, and the file is
untouched; and a refused append raises `EmitError`, writes nothing, and leaves the password out of
the message.

The default-run tests cover the following cases: the exit-code mapping (0, 10, and every other
code, timeout, and `OSError`); the DSN in `env` and never in argv; a read DSN with a matching file
returning False when the database reader says no match; append-only mode raising with no
subprocess; neither DSN keeping the file path; and the reader's failure log being JSON, by type,
and free of the DSN; the emitter's error with a leaked DSN or password in stderr, in three DSN
forms, redacted; and, with a fake driver, one connection whose single `SELECT` runs read-only, at
repeatable read, inside the transaction, with the rows consumed before it closes.

## Files changed

- `src/intent_packages/chain_db.py` (new): the one-snapshot reader, `evidence_matches`, and exit
  codes.
- `src/intent_packages/operations.py`: `default_chain_checker` modes,
  `_database_chain_has_matching_approval`, and `_evidence_matches` moved to `chain_db`.
- `src/intent_packages/emitter.py`: the `_events_env` helper, and `redact_chain_dsns` on the
  `EmitError` text.
- `tests/test_chain_checker_database_mode.py` (new) and `tests/test_chain_db_integration.py` (new).
- `tests/conftest.py`: an autouse fixture that removes the chain DSN variables, so no test reaches
  an ambient real DSN (FE-1's fixture).
- `scripts/check-integration.sh` (new): mirrors FE-1's script.
- `pyproject.toml` and `uv.lock`: the `integration` marker, `addopts = "-m 'not integration'"`,
  and `psycopg[binary]>=3.3.6` in the `dev` dependency group, for the integration fixture only.
- `docs/decisions/0001-approval-chain-is-the-audit-trail.md`: one sentence on the read DSN.
- `CLAUDE.md`: one invariant line naming the reader, the append-only behavior, and the test
  command.

## Self-review

The `/code-review` items, and why none changed the code:

- **The reader's JSON log reaches the caller's stdout.** This is intended (item 13, rule 3). The
  only in-repo caller of `verify_approval` is the `verify-approval` CLI, and the orchestrator reads
  only its exit code (`package_sources.py`, `_verify_with_intent_packages_cli`).
- **The match is noted before the walker checks the row.** A match is trusted only when
  `walk_records` reports no error, and the walker yields no error-free result past a break. A unit
  test pins that a broken walk with a match returns `UNAVAILABLE`.
- **A jsonb `event` column would break every read.** FE-1 stores canonical JSON text, and its own
  reader parses with `json.loads`. The integration tests run against FE-1's real schema.
- **The 30-second timeout.** This is the same bound the file path's verify has. FE-1 owns the walk
  cost measurement (ADR-0055 "Open before building"). A timeout fails closed.
- **The import and owner DSNs aren't guarded.** FE-1's `chain.database_mode()` considers only the
  append and read DSNs, and this matches it.
- **The unparenthesized `except` (PEP 758).** ruff format writes it for the repo's
  Python 3.14 target. Both possible interpreters are 3.14: `.venv-events` is 3.14.3, and the
  fallback is this repo's `>=3.14` runtime.
- **The `except Exception` hides the cause.** This is deliberate. The type is logged and printed to
  the inherited stderr, and the text is dropped because a driver's text can hold the DSN.
- **The readiness probe isn't on the host port.** The script copies FE-1's script; it didn't flake
  in these runs.
- **The private `_events_env` is imported across modules.** This follows the existing pattern for
  `_events_python` and `_security_standards_dir`.

## Concerns

1. **The append DSN alone raises instead of using the file path.** The handoff says that when the
   read DSN isn't set, the file path behaves exactly as today. With only the append DSN set,
   however, "today" would run FE-1's `factory_events verify` against the database (FE-1 falls back
   to the append DSN) and then match against the unverified local file. That is a split-brain,
   fail-open read. The checker raises `ChainUnavailable` there instead. In this repository,
   `verify_approval`'s only caller is the `verify-approval` CLI, and `do_approve` doesn't verify.
   Outside it, the orchestrator's `package_sources.py` (line 168 at `4953fe10`) runs the CLI for
   the carrier, which holds the read DSN, and sds-hq's gate files (for example
   `state/gates/landing-ledger-token-issue.md`, step 4) run it by hand. If such a shell holds only
   the append DSN after FE-5, it now fails closed. Under D-44 B (D-47) only the carrier reads the
   chain, and once FE-5 seals the file, the old path would fail too (the file is gone), so the
   result is the same: no verified approval. Nothing runs this path before FE-5 sets DSNs. HQ can
   reverse this choice if it reads the handoff literally.
2. **The vendored Makefile has no `check-integration` target.** The Makefile header says "Edit
   upstream and `code-standards sync`", so a target added here would show as drift and be removed
   by the next sync. The runner is `scripts/check-integration.sh`, called directly. A
   `check-integration` hook in the code-standards template would be the upstream fix.
3. **CI doesn't run the database tests.** The default CI gate excludes them, as FE-1's does. They
   need a security-standards checkout with FE-1 and its `.venv-events`, which this repo's CI
   doesn't have.
4. **The local security-standards main checkout is at `1baec77`, behind FE-1.** Until it's pulled,
   a live `verify-approval` on this Mac with a read DSN would fail closed, because that checkout
   has no `factory_events.store.walk_records` (the reader's import fails and exits 2). No DSN
   is set before FE-5, so nothing changes today. FE-5 has to ensure each reader's checkout holds
   FE-1.
5. **The standards cover all concerns.** The Standards section covered every concern this change
   touches.

## Standards followed

- **Code Brain 3 (logging):** `chain_db` writes one structured JSON record to stdout per check:
  logger, op, outcome, `seq`, a 12-character head prefix, event count, matched event id, and error
  type. It writes no file. `emit`'s stdout and `_parse_event_id` are untouched; the integration
  test asserts that the emitter returns the id `emit` appended.
- **Code Brain 4 (error handling):** no exception is silently swallowed. The reader's one
  `except Exception` carries an inline justification, logs the error's type, and returns
  `UNAVAILABLE`, which the parent raises as `ChainUnavailable`. The parent chains the cause
  (`from exc`) for `OSError` and `TimeoutExpired`; their text holds argv only, never the DSN. The
  database driver's exception lives in the child process, so its cause can't be chained into the
  parent; that matches FE-1's `from None`, which keeps a driver's text out of every traceback.
  `EmitError` is unchanged.
- **Code Brain 5 (security):** the DSNs travel only in the subprocess environment, never in argv,
  a log, or an exception message. The checker's errors carry only an exit code or an exception
  type; the emitter's error is passed through `redact_chain_dsns`. Tests assert the password is
  absent from errors, stdout, and stderr, including a stderr that repeats the DSN, and the
  integration tests wrap DSNs in a redacted-`repr` type.
- **Infra Brain Database 6:** no schema or migration at build time. The only DDL is FE-1's
  `db_setup`, run by the integration fixture against a per-test throwaway database.
- **Infra Brain Security 591, 592, and 593:** no BWS token anywhere. DSNs come from the
  environment only. Tests use the throwaway container's random password and random role
  passwords; the unit tests use placeholder strings.
- **Infra Brain Security 1032:** no DSN was printed in any log, test output, or this transcript;
  the integration script passes the container password by name.
- **Repo rules:** I ran `make check` and `/code-review`. I didn't merge; the PR waits for Devon.
  The HTTP and CLI transport rules for the `factory` CLI are untouched.
