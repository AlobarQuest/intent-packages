"""The emitter and the chain checker against FE-1's database chain on a disposable Postgres.

Run by scripts/check-integration.sh, never by `make check`. FACTORY_TEST_DSN names a superuser
on a throwaway cluster; each test gets its own new database, set up by FE-1's real roles script
(`factory_events.db_setup`, run under the events interpreter), and appends through FE-1's real
`factory_events emit`. IT_SECURITY_STANDARDS_DIR names a security-standards checkout with FE-1.
"""

import json
import os
import secrets
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from intent_packages.emitter import (
    EmitError,
    FactoryEventsEmitter,
    _events_env,
    _events_python,
    _security_standards_dir,
)
from intent_packages.operations import ChainUnavailable, default_chain_checker

pytestmark = pytest.mark.integration

ROLE_PASSWORD = secrets.token_hex(16)  # throwaway, for this run's disposable cluster only


def _psycopg() -> Any:
    return import_module("psycopg")


class Dsn(str):
    """A DSN whose repr is redacted, so a failing assert can't print its password."""

    def __repr__(self) -> str:
        return "'<dsn redacted>'"


def _conninfo(base: str, **overrides: str) -> Dsn:
    conninfo = import_module("psycopg.conninfo")
    params = conninfo.conninfo_to_dict(base)
    params.update(overrides)
    return Dsn(conninfo.make_conninfo(**params))


@dataclass(frozen=True)
class ChainDb:
    owner: Dsn
    append: Dsn
    read: Dsn


def _setup_schema(owner: Dsn) -> None:
    """FE-1's roles script, as the owner, under the events interpreter (test fixture only)."""
    sec = _security_standards_dir()
    env = _events_env(sec)
    env["FACTORY_EVENTS_OWNER_DSN"] = owner
    result = subprocess.run(
        [_events_python(sec), "-m", "factory_events.db_setup"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, "factory_events.db_setup failed"


@pytest.fixture(autouse=True)
def _security_standards_with_fe1(tmp_path, monkeypatch):
    # conftest points SECURITY_STANDARDS_DIR at an empty placeholder for every test; these
    # tests need the real checkout, which the runner script passes under its own name.
    sec = os.environ.get("IT_SECURITY_STANDARDS_DIR")
    assert sec and Path(sec, "src/factory_events/db.py").is_file(), (
        "IT_SECURITY_STANDARDS_DIR must name a checkout with FE-1 (scripts/check-integration.sh)"
    )
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", sec)
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path / "factory"))
    monkeypatch.delenv("FACTORY_AGENT_ID", raising=False)


@pytest.fixture()
def chain_db() -> Iterator[ChainDb]:
    base = os.environ.get("FACTORY_TEST_DSN")
    assert base, "FACTORY_TEST_DSN is required (scripts/check-integration.sh sets one)"
    psycopg = _psycopg()
    sql = import_module("psycopg.sql")
    name = f"ip_chain_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    owner = _conninfo(base, dbname=name)
    try:
        _setup_schema(owner)
        with psycopg.connect(owner, autocommit=True) as conn:
            for role in ("factory_events_append", "factory_events_read"):
                conn.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(ROLE_PASSWORD)
                    )
                )
        yield ChainDb(
            owner=owner,
            append=_conninfo(owner, user="factory_events_append", password=ROLE_PASSWORD),
            read=_conninfo(owner, user="factory_events_read", password=ROLE_PASSWORD),
        )
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


def _emit(monkeypatch, append_dsn: str, action: str, evidence: dict) -> str | None:
    monkeypatch.setenv("FACTORY_EVENTS_APPEND_DSN", append_dsn)
    try:
        return FactoryEventsEmitter().emit(action, "intent-packages-it", evidence)
    finally:
        monkeypatch.delenv("FACTORY_EVENTS_APPEND_DSN")


def _approve(monkeypatch, db: ChainDb, approved_hash: str, revision: int) -> str | None:
    _emit(monkeypatch, db.append, "package.transitioned", {"to": "ready_for_review"})
    return _emit(
        monkeypatch,
        db.append,
        "package.approved",
        {"approved_hash": approved_hash, "revision": revision, "approver": "devon"},
    )


