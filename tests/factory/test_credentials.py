import subprocess

import pytest

from intent_packages.factory.credentials import CredentialError, Role, resolve_token


def test_env_wins(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_SYSTEM_TOKEN", "env-token")
    assert resolve_token(Role.SYSTEM) == "env-token"


def test_verifier_uses_its_own_env_var(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_VERIFIER_TOKEN", "verifier-token")
    assert resolve_token(Role.VERIFIER) == "verifier-token"


def test_falls_back_to_bws(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")
    seen = {}

    def runner(argv):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="bws-token\n", stderr="")

    assert resolve_token(Role.SYSTEM, runner=runner) == "bws-token"
    assert seen["argv"][:3] == ["bws", "secret", "get"]
    assert seen["argv"][3] == "221a48d5-3f29-4898-b300-b4820140c880"


def test_missing_bws_access_token_names_both_routes(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.delenv("BWS_ACCESS_TOKEN", raising=False)
    with pytest.raises(CredentialError) as error:
        resolve_token(Role.SYSTEM)
    message = str(error.value)
    assert "ORCHESTRATOR_SYSTEM_TOKEN" in message
    assert "221a48d5-3f29-4898-b300-b4820140c880" in message


def test_bws_failure_does_not_leak_stdout(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")

    def runner(argv):
        return subprocess.CompletedProcess(argv, 1, stdout="s3cret-leak", stderr="denied")

    with pytest.raises(CredentialError) as error:
        resolve_token(Role.SYSTEM, runner=runner)
    assert "s3cret-leak" not in str(error.value)


def test_parses_bws_env_output(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_VERIFIER_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")

    def runner(argv):
        return subprocess.CompletedProcess(argv, 0, stdout='TOKEN="abc123"\n', stderr="")

    assert resolve_token(Role.VERIFIER, runner=runner) == "abc123"


def test_quoted_empty_value_raises_rather_than_returning_empty(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")

    def runner(argv):
        return subprocess.CompletedProcess(argv, 0, stdout='TOKEN=""\n', stderr="")

    with pytest.raises(CredentialError) as error:
        resolve_token(Role.SYSTEM, runner=runner)
    assert '""' not in str(error.value)


def test_missing_bws_binary_raises_credential_error(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")

    def runner(argv):
        raise FileNotFoundError("no such file or directory: 'bws'")

    with pytest.raises(CredentialError) as error:
        resolve_token(Role.SYSTEM, runner=runner)
    assert "no such file or directory" not in str(error.value)


def test_bws_timeout_raises_credential_error(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")

    def runner(argv):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=30, output="partial-stdout-leak")

    with pytest.raises(CredentialError) as error:
        resolve_token(Role.SYSTEM, runner=runner)
    assert "partial-stdout-leak" not in str(error.value)
