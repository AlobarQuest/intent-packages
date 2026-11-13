"""The chain checker and emitter under the database chain's DSNs (ADR-0055 amendment 24), with
`subprocess.run` faked. The real database paths are in test_chain_db_integration.py."""

import contextlib
import json
import os
import subprocess
import types
from pathlib import Path

import pytest

from intent_packages import chain_db
from intent_packages.emitter import EmitError, FactoryEventsEmitter
from intent_packages.operations import ChainUnavailable, default_chain_checker

READ_DSN = "postgresql://factory_events_read:READ-PW-placeholder@127.0.0.1:1/factory_events"
APPEND_DSN = "postgresql://factory_events_append:APPEND-PW-placeholder@127.0.0.1:1/factory_events"


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
    monkeypatch.setenv("FACTORY_EVENTS_READ_DSN", READ_DSN)


def _fake_reader(monkeypatch, returncode: int) -> list[dict]:
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, returncode)

    monkeypatch.setattr("intent_packages.operations.subprocess.run", fake_run)
    return calls


def test_read_dsn_runs_the_one_snapshot_reader_with_the_dsn_in_env_only(monkeypatch, read_mode):
    calls = _fake_reader(monkeypatch, chain_db.MATCH)

    assert default_chain_checker("deadbeef", 1) is True

    [call] = calls  # one read: never `factory_events verify` followed by a file scan
    assert call["argv"][1:] == ["-m", "intent_packages.chain_db", "deadbeef", "1"]
    assert READ_DSN not in " ".join(call["argv"])
    assert call["env"]["FACTORY_EVENTS_READ_DSN"] == READ_DSN
    pythonpath = call["env"]["PYTHONPATH"].split(os.pathsep)
    assert pythonpath[1] == str(Path(chain_db.__file__).resolve().parents[1])


def test_read_dsn_no_match_returns_false_even_with_a_matching_file(monkeypatch, read_mode):
    _fake_reader(monkeypatch, chain_db.NO_MATCH)

    assert default_chain_checker("deadbeef", 1) is False


@pytest.mark.parametrize("returncode", [chain_db.UNAVAILABLE, 1, 3, -9])
def test_read_dsn_any_other_exit_raises_without_the_dsn(monkeypatch, read_mode, returncode):
    _fake_reader(monkeypatch, returncode)

    with pytest.raises(ChainUnavailable) as info:
        default_chain_checker("deadbeef", 1)
    assert "PW-placeholder" not in str(info.value)


@pytest.mark.parametrize(
    "error", [subprocess.TimeoutExpired(cmd="reader", timeout=30), OSError("no python")]
)
def test_read_dsn_reader_failing_to_run_raises(monkeypatch, read_mode, error):
    def fake_run(argv, **kwargs):
        raise error

    monkeypatch.setattr("intent_packages.operations.subprocess.run", fake_run)

    with pytest.raises(ChainUnavailable):
        default_chain_checker("deadbeef", 1)


def test_append_dsn_without_read_dsn_raises_and_reads_nothing(monkeypatch, read_mode):
    monkeypatch.delenv("FACTORY_EVENTS_READ_DSN")
    monkeypatch.setenv("FACTORY_EVENTS_APPEND_DSN", APPEND_DSN)
    calls = _fake_reader(monkeypatch, 0)

    with pytest.raises(ChainUnavailable, match="refusing to read the file chain") as info:
        default_chain_checker("deadbeef", 1)
    assert "PW-placeholder" not in str(info.value)
    assert calls == []


def test_neither_dsn_keeps_the_file_path(tmp_path, monkeypatch, fake_registry):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path / "factory-home"))
    _matching_events_file(tmp_path / "factory-home")
    calls = _fake_reader(monkeypatch, 0)

    assert default_chain_checker("deadbeef", 1) is True
    [call] = calls
    assert call["argv"][1:] == ["-m", "factory_events", "verify"]


# --- the reader's own failure reporting (no psycopg or factory_events needed) -----------


def test_reader_without_read_dsn_is_unavailable():
    assert chain_db.main(["deadbeef", "1"]) == chain_db.UNAVAILABLE


def test_reader_failure_logs_json_by_type_and_never_the_dsn(monkeypatch, capsys):
    monkeypatch.setenv("FACTORY_EVENTS_READ_DSN", READ_DSN)

    def refuse(dsn, approved_hash, revision):
        raise RuntimeError(f"connection to {dsn} refused")  # a driver's text can hold the DSN

    monkeypatch.setattr(chain_db, "_walk", refuse)

    assert chain_db.main(["deadbeef", "1"]) == chain_db.UNAVAILABLE
    out, err = capsys.readouterr()
    record = json.loads(out)
    assert record["outcome"] == "failure" and record["error_type"] == "RuntimeError"
    assert "PW-placeholder" not in out + err


def test_reader_maps_walk_results_to_exit_codes(monkeypatch, capsys):
    monkeypatch.setenv("FACTORY_EVENTS_READ_DSN", READ_DSN)
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


# --- the emitter under the append DSN ----------------------------------------------------


def test_emitter_passes_the_append_dsn_through_in_env_only(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))
    monkeypatch.setenv("FACTORY_EVENTS_APPEND_DSN", APPEND_DSN)
    captured = {}

    def fake_run(argv, capture_output, text, env, timeout):
        captured.update(argv=argv, env=env)
        return subprocess.CompletedProcess(argv, 0, stdout="ev-9\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert FactoryEventsEmitter().emit("package.approved", "pkg", {}) == "ev-9"
    assert captured["env"]["FACTORY_EVENTS_APPEND_DSN"] == APPEND_DSN
    assert APPEND_DSN not in " ".join(captured["argv"])


def test_emitter_failed_append_raises_emit_error(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))
    monkeypatch.setenv("FACTORY_EVENTS_APPEND_DSN", APPEND_DSN)

    def fake_run(argv, capture_output, text, env, timeout):
        # FE-1's emit reports a failed append by the error's type only.
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="emit failed: append failed (OperationalError)\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(EmitError, match="OperationalError"):
        FactoryEventsEmitter().emit("package.approved", "pkg", {})


@pytest.mark.parametrize(
    ("dsn", "password"),
    [
        (APPEND_DSN, "APPEND-PW-placeholder"),
        ("postgresql://u:p%40ss-placeholder@127.0.0.1:1/db", "p@ss-placeholder"),
        ("host=127.0.0.1 user=u password='kv pw-placeholder' dbname=db", "kv pw-placeholder"),
    ],
)
def test_emitter_error_never_repeats_a_chain_dsn_or_its_password(
    monkeypatch, tmp_path, dsn, password
):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))
    monkeypatch.setenv("FACTORY_EVENTS_APPEND_DSN", dsn)

    def fake_run(argv, capture_output, text, env, timeout):
        leak = f"connection to {dsn} failed\nauthentication failed for password {password}\n"
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr=leak)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(EmitError) as info:
        FactoryEventsEmitter().emit("package.approved", "pkg", {})
    message = str(info.value)
    assert dsn not in message and password not in message
    assert "<FACTORY_EVENTS_APPEND_DSN redacted>" in message


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
    connects: list[str] = []

    def connect(dsn, **kwargs):
        connects.append(dsn)
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

    errors, last, count, matches = chain_db._walk(READ_DSN, "h", 1)

    assert connects == [READ_DSN]
    assert conn.executed == [(chain_db._WALK, True, "repeatable-read", True)]
    assert (errors, count, matches) == ([], 1, ["ev-1"])
    assert last is not None and last["seq"] == 1
