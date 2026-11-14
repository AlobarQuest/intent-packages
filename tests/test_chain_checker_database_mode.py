"""The chain checker and emitter under the database chain's passwords and settings (ADR-0055
amendments 24 and 26), with `subprocess.run` faked. The real database paths are in
test_chain_db_integration.py."""

import contextlib
import json
import os
import subprocess
import types
from pathlib import Path

import pytest

from intent_packages import chain_db
from intent_packages.emitter import EmitError, FactoryEventsEmitter, redact_chain_passwords
from intent_packages.operations import ChainUnavailable, default_chain_checker

# Distinctive placeholders: each test that can fail asserts they appear in no output.
READ_PASSWORD = "READ-PW-placeholder-7f3c"
APPEND_PASSWORD = "APPEND-PW-placeholder-9d1e"
RETIRED_VALUE = "postgresql://u:RETIRED-PW-placeholder-41ab@127.0.0.1:1/db"
SETTINGS = {
    "FACTORY_EVENTS_DB_HOST": "127.0.0.1",
    "FACTORY_EVENTS_DB_PORT": "1",
    "FACTORY_EVENTS_DB_NAME": "factory_events",
}
RETIRED = ("FACTORY_EVENTS_APPEND_DSN", "FACTORY_EVENTS_READ_DSN", "FACTORY_EVENTS_IMPORT_DSN")


def _set_settings(monkeypatch) -> None:
    for name, value in SETTINGS.items():
        monkeypatch.setenv(name, value)


def _assert_no_secret(*texts: str) -> None:
    joined = "\n".join(texts)
    for secret in (READ_PASSWORD, APPEND_PASSWORD, "RETIRED-PW-placeholder"):
        assert secret not in joined


def _matching_events_file(home: Path) -> None:
    """A file chain holding the approval, so a file read would answer True."""
    home.mkdir()
    event = {
        "action": "package.approved",
        "evidence": [{"approved_hash": "deadbeef", "revision": 1}],
    }
    (home / "events.jsonl").write_text(json.dumps({"seq": 1, "event": event}) + "\n")


@pytest.fixture
def read_mode(tmp_path, monkeypatch, fake_registry):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path / "factory-home"))
    _matching_events_file(tmp_path / "factory-home")
    monkeypatch.setenv("FACTORY_EVENTS_READ_PASSWORD", READ_PASSWORD)
    _set_settings(monkeypatch)


def _fake_reader(monkeypatch, returncode: int) -> list[dict]:
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, returncode)

    monkeypatch.setattr("intent_packages.operations.subprocess.run", fake_run)
    return calls


def test_read_password_runs_the_one_snapshot_reader_with_the_parts_in_env_only(
    monkeypatch, read_mode
):
    calls = _fake_reader(monkeypatch, chain_db.MATCH)

    assert default_chain_checker("deadbeef", 1) is True

    [call] = calls  # one read: never `factory_events verify` followed by a file scan
    assert call["argv"][1:] == ["-m", "intent_packages.chain_db", "deadbeef", "1"]
    _assert_no_secret(" ".join(call["argv"]))
    assert call["env"]["FACTORY_EVENTS_READ_PASSWORD"] == READ_PASSWORD
    assert {name: call["env"][name] for name in SETTINGS} == SETTINGS
    pythonpath = call["env"]["PYTHONPATH"].split(os.pathsep)
    assert pythonpath[1] == str(Path(chain_db.__file__).resolve().parents[1])


def test_read_password_no_match_returns_false_even_with_a_matching_file(monkeypatch, read_mode):
    _fake_reader(monkeypatch, chain_db.NO_MATCH)

    assert default_chain_checker("deadbeef", 1) is False


@pytest.mark.parametrize("returncode", [chain_db.UNAVAILABLE, 1, 3, -9])
def test_read_password_any_other_exit_raises_without_the_password(
    monkeypatch, read_mode, returncode, capsys, caplog
):
    _fake_reader(monkeypatch, returncode)

    with pytest.raises(ChainUnavailable) as info:
        default_chain_checker("deadbeef", 1)
    out, err = capsys.readouterr()
    _assert_no_secret(str(info.value), out, err, caplog.text)


