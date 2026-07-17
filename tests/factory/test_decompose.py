import dataclasses
import json
import subprocess

import pytest

from intent_packages.factory import decompose
from intent_packages.factory.orchestrator_cli import OrchestratorClient
from intent_packages.profiles import dependency_update as dep_update
from intent_packages.profiles.dependency_update import PinSite

_INTAKE = {
    "acceptance_criteria": [
        {"id": "uuid-1", "ac_id": "AC-001"},
        {"id": "uuid-2", "ac_id": "AC-002"},
        {"id": "uuid-3", "ac_id": "AC-003"},
    ]
}
_CONFORMANCE = {"accepted_standards": [], "standards_touched": ["project"], "status": "green"}


def test_build_proposal_maps_uuid_and_covers_all_acs():
    sites = [PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    proposal = decompose.build_proposal(
        _INTAKE,
        "AC-002",
        "brain-ac002",
        "AlobarQuest/brain",
        "pip",
        "fastapi",
        "0.139.0",
        "0.139.2",
        _CONFORMANCE,
        sites,
        "retained: not this run",
    )
    assert proposal["expected_version"] == 0
    assert proposal["ac_mappings"] == [{"ac_id": "uuid-2", "unit_key": "brain-ac002"}]
    assert sorted(r["ac_id"] for r in proposal["retained_acs"]) == ["uuid-1", "uuid-3"]
    unit = proposal["proposed_units"][0]
    assert unit["required_capability"] == "repo.edit"
    assert "work_unit_id" not in unit["authority"]["constraints"]


def test_build_proposal_unknown_ac_raises():
    with pytest.raises(decompose.DecomposeError, match="AC-999"):
        decompose.build_proposal(
            _INTAKE,
            "AC-999",
            "k",
            "AlobarQuest/brain",
            "pip",
            "fastapi",
            "0.139.0",
            "0.139.2",
            _CONFORMANCE,
            [],
            "r",
        )


def _git_repo(tmp_path):
    repo = tmp_path / "brain"
    repo.mkdir()
    (repo / "requirements.txt").write_text("fastapi==0.139.0\n", encoding="utf-8")
    for argv in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(["git", *argv], cwd=repo, check=True)
    return repo


def _portable_pip_mutation(package, old, new, sites):
    # Test-only macOS-portability shim: the pip profile's REAL mutator is GNU
    # `sed -i 's/.../.../'`, which BSD/macOS sed cannot execute (it requires an
    # explicit backup-suffix argument to -i). The production mutator in
    # profiles/dependency_update.py stays GNU-shaped because that's what the
    # Linux hosted runner needs; only these tests swap in a cross-platform
    # `perl -pi -e` substitution so `dry_run_mutation` (which really executes
    # the mutator locally) is exercised honestly on this dev machine.
    return [f"perl -pi -e 's/^{package}=={old}$/{package}=={new}/' {site.file}" for site in sites]


@pytest.fixture
def portable_pip(monkeypatch):
    original = dep_update.PROFILES["pip"]
    portable = dataclasses.replace(original, mutation_commands=_portable_pip_mutation)
    monkeypatch.setitem(dep_update.PROFILES, "pip", portable)


def test_run_end_to_end_no_submit(tmp_path, capsys, portable_pip):
    repo = _git_repo(tmp_path)
    out_file = tmp_path / "proposal.json"

    def runner(argv):
        cmd = argv[1]
        body = _INTAKE if cmd == "show-package-intake" else _CONFORMANCE
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(body), stderr="")

    rc = decompose.run(
        revision="rev-1",
        ac="AC-002",
        target_repo="AlobarQuest/brain",
        repo_path=str(repo),
        tooling="pip",
        package="fastapi",
        from_version="0.139.0",
        to_version="0.139.2",
        unit_key="",
        rationale="",
        out=str(out_file),
        submit=False,
        client=OrchestratorClient(runner=runner),
    )
    assert rc == 0
    assert out_file.exists()
    body = json.loads(out_file.read_text())
    assert body["ac_mappings"][0]["ac_id"] == "uuid-2"


def test_run_fails_closed_on_no_diff(tmp_path, portable_pip):
    repo = tmp_path / "brain"
    repo.mkdir()
    (repo / "requirements.txt").write_text("fastapi==0.139.2\n", encoding="utf-8")  # already new
    for argv in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(["git", *argv], cwd=repo, check=True)

    def runner(argv):
        body = _INTAKE if argv[1] == "show-package-intake" else _CONFORMANCE
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(body), stderr="")

    rc = decompose.run(
        revision="rev-1",
        ac="AC-002",
        target_repo="AlobarQuest/brain",
        repo_path=str(repo),
        tooling="pip",
        package="fastapi",
        from_version="0.139.0",
        to_version="0.139.2",
        unit_key="",
        rationale="",
        out="",
        submit=False,
        client=OrchestratorClient(runner=runner),
    )
    assert rc == 1
