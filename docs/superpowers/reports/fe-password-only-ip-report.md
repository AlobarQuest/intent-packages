Outcome: done

# FE password-only, increment 2 (intent-packages): build report

PR: https://github.com/AlobarQuest/intent-packages/pull/186 (branch `hq/fe-password-only-ip`,
base `3705e0c`). Not merged.

## What I built

This change implements orchestrator ADR-0055 amendment 26, increment 2, read at orchestrator
`origin/main` against security-standards `60ec80f7`. The amendment's text didn't contradict the
code at `3705e0c`, so I wrote no question file.

- **`chain_db` connects through `factory_events.chain`.** It calls
  `connection_params(READ_ROLE)` strictly, with no fallback to the append role, and passes
  `as_kwargs()` to `psycopg.connect` as keyword parameters, with no positional conninfo. The
  import stays lazy (`import_module`), so the top level is still stdlib-only. `READ_DSN_VAR`
  retires. A `ChainError` from `connection_params`, meaning a missing or retired setting, logs
  `outcome: refused` and prints the refusal's text on stderr. That text names only the variable,
  for example `FACTORY_EVENTS_DB_HOST is not set`. Any later failure stays type-only. A
  security-standards checkout older than amendment 26 (no `connection_params`) reports as a
  logged `failure` (`AttributeError`), not a traceback.
- **The mode check in `default_chain_checker` uses the password names.** It checks the retired
  variables first, so a set `FACTORY_EVENTS_APPEND_DSN`, `_READ_DSN`, or `_IMPORT_DSN` refuses by
  name in every mode. Otherwise it would fall back to the file chain without a word. After that,
  `FACTORY_EVENTS_READ_PASSWORD` selects the database, and `FACTORY_EVENTS_APPEND_PASSWORD` alone
  refuses to read the file. No refusal message carries a value.
- **The emitter redacts values without parsing.** `redact_chain_dsns` and `CHAIN_DSN_VARS` are
  replaced by `redact_chain_passwords`, `APPEND_PASSWORD_VAR`, `READ_PASSWORD_VAR`, and
  `RETIRED_CHAIN_VARS`. It redacts each set password's value, and any set retired variable's whole
  value, longest first, and the DSN parsing is gone. `_events_env` still copies the whole
  environment: that passes the passwords and the three settings through, plus a set retired
  variable, so the child can refuse it by name. Only its docstring changed. The names live in
  `emitter`, and `operations` and `tests/conftest.py` import them.
- **Docs.** `CLAUDE.md`'s invariant and ADR-0001's chain bullet describe the passwords, the three
  settings, and the retired-variable refusal. A comment in `scripts/check-integration.sh` now says
  "test DSN".

## Tests and checks run

| Check | Result |
|---|---|
| `make check` (ruff, ruff format, pyright, pytest) | ruff clean; pyright 0 errors, 0 warnings, 0 informations; **collected 1,363 items, 10 deselected, 1,353 selected, 1,353 passed** |
| `SECURITY_STANDARDS_DIR=<scratch> scripts/check-integration.sh` | **10 passed** (the 10 integration tests `make check` deselects) |
| Security scanner, from the repo root | 0 BLOCK, 1 WARN, 1 INFO |

`make check` and the integration run both show one pytest warning: `anyio`'s
`PytestRemovedIn10Warning` from `site-packages`. It doesn't come from this change.

**How I ran the integration tests.** I extracted security-standards `60ec80f7` with
`git archive` into a new scratch directory, `/tmp/w148-ss.JFC3`, and built its own
`.venv-events` there (`uv venv --python 3.14`, then `uv pip install -e '.[events]'`). The
security-standards main checkout and its worktrees didn't change. The script started its own
disposable `postgres:16-alpine` container on a random local port. No test touched the VPS
database.

**What the security scanner found.** The WARN is `bws.reference-by-stable-uuid` in
`tests/factory/fixtures/infra_rules.json`, a file this change doesn't touch. The INFO is the
judgment-only `bws.least-privilege-scope`.

**What the tests cover:**

- **Unit tests** (`tests/test_chain_checker_database_mode.py`) use a fake `factory_events.chain`,
  so the `chain_db` tests take the real branches, not an `ImportError`. They cover:
  - The read password with all three settings passed through in the environment only.
  - Append password alone refuses with no subprocess.
  - All three retired variables refuse, with and without a password set, with no subprocess.
  - A missing setting refuses by name before any connection.
  - The strict read role.
  - An old checkout reports `AttributeError`.
  - Connect kwargs are exactly host, port, dbname, `user=factory_events_read`, and password, with
    no positional argument.
  - Emitter redaction over passwords holding `@`, `%`, a space, and quotes; one password inside
    another; and a retired value redacted whole.