@pytest.mark.parametrize(
    "error", [subprocess.TimeoutExpired(cmd="reader", timeout=30), OSError("no python")]
)
def test_read_password_reader_failing_to_run_raises(monkeypatch, read_mode, error):
    def fake_run(argv, **kwargs):
        raise error

    monkeypatch.setattr("intent_packages.operations.subprocess.run", fake_run)

    with pytest.raises(ChainUnavailable):
        default_chain_checker("deadbeef", 1)


def test_append_password_without_read_password_raises_and_reads_nothing(monkeypatch, read_mode):
    monkeypatch.delenv("FACTORY_EVENTS_READ_PASSWORD")
    monkeypatch.setenv("FACTORY_EVENTS_APPEND_PASSWORD", APPEND_PASSWORD)
    calls = _fake_reader(monkeypatch, 0)

    with pytest.raises(ChainUnavailable, match="refusing to read the file chain") as info:
        default_chain_checker("deadbeef", 1)
    _assert_no_secret(str(info.value))
    assert calls == []


@pytest.mark.parametrize("with_password", [True, False])
@pytest.mark.parametrize("retired", RETIRED)
def test_a_set_retired_variable_refuses_by_name_and_reads_nothing(
    monkeypatch, read_mode, retired, with_password
):
    if not with_password:  # without a password the file would answer True: it must not
        monkeypatch.delenv("FACTORY_EVENTS_READ_PASSWORD")
    monkeypatch.setenv(retired, RETIRED_VALUE)
    calls = _fake_reader(monkeypatch, chain_db.MATCH)

    with pytest.raises(ChainUnavailable, match=f"{retired} is retired") as info:
        default_chain_checker("deadbeef", 1)
    _assert_no_secret(str(info.value))
    assert calls == []


def test_neither_password_keeps_the_file_path(tmp_path, monkeypatch, fake_registry):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path / "factory-home"))
    _matching_events_file(tmp_path / "factory-home")
    _set_settings(monkeypatch)  # the settings alone select nothing
    calls = _fake_reader(monkeypatch, 0)

    assert default_chain_checker("deadbeef", 1) is True
    [call] = calls
    assert call["argv"][1:] == ["-m", "factory_events", "verify"]


# --- the reader's own reporting, with a fake factory_events.chain -----------------------


class _ChainError(RuntimeError):
    pass


class _Params:
    """Stands in for factory_events.db.ConnectParams."""

    def __init__(self, role: str):
        self.role = role

    def as_kwargs(self) -> dict[str, str]:
        return {
            "host": SETTINGS["FACTORY_EVENTS_DB_HOST"],
            "port": SETTINGS["FACTORY_EVENTS_DB_PORT"],
            "dbname": SETTINGS["FACTORY_EVENTS_DB_NAME"],
            "user": self.role,
            "password": READ_PASSWORD,
        }


def _fake_chain(monkeypatch, refusal: str | None = None, **modules: object) -> list[str]:
    """Install a fake `factory_events.chain` (and `modules`, by dotted name) for chain_db's
    lazy imports. Returns the roles `connection_params` was asked for."""
    roles: list[str] = []

    def connection_params(role: str) -> _Params:
        roles.append(role)
        if refusal:
            raise _ChainError(refusal)
        return _Params(role)

    chain = types.SimpleNamespace(
        READ_ROLE="factory_events_read",
        connection_params=connection_params,
        db=types.SimpleNamespace(ChainError=_ChainError),
    )
    table = {"factory_events.chain": chain, **modules}
    monkeypatch.setattr(chain_db, "import_module", table.__getitem__)
    return roles


def test_reader_without_factory_events_is_unavailable(capsys):
    # This venv has no factory_events: the lazy import fails, and that is a refusal too.
    assert chain_db.main(["deadbeef", "1"]) == chain_db.UNAVAILABLE
    record = json.loads(capsys.readouterr().out)
    assert record["outcome"] == "failure" and record["error_type"] == "ModuleNotFoundError"


