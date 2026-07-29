import json
import subprocess

import pytest

from intent_packages.factory.orchestrator_cli import OrchestratorClient, OrchestratorCliError


def _fake(returncode, stdout):
    def runner(argv):
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    return runner


def test_orchestrator_client_no_longer_exposes_api_calls():
    assert not hasattr(OrchestratorClient, "show_package_intake")
    assert not hasattr(OrchestratorClient, "propose_decomposition")


def test_error_key_raises():
    client = OrchestratorClient(runner=_fake(0, json.dumps({"error": {"code": "boom"}})))
    with pytest.raises(OrchestratorCliError, match="boom"):
        client.conformance_claim("/tmp/repo")


def test_nonzero_exit_raises():
    client = OrchestratorClient(runner=_fake(1, ""))
    with pytest.raises(OrchestratorCliError):
        client.conformance_claim("/tmp/repo")


def test_conformance_builds_expected_argv():
    seen = {}

    def runner(argv):
        seen["argv"] = argv
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps({"status": "green"}), stderr=""
        )

    OrchestratorClient(runner=runner).conformance_claim("/tmp/repo")
    assert seen["argv"] == ["orchestrator", "conformance-claim", "/tmp/repo", "--json"]


def test_non_json_stdout_raises():
    client = OrchestratorClient(runner=_fake(0, "not json at all"))
    with pytest.raises(OrchestratorCliError):
        client.conformance_claim("/tmp/repo")


def test_non_dict_json_raises():
    client = OrchestratorClient(runner=_fake(0, json.dumps([1, 2, 3])))
    with pytest.raises(OrchestratorCliError):
        client.conformance_claim("/tmp/repo")
