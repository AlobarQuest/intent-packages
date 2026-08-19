import dataclasses
import json
import subprocess

import httpx
import pytest

from intent_packages.factory import decompose
from intent_packages.factory.api import OrchestratorApi
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


class _FakeBrain:
    """Offline stand-in for the brains' lookup API.

    decompose resolves enrichment before it builds the proposal, so without an
    injected client every one of these tests would reach for a BWS credential.
    """

    def get_road(self, slug):
        return {"road": {"slug": slug, "status": "paved"}, "rules": [], "exemplars": []}

    def list_infra_rules(self):
        return []


def _conformance_client():
    def runner(argv):
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(_CONFORMANCE), stderr="")

    return OrchestratorClient(runner=runner)


def _api_returning_intake(intake=None):
    """A REAL `OrchestratorApi` over a mock transport -- not a duck-typed fake.

    Used for the submit=False tests, which only ever call `get_intake`; any
    other request is a test bug, not a thing to shrug off with a lenient
    handler.
    """
    body = _INTAKE if intake is None else intake

    def handler(request):
        assert request.method == "GET", f"unexpected method: {request.method}"
        return httpx.Response(200, json=body)

    return OrchestratorApi(
        "https://sds.example",
        transport=httpx.MockTransport(handler),
        token_resolver=lambda role: "t",
    )


def test_build_proposal_maps_uuid_and_covers_all_acs(tmp_path):
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
        tmp_path,
    )
    assert proposal["expected_version"] == 0
    assert proposal["ac_mappings"] == [{"ac_id": "uuid-2", "unit_key": "brain-ac002"}]
    assert sorted(r["ac_id"] for r in proposal["retained_acs"]) == ["uuid-1", "uuid-3"]
    unit = proposal["proposed_units"][0]
    assert unit["required_capability"] == "repo.edit"
    assert "work_unit_id" not in unit["authority"]["constraints"]


def test_build_proposal_rationale_applies_to_retained_only(tmp_path):
    sites = [PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    rationale = "retained: not this run"
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
        rationale,
        tmp_path,
    )
    assert proposal["rationale"] == (
        "Dependency update: fastapi 0.139.0 -> 0.139.2 in AlobarQuest/brain."
    )
    assert proposal["rationale"] != rationale
    assert proposal["retained_acs"]
    assert all(r["rationale"] == rationale for r in proposal["retained_acs"])


def test_build_proposal_unknown_ac_raises(tmp_path):
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
            tmp_path,
        )


def _git_repo(tmp_path, content="fastapi==0.139.0\n"):
    """A local checkout tracking a file:// origin — decompose now verifies currency
    against origin/main before dry-running, so a bare origin-less repo fails closed."""
    origin = tmp_path / "brain-origin"
    origin.mkdir()
    (origin / "requirements.txt").write_text(content, encoding="utf-8")
    for argv in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(["git", *argv], cwd=origin, check=True)
    repo = tmp_path / "brain"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(repo)], check=True, capture_output=True
    )
    return repo


def _portable_pip_mutation(repo, package, old, new, sites):
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
    original = dep_update.TOOLING_PROFILES["pip"]
    portable = dataclasses.replace(original, mutation_commands=_portable_pip_mutation)
    monkeypatch.setitem(dep_update.TOOLING_PROFILES, "pip", portable)


def test_run_end_to_end_no_submit(tmp_path, capsys, portable_pip):
    repo = _git_repo(tmp_path)
    out_file = tmp_path / "proposal.json"

    rc = decompose.run(
        brain_client=_FakeBrain(),
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
        client=_conformance_client(),
        api=_api_returning_intake(),
    )
    assert rc == 0
    assert out_file.exists()
    body = json.loads(out_file.read_text())
    assert body["ac_mappings"][0]["ac_id"] == "uuid-2"


