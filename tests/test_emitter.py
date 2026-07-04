import json
import subprocess
import sys

import pytest

from intent_packages.emitter import (
    EMIT_TIMEOUT_SECONDS,
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
    evidence = {"k": "v"}

    def fake_run(argv, capture_output, text, env, timeout):
        captured["argv"] = argv
        captured["env"] = env
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(argv, 0, stdout='{"event_id":"ev-1"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    emitter = FactoryEventsEmitter()
    event_id = emitter.emit("package.approved", "pkg-123", evidence)

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
    assert captured["timeout"] == EMIT_TIMEOUT_SECONDS

    # Fallback path: tmp_path has no .venv-events, so argv[0] must be the
    # running interpreter, not a venv-specific python.
    assert argv[0] == sys.executable

    # Regression guard: --result must be immediately followed by "success".
    result_idx = argv.index("--result")
    assert argv[result_idx + 1] == "success"

    # Regression guard: --evidence-json must be immediately followed by the
    # exact json.dumps(...) of the evidence dict passed to emit().
    evidence_idx = argv.index("--evidence-json")
    assert argv[evidence_idx + 1] == json.dumps(evidence)


def test_factory_events_emitter_uses_factory_agent_id(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))
    monkeypatch.setenv("FACTORY_AGENT_ID", "custom-agent")

    captured = {}

    def fake_run(argv, capture_output, text, env, timeout):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout='{"event_id":"ev-2"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    FactoryEventsEmitter().emit("package.approved", "pkg-123", {})

    assert "custom-agent" in captured["argv"]
    assert "claude-code-interactive" not in captured["argv"]


def test_factory_events_emitter_raises_on_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))

    def fake_run(argv, capture_output, text, env, timeout):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(EmitError, match="boom"):
        FactoryEventsEmitter().emit("package.approved", "pkg-123", {})


def test_factory_events_emitter_no_security_standards_raises(monkeypatch):
    monkeypatch.delenv("SECURITY_STANDARDS_DIR", raising=False)
    monkeypatch.setattr("intent_packages.emitter.registry.registry_dir", lambda: None)

    with pytest.raises(EmitError, match="cannot locate security-standards"):
        FactoryEventsEmitter().emit("package.approved", "pkg-123", {})


def test_factory_events_emitter_prefers_venv_python(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))
    monkeypatch.delenv("FACTORY_AGENT_ID", raising=False)

    venv_python = tmp_path / ".venv-events" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()

    captured = {}

    def fake_run(argv, capture_output, text, env, timeout):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout='{"event_id":"ev-3"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    FactoryEventsEmitter().emit("package.approved", "pkg-123", {})

    assert captured["argv"][0] == str(venv_python)
    assert captured["argv"][0] != sys.executable


def test_factory_events_emitter_timeout_raises_emit_error(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(tmp_path))

    def fake_run(argv, capture_output, text, env, timeout):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(EmitError, match="timed out"):
        FactoryEventsEmitter().emit("package.approved", "pkg-123", {})