def test_reader_refuses_a_missing_setting_by_name_before_any_connection(monkeypatch, capsys):
    _fake_chain(monkeypatch, refusal="FACTORY_EVENTS_DB_HOST is not set")
    monkeypatch.setattr(chain_db, "_walk", lambda *a: pytest.fail("connected after a refusal"))

    assert chain_db.main(["deadbeef", "1"]) == chain_db.UNAVAILABLE
    out, err = capsys.readouterr()
    record = json.loads(out)
    assert record["outcome"] == "refused" and record["error_type"] == "_ChainError"
    assert "FACTORY_EVENTS_DB_HOST is not set" in err


def test_reader_asks_strictly_for_the_read_role(monkeypatch, capsys):
    roles = _fake_chain(monkeypatch)
    monkeypatch.setattr(chain_db, "_walk", lambda *a: ([], None, 0, []))

    assert chain_db.main(["deadbeef", "1"]) == chain_db.NO_MATCH
    assert roles == ["factory_events_read"]


def test_reader_failure_logs_json_by_type_and_never_the_password(monkeypatch, capsys, caplog):
    _fake_chain(monkeypatch)

    def refuse(params, approved_hash, revision):
        # A driver's text can repeat connection details, the password included.
        raise RuntimeError(f"connection failed: {params.as_kwargs()}")

    monkeypatch.setattr(chain_db, "_walk", refuse)

    assert chain_db.main(["deadbeef", "1"]) == chain_db.UNAVAILABLE
    out, err = capsys.readouterr()
    record = json.loads(out)
    assert record["outcome"] == "failure" and record["error_type"] == "RuntimeError"
    _assert_no_secret(out, err, caplog.text)


def test_reader_maps_walk_results_to_exit_codes(monkeypatch, capsys):
    _fake_chain(monkeypatch)
    head = {"seq": 2, "hash": "ab" * 32}
    outcomes = {
        "match": ([], head, 2, ["ev-1"]),
        "no-match": ([], head, 2, []),
        "broken": (["seq 2: hash mismatch (line tampered)"], head, 1, ["ev-1"]),
    }
    codes = {}
    for name, result in outcomes.items():
        monkeypatch.setattr(chain_db, "_walk", lambda *a, result=result: result)
        codes[name] = chain_db.main(["deadbeef", "1"])
        assert json.loads(capsys.readouterr().out)["outcome"] == name

    assert codes == {
        "match": chain_db.MATCH,
        "no-match": chain_db.NO_MATCH,
        "broken": chain_db.UNAVAILABLE,  # a match in a broken chain is not a match
    }


def test_records_note_only_a_matching_approval():
    def row(seq, action, approved_hash, revision):
        event = {
            "event_id": f"ev-{seq}",
            "action": action,
            "evidence": [{"approved_hash": approved_hash, "revision": revision}],
        }
        return (seq, "p", "h", f"ev-{seq}", json.dumps(event))

    rows = [
        row(1, "package.transitioned", "deadbeef", 1),
        row(2, "package.approved", "deadbeef", 2),
        row(3, "package.approved", "deadbeef", 1),
        (4, "p", "h", "ev-4", "{not json"),
    ]
    matches: list[str] = []
    records = list(chain_db._records(rows, "deadbeef", 1, matches))

    assert matches == ["ev-3"]
    assert records[3]["event"] is None  # the walker reports it as tampered
    assert records[2]["event_id"] == "ev-3"


# --- the emitter under the append password ----------------------------------------------


def _emit_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))
    monkeypatch.setenv("FACTORY_EVENTS_APPEND_PASSWORD", APPEND_PASSWORD)
    _set_settings(monkeypatch)


