import subprocess

import pytest

from intent_packages.emitter import (
    EmitError,
    FactoryEventsEmitter,
    NullEmitter,
    _parse_event_id,
)


def test_null_emitter_returns_none():
    assert NullEmitter().emit("package.approved", "pkg", {}) is None


def test_parse_event_id_from_json_stdout():
    assert _parse_event_id('{"event_id": "abc123", "seq": 1}') == "abc123"


def test_parse_event_id_from_bare_token():
    assert _parse_event_id("evt-9f8e7d6c\n") == "evt-9f8e7d6c"


def test_parse_event_id_from_empty_stdout():
    assert _parse_event_id("") is None
    assert _parse_event_id("   \n  ") is None


def test_factory_events_emitter_success(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))
    monkeypatch.delenv("FACTORY_AGENT_ID", raising=False)

    captured = {}

    def fake_run(argv, capture_output, text, env):
        captured["argv"] = argv
        captured["env"] = env
        return subprocess.CompletedProcess(argv, 0, stdout='{"event_id":"ev-1"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    emitter = FactoryEventsEmitter()
    event_id = emitter.emit("package.approved", "pkg-123", {"k": "v"})

    assert event_id == "ev-1"
    argv = captured["argv"]
    assert "-m" in argv
    assert "factory_events" in argv
    assert "emit" in argv
    assert "--actor" in argv
    assert "claude-code-interactive" in argv
    assert "package.approved" in argv
    assert "--ref" in argv
    assert "pkg-123" in argv
    assert "--evidence-json" in argv
    assert captured["env"]["PYTHONPATH"].startswith(str(tmp_path / "src"))


def test_factory_events_emitter_uses_factory_agent_id(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))
    monkeypatch.setenv("FACTORY_AGENT_ID", "custom-agent")

    captured = {}

    def fake_run(argv, capture_output, text, env):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout='{"event_id":"ev-2"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    FactoryEventsEmitter().emit("package.approved", "pkg-123", {})

    assert "custom-agent" in captured["argv"]
    assert "claude-code-interactive" not in captured["argv"]


def test_factory_events_emitter_raises_on_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))

    def fake_run(argv, capture_output, text, env):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(EmitError, match="boom"):
        FactoryEventsEmitter().emit("package.approved", "pkg-123", {})


def test_factory_events_emitter_no_security_standards_raises(monkeypatch):
    monkeypatch.delenv("SECURITY_STANDARDS_DIR", raising=False)
    monkeypatch.setattr("intent_packages.emitter.registry.registry_dir", lambda: None)

    with pytest.raises(EmitError, match="cannot locate security-standards"):
        FactoryEventsEmitter().emit("package.approved", "pkg-123", {})
