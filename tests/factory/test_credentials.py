import subprocess
from pathlib import Path

import pytest

from intent_packages.factory import brains, credentials
from intent_packages.factory.brains import BrainKey, resolve_brain_key
from intent_packages.factory.credentials import CredentialError, Role, resolve_token, secret_uuid


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
    assert seen["argv"][:5] == ["env", "-u", "FORCE_COLOR", "-u", "CLICOLOR_FORCE"]
    assert seen["argv"][5:9] == [
        "bws",
        "secret",
        "get",
        "221a48d5-3f29-4898-b300-b4820140c880",
    ]
    assert seen["argv"][-2:] == ["--color", "no"]


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


def test_secret_uuid_selects_by_role_not_name(monkeypatch, tmp_path):
    manifest = tmp_path / ".bws-secrets.toml"
    manifest.write_text(
        "[[secret]]\n"
        'uuid = "11111111-1111-1111-1111-111111111111"\n'
        'name = "renamed-in-bws-since"\n'
        'role = "orchestrator-system"\n'
    )
    monkeypatch.setattr(credentials, "MANIFEST", manifest)
    assert secret_uuid(Role.SYSTEM) == "11111111-1111-1111-1111-111111111111"


def test_secret_uuid_missing_role_raises_credential_error(monkeypatch, tmp_path):
    manifest = tmp_path / ".bws-secrets.toml"
    manifest.write_text(
        "[[secret]]\n"
        'uuid = "11111111-1111-1111-1111-111111111111"\n'
        'name = "some-other-secret"\n'
        'role = "orchestrator-verifier"\n'
    )
    monkeypatch.setattr(credentials, "MANIFEST", manifest)
    with pytest.raises(CredentialError) as error:
        secret_uuid(Role.SYSTEM)
    message = str(error.value)
    assert "orchestrator-system" in message
    assert str(manifest) in message


def test_bws_timeout_raises_credential_error(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")

    def runner(argv):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=30, output="partial-stdout-leak")

    with pytest.raises(CredentialError) as error:
        resolve_token(Role.SYSTEM, runner=runner)
    assert "partial-stdout-leak" not in str(error.value)


# A stand-in for `bws` that behaves the way the real one does under a forcing
# variable: it wraps its output in ANSI escapes whenever FORCE_COLOR or
# CLICOLOR_FORCE reaches it, whatever flags it was given. The value it prints
# is a dummy, never a secret.
FAKE_BWS = """#!/bin/sh
value='TOKEN="dummy-value"'
if [ -n "$FORCE_COLOR" ] || [ -n "$CLICOLOR_FORCE" ]; then
  printf '\\033[38;5;2m%s\\033[0m\\n' "$value"
else
  printf '%s\\n' "$value"
fi
"""


@pytest.fixture
def forced_colour_bws(monkeypatch, tmp_path: Path):
    """Put the fake `bws` first on PATH, with both forcing variables set."""
    fake = tmp_path / "bws"
    fake.write_text(FAKE_BWS)
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("FORCE_COLOR", "3")
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")


@pytest.mark.usefixtures("forced_colour_bws")
def test_token_arrives_without_ansi_escapes_under_forced_colour(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    assert resolve_token(Role.SYSTEM) == "dummy-value"


@pytest.mark.usefixtures("forced_colour_bws")
def test_brain_key_arrives_without_ansi_escapes_under_forced_colour(monkeypatch):
    monkeypatch.delenv("CODE_BRAIN_KEY", raising=False)
    assert resolve_brain_key(BrainKey.CODE) == "dummy-value"


def test_brain_key_uses_the_shared_bws_invocation(monkeypatch):
    monkeypatch.delenv("INFRA_BRAIN_KEY", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")
    seen = {}

    def runner(argv):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout='KEY="brain-key"\n', stderr="")

    assert resolve_brain_key(BrainKey.INFRA, runner=runner) == "brain-key"
    assert seen["argv"] == credentials.bws_get_argv(brains.brain_secret_uuid(BrainKey.INFRA))


def test_missing_bws_under_env_prefix_is_reported_as_missing(monkeypatch):
    """`env` reports a missing program as exit 127 instead of raising."""
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")

    def runner(argv):
        return subprocess.CompletedProcess(argv, 127, stdout="", stderr="env: bws: not found")

    with pytest.raises(CredentialError, match="bws CLI not found"):
        resolve_token(Role.SYSTEM, runner=runner)
