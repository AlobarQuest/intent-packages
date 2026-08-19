"""WS-P2.12: every proposed unit carries its change class's enrichment."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from intent_packages.factory.brains import enrichment_for_profile, resolve_enrichment
from intent_packages.factory.decompose import build_proposal
from intent_packages.profiles import PROFILES
from intent_packages.profiles.dependency_update import PinSite

FIXTURES = Path(__file__).parent / "fixtures"
WHEN = datetime(2026, 7, 30, tzinfo=UTC)


class FakeBrainClient:
    def get_road(self, slug: str) -> dict:
        return json.loads((FIXTURES / "code_road_error_logging.json").read_text())

    def list_infra_rules(self) -> list[dict]:
        return json.loads((FIXTURES / "infra_rules.json").read_text())["rules"]


def _intake() -> dict:
    return {
        "acceptance_criteria": [
            {"ac_id": "AC-001", "id": "11111111-1111-1111-1111-111111111111"},
            {"ac_id": "AC-002", "id": "22222222-2222-2222-2222-222222222222"},
        ]
    }


def _document(profile_name: str = "dependency-update") -> dict:
    profile = PROFILES[profile_name]
    assert profile.enrichment is not None
    return resolve_enrichment(
        profile.enrichment,
        profile=profile.name,
        change_class=profile.change_class or profile.name,
        client=FakeBrainClient(),
        now=WHEN,
    )


def _proposal(document: dict | None, repo: Path) -> dict:
    return build_proposal(
        _intake(),
        "AC-001",
        "demo-unit",
        "AlobarQuest/change-manager",
        "uv",
        "ruff",
        "0.15.20",
        "0.15.21",
        {"conformance": "attested"},
        [PinSite(file="pyproject.toml", label="project.dependencies", current_version="0.15.20")],
        "",
        repo,
        context_enrichment=document,
    )


def test_every_proposed_unit_carries_the_document(tmp_path: Path) -> None:
    proposal = _proposal(_document(), tmp_path)

    for unit in proposal["proposed_units"]:
        assert unit["context_enrichment"]["schema_version"] == 1


def test_all_units_of_one_proposal_share_one_resolution(tmp_path: Path) -> None:
    """Resolved once per proposal, never once per unit.

    Per-unit resolution would let two units of the same proposal disagree about
    the standards they were approved under — and the human approving them would
    have no way to see that they had.
    """
    proposal = _proposal(_document(), tmp_path)

    fingerprints = {
        unit["context_enrichment"]["content_fingerprint"] for unit in proposal["proposed_units"]
    }
    assert len(fingerprints) == 1


def test_dependency_update_units_carry_an_empty_but_present_document() -> None:
    """Empty by CONTENT. Absent would mean "never enriched", which is different."""
    document = _document("dependency-update")

    assert document["roads"] == []
    assert len(document["rules"]) == 4  # the four infra authority=required rules
    assert document["content_fingerprint"].startswith("sha256:")


def test_a_proposal_without_enrichment_omits_the_key_entirely(tmp_path: Path) -> None:
    """None is not {} — a unit that predates enrichment must stay distinguishable."""
    proposal = _proposal(None, tmp_path)

    assert "context_enrichment" not in proposal["proposed_units"][0]


def test_enrichment_for_an_unregistered_profile_is_refused() -> None:
    with pytest.raises(KeyError):
        enrichment_for_profile("no-such-profile", client=FakeBrainClient(), now=WHEN)


def test_enrichment_for_profile_resolves_the_registered_spec() -> None:
    document = enrichment_for_profile("software-delivery", client=FakeBrainClient(), now=WHEN)

    assert document is not None
    assert [road["slug"] for road in document["roads"]] == ["error-logging"]
    assert document["profile"] == "software-delivery"


def test_non_software_operational_resolves_the_credential_rules() -> None:
    """WS-P2.13: the profile has no change_class, and still resolves a real document.

    Before it declared a spec this returned None, so every brief for the class carried nothing.
    The content is the point: an infra-authority projection is exactly the governed knowledge a
    credential rotation must honour, which is why the emptiness was worth closing rather than
    recording.
    """
    document = enrichment_for_profile(
        "non-software-operational", client=FakeBrainClient(), now=WHEN
    )

    assert document is not None
    assert document["profile"] == "non-software-operational"
    assert document["change_class"] == "non-software-operational"
    assert document["roads"] == []  # this profile ships no code
    assert len(document["rules"]) == 4
    assert document["content_fingerprint"].startswith("sha256:")


def test_a_brain_outage_fails_the_decomposition_closed(tmp_path, capsys) -> None:
    """No credential, no proposal. A unit whose workers were told nothing, shipped
    as though they had been, is worse than a decomposition that stops and says so.
    """
    from intent_packages.factory import decompose

    rc = decompose.run(
        revision="rev-1",
        ac="AC-001",
        target_repo="AlobarQuest/brain",
        repo_path=str(tmp_path),
        tooling="pip",
        package="fastapi",
        from_version="0.139.0",
        to_version="0.139.2",
        unit_key="",
        rationale="",
        out="",
        submit=False,
        brain_client=None,
    )

    assert rc == 1
    assert "decompose failed" in capsys.readouterr().err