def test_emitter_passes_the_append_password_and_settings_through_in_env_only(monkeypatch, tmp_path):
    _emit_env(monkeypatch, tmp_path)
    captured = {}

    def fake_run(argv, capture_output, text, env, timeout):
        captured.update(argv=argv, env=env)
        return subprocess.CompletedProcess(argv, 0, stdout="ev-9\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert FactoryEventsEmitter().emit("package.approved", "pkg", {}) == "ev-9"
    assert captured["env"]["FACTORY_EVENTS_APPEND_PASSWORD"] == APPEND_PASSWORD
    assert {name: captured["env"][name] for name in SETTINGS} == SETTINGS
    _assert_no_secret(" ".join(captured["argv"]))


def test_emitter_failed_append_raises_emit_error(monkeypatch, tmp_path):
    _emit_env(monkeypatch, tmp_path)

    def fake_run(argv, capture_output, text, env, timeout):
        # FE-1's emit reports a failed append by the error's type only.
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="emit failed: append failed (OperationalError)\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(EmitError, match="OperationalError"):
        FactoryEventsEmitter().emit("package.approved", "pkg", {})


@pytest.mark.parametrize(
    "password",
    [APPEND_PASSWORD, "p@ss-placeholder", "50%25-placeholder", "kv pw-placeholder", "q'uo\"te"],
)
def test_emitter_error_never_repeats_a_chain_password(monkeypatch, tmp_path, password):
    _emit_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FACTORY_EVENTS_APPEND_PASSWORD", password)

    def fake_run(argv, capture_output, text, env, timeout):
        leak = f"authentication failed for password {password} at 127.0.0.1\n"
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr=leak)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(EmitError) as info:
        FactoryEventsEmitter().emit("package.approved", "pkg", {})
    message = str(info.value)
    assert password not in message
    assert "<FACTORY_EVENTS_APPEND_PASSWORD redacted>" in message


def test_redaction_replaces_the_longer_password_whole(monkeypatch):
    # One password containing the other must not leave a fragment of the longer one behind.
    monkeypatch.setenv("FACTORY_EVENTS_READ_PASSWORD", "shared")
    monkeypatch.setenv("FACTORY_EVENTS_APPEND_PASSWORD", "shared-and-longer")

    assert redact_chain_passwords("a=shared-and-longer r=shared") == (
        "a=<FACTORY_EVENTS_APPEND_PASSWORD redacted> r=<FACTORY_EVENTS_READ_PASSWORD redacted>"
    )


# --- the reader's transaction, with a fake driver --------------------------------------


class _FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.read_only = None
        self.isolation_level = None
        self.in_transaction = False
        self.executed: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextlib.contextmanager
    def transaction(self):
        self.in_transaction = True
        yield
        self.in_transaction = False

    @contextlib.contextmanager
    def cursor(self, name):
        conn = self

        class Cursor:
            def execute(self, query):
                conn.executed.append(
                    (query, conn.read_only, conn.isolation_level, conn.in_transaction)
                )

            def __iter__(self):
                assert conn.in_transaction, "rows read outside the transaction"
                return iter(conn.rows)

        yield Cursor()


def test_reader_walks_and_matches_in_one_read_only_repeatable_read_transaction(monkeypatch):
    event = {"action": "package.approved", "evidence": [{"approved_hash": "h", "revision": 1}]}
    conn = _FakeConn([(1, "0" * 64, "a" * 64, "ev-1", json.dumps(event))])
    connects: list[tuple] = []

    def connect(*args, **kwargs):
        connects.append((args, kwargs))
        return conn

    psycopg = types.SimpleNamespace(
        connect=connect, IsolationLevel=types.SimpleNamespace(REPEATABLE_READ="repeatable-read")
    )

    def walk_records(records):
        records = list(records)  # consumed while the cursor's transaction is open
        return [], records[-1], len(records)

    store = types.SimpleNamespace(walk_records=walk_records)
    modules = {"psycopg": psycopg, "factory_events.store": store}
    monkeypatch.setattr(chain_db, "import_module", modules.__getitem__)

    errors, last, count, matches = chain_db._walk(_Params("factory_events_read"), "h", 1)

    [(args, kwargs)] = connects
    assert args == ()  # keyword parameters only: never a URL holding the password
    assert kwargs == {
        "host": "127.0.0.1",
        "port": "1",
        "dbname": "factory_events",
        "user": "factory_events_read",
        "password": READ_PASSWORD,
        "connect_timeout": chain_db.CONNECT_TIMEOUT_SECONDS,
        "application_name": "intent_packages",
    }
    assert conn.executed == [(chain_db._WALK, True, "repeatable-read", True)]
    assert (errors, count, matches) == ([], 1, ["ev-1"])
    assert last is not None and last["seq"] == 1