def _event_ids(dsn: str) -> list[str]:
    with _psycopg().connect(dsn) as conn:
        return [row[0] for row in conn.execute("SELECT event_id FROM factory_events ORDER BY seq")]


def _check_under_read_dsn(monkeypatch, db: ChainDb, approved_hash: str, revision: int) -> bool:
    monkeypatch.setenv("FACTORY_EVENTS_READ_DSN", db.read)
    return default_chain_checker(approved_hash, revision)


def test_emitter_appends_through_the_append_dsn_and_returns_the_id(monkeypatch, chain_db):
    event_id = _approve(monkeypatch, chain_db, "h1", 1)

    assert event_id is not None
    assert _event_ids(chain_db.read)[-1] == event_id  # _parse_event_id read emit's own id
    assert not (Path(os.environ["FACTORY_EVENTS_HOME"]) / "events.jsonl").exists()


def test_checker_matches_the_approval_in_the_database(monkeypatch, chain_db, capfd):
    event_id = _approve(monkeypatch, chain_db, "h1", 1)

    assert _check_under_read_dsn(monkeypatch, chain_db, "h1", 1) is True
    out = capfd.readouterr().out
    record = json.loads(out.strip().splitlines()[-1])
    assert record["outcome"] == "match" and record["event_id"] == event_id
    assert ROLE_PASSWORD not in out


def test_checker_no_match_returns_false(monkeypatch, chain_db):
    _approve(monkeypatch, chain_db, "h1", 1)

    assert _check_under_read_dsn(monkeypatch, chain_db, "h1", 2) is False
    assert _check_under_read_dsn(monkeypatch, chain_db, "h2", 1) is False


def test_checker_on_an_empty_chain_returns_false(monkeypatch, chain_db):
    assert _check_under_read_dsn(monkeypatch, chain_db, "h1", 1) is False


def test_checker_broken_chain_raises_even_with_the_match_present(monkeypatch, chain_db):
    _approve(monkeypatch, chain_db, "h1", 1)
    with _psycopg().connect(chain_db.owner) as conn:  # only the owner can lift the trigger
        conn.execute("ALTER TABLE factory_events DISABLE TRIGGER factory_events_no_update_delete")
        conn.execute(
            "UPDATE factory_events SET event = replace(event, 'ready_for_review', 'x') "
            "WHERE seq = 1"
        )

    with pytest.raises(ChainUnavailable):
        _check_under_read_dsn(monkeypatch, chain_db, "h1", 1)


def test_checker_unreachable_database_raises_without_the_dsn(monkeypatch, chain_db, capfd):
    closed_port = _conninfo(chain_db.read, host="127.0.0.1", port="1")
    monkeypatch.setenv("FACTORY_EVENTS_READ_DSN", closed_port)

    with pytest.raises(ChainUnavailable) as info:
        default_chain_checker("h1", 1)
    captured = capfd.readouterr()
    assert ROLE_PASSWORD not in str(info.value) + captured.out + captured.err


def test_checker_refused_role_raises(monkeypatch, chain_db):
    monkeypatch.setenv("FACTORY_EVENTS_READ_DSN", _conninfo(chain_db.read, password="wrong"))

    with pytest.raises(ChainUnavailable):
        default_chain_checker("h1", 1)


def test_read_dsn_set_never_reads_the_file(monkeypatch, chain_db, tmp_path):
    # The file chain holds the approval (a real FE-1 file append); the database doesn't.
    FactoryEventsEmitter().emit(
        "package.approved", "intent-packages-it", {"approved_hash": "h1", "revision": 1}
    )
    assert (tmp_path / "factory" / "events.jsonl").is_file()
    assert default_chain_checker("h1", 1) is True  # neither DSN set: the file answers

    assert _check_under_read_dsn(monkeypatch, chain_db, "h1", 1) is False


def test_failed_append_raises_emit_error_without_the_dsn(monkeypatch, chain_db):
    # The read role can't INSERT: the append is refused, writes nothing, and raises.
    with pytest.raises(EmitError) as info:
        _emit(monkeypatch, chain_db.read, "package.approved", {"approved_hash": "h1"})
    assert ROLE_PASSWORD not in str(info.value)
    assert _event_ids(chain_db.read) == []