def test_run_end_to_end_submit_posts_the_proposal_dict_directly(tmp_path, capsys, portable_pip):
    """The HTTP path posts the exact proposal dict to the exact route; no

    tempfile is involved. Pins method + path for BOTH calls (a typo'd path in
    api.py would otherwise pass every test, since a duck-typed fake only
    asserts what it is told to expect) and ties the posted body to the
    `--out` bytes byte-for-byte, rather than checking a single key.
    """
    repo = _git_repo(tmp_path)
    out_file = tmp_path / "proposal.json"
    calls = []
    posted = {}

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=_INTAKE)
        posted["body"] = json.loads(request.content)
        return httpx.Response(200, json={"proposal_id": "p-42"})

    api = OrchestratorApi(
        "https://sds.example",
        transport=httpx.MockTransport(handler),
        token_resolver=lambda role: "t",
    )

    rc = decompose.run(
        brain_client=_FakeBrain(),
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
        submit=True,
        client=_conformance_client(),
        api=api,
    )
    assert rc == 0
    assert calls == [
        ("GET", "/api/v1/package-intakes/rev-1"),
        ("POST", "/api/v1/package-intakes/rev-1/decomposition-proposals"),
    ]
    written = json.loads(out_file.read_text())
    assert posted["body"] == written
    assert posted["body"]["rationale"].endswith(" routing: sonnet-5 per routing-policy v2.")
    err = capsys.readouterr().err
    assert "submitted:" in err
    assert "p-42" in err


def test_routing_note_lands_in_rationale(tmp_path, capsys, portable_pip):
    repo = _git_repo(tmp_path)
    out_file = tmp_path / "proposal.json"

    rc = decompose.run(
        brain_client=_FakeBrain(),
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
        client=_conformance_client(),
        api=_api_returning_intake(),
    )
    assert rc == 0
    proposal = json.loads(out_file.read_text())
    assert proposal["rationale"].endswith(" routing: sonnet-5 per routing-policy v2.")


def test_missing_routing_row_fails_closed(tmp_path, capsys, portable_pip):
    repo = _git_repo(tmp_path)

    policy = tmp_path / "p.toml"
    policy.write_text(
        'version = 1\n[models]\nsonnet-5 = "claude-sonnet-5"\n'
        "[no_llm]\nitems = []\n"
        '[[surface]]\nid = "runner-implementation"\nmodels = ["sonnet-5"]\n'
        'where = "w"\nrationale = "r"\ndecided = "2026-07-29"\n',
        encoding="utf-8",
    )

    rc = decompose.run(
        brain_client=_FakeBrain(),
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
        client=_conformance_client(),
        api=_api_returning_intake(),
        policy_path=policy,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "decompose failed:" in err
    assert "unknown change-class" in err


def test_run_fails_closed_on_no_diff(tmp_path, capsys, portable_pip):
    repo = _git_repo(tmp_path, content="fastapi==0.139.2\n")  # already at target

    rc = decompose.run(
        brain_client=_FakeBrain(),
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
        client=_conformance_client(),
        api=_api_returning_intake(),
    )
    assert rc == 1
    # Pin the failure to the dry-run, not the (newer) checkout-currency guard.
    assert "no diff" in capsys.readouterr().err


def test_run_fails_closed_on_stale_checkout(tmp_path, capsys, portable_pip):
    """A checkout behind origin/main must never reach the dry-run — the guard
    would otherwise prove the mutator against a tree the runner will not see."""
    repo = _git_repo(tmp_path)
    origin = tmp_path / "brain-origin"
    (origin / "requirements.txt").write_text("fastapi==0.139.1\n", encoding="utf-8")
    for argv in (
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "advance origin"],
    ):
        subprocess.run(["git", *argv], cwd=origin, check=True)

    rc = decompose.run(
        brain_client=_FakeBrain(),
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
        client=_conformance_client(),
        api=_api_returning_intake(),
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "decompose failed:" in err
    assert "pull --ff-only origin main" in err