- **Distinctive placeholder passwords** (`READ-PW-placeholder-7f3c`, `APPEND-PW-placeholder-9d1e`,
  `RETIRED-PW-placeholder-41ab`) are asserted absent from exception text, `caplog`, stdout, and
  stderr.
- **Integration tests** (`tests/test_chain_db_integration.py`) set the parts. Host and port come
  from `FACTORY_TEST_DSN`, the database name is the per-test database, and each role gets a
  different throwaway password. The tests cover:
  - Unreachable database: the port setting changed to `1`.
  - A refused password: the read role given the append role's password.
  - A missing `FACTORY_EVENTS_DB_HOST`, refused by name from the real `factory_events.chain`.
  - A failed append: the append role given the read role's password. It writes nothing.

  `_event_ids` reads through the owner fixture DSN. No test sets a retired variable except to
  prove it refuses.

## Files changed

- `src/intent_packages/chain_db.py`
- `src/intent_packages/operations.py`
- `src/intent_packages/emitter.py`
- `tests/conftest.py` (the autouse scrub covers the passwords, the three settings,
  `FACTORY_EVENTS_OWNER_DSN`, and the retired variables)
- `tests/test_chain_checker_database_mode.py`
- `tests/test_chain_db_integration.py`
- `CLAUDE.md`
- `docs/decisions/0001-approval-chain-is-the-audit-trail.md`
- `scripts/check-integration.sh` (comment only)

## Self-review

I ran `/code-review` at medium on the diff and fixed four findings in the second commit:

- **Retired-value redaction.** A set retired variable's value now gets redacted too, because
  `_events_env` deliberately passes it to the child.
- **One home for the names.** The variable names were in three places; they're in one now.
- **Old checkouts.** An `AttributeError` from a pre-amendment-26 checkout became a traceback with
  exit 1; it's now a logged failure.
- **Typing and duplication.** `params: Any` is now a `Protocol`, and `main`'s duplicated
  failure bodies collapse into one helper.

I didn't change the following findings, for these reasons:

- **`FACTORY_EVENTS_IMPORT_DSN` refuses even in file mode.** That's required: amendment item 5
  says a set retired variable refuses in both parents' mode checks.
- **Short passwords garble the redacted text, and percent-encoded forms aren't covered.** The
  value is a bare password, and a garbled message is the safe side.

## Concerns

- **A fetch in the orchestrator repository.** I ran `git fetch` in `~/Projects/orchestrator`
  (not a pull, checkout, branch, or edit) to read the ADR at `origin/main`. The handoff
  allows `git show origin/main:`; the fetch only moved remote-tracking refs. I'm flagging it
  because the rule names that tree.
- **The integration suite depends on the checkout version.** Against a security-standards
  checkout older than `60ec80f7`, the integration suite fails, as the amendment's "Increments"
  paragraph expects.
- **One design choice the amendment doesn't settle.** `chain_db` prints `factory_events.chain`'s
  refusal text on stderr. That's how "refuses by name" reaches an operator. It's safe only because
  `chain.py` at `60ec80f7` builds those messages from variable names alone. If security-standards
  ever puts a value in a `ChainError` raised from `connection_params`, this line would print it.
- **Scratch directory.** `/tmp/w148-ss.JFC3` (the scratch checkout and its venv) is still there:
  the `rm -rf` was denied. It holds no credential.

## Standards followed

- **Code Brain rule 5 (no secrets in logs).** No log record, exception message, or repr holds a
  password. `chain_db` logs only outcome and type, plus a refusal text that names a variable.
  `ConnectParams` goes straight into `psycopg.connect`. Emitter errors redact every set password
  and retired value. Tests assert distinctive placeholders absent from exceptions, `caplog`,
  stdout, and stderr. The integration `Dsn` keeps its redacted repr.
- **Code Brain rule 4 (no silent swallow).** Each `except` in `chain_db.main` logs a structured
  record and returns `UNAVAILABLE`, which the parent raises as `ChainUnavailable`. Each one
  carries an inline justification.
- **Code Brain rule 3 (structured JSON logs to stdout).** I added no logging path and no file
  logging. The `refused` outcome uses the existing JSON-to-stdout `_log`.
- **Infra Brain 591, 592, 593 (no BWS token in tracked files).** No token appears anywhere. The
  scanner shows 0 BLOCK, and the write-guard didn't fire.
- **Infra Brain 1032 (`cred.exposure-rotate`).** No tool showed me a credential value. I fetched
  no BWS secret and called no infraops tool. The only passwords in this session were placeholders
  and per-run random throwaways for a disposable container.
- **Infra Brain 3035 (`bws.secret-holds-value-only`) and build-agent-secrets rule 7.** The code
  reads only a bare password per role, plus non-secret host, port, and database-name settings. No
  whole-DSN variable is accepted for the append or read role, tests included.
