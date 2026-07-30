"""WS-P2.12: authoring-time governed-knowledge resolution.

Fixtures are captured from the live brains, not hand-authored, so a shape change
on their side reds here rather than passing against an imagined API.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from intent_packages.factory.brains import (
    BrainKey,
    brain_secret_uuid,
    content_fingerprint,
    resolve_enrichment,
)
from intent_packages.profiles import EnrichmentSpec

FIXTURES = Path(__file__).parent / "fixtures"
WHEN = datetime(2026, 7, 30, tzinfo=UTC)


def _road_fixture() -> dict:
    return json.loads((FIXTURES / "code_road_error_logging.json").read_text())


def _infra_fixture() -> list[dict]:
    return json.loads((FIXTURES / "infra_rules.json").read_text())["rules"]


class FakeBrainClient:
    def __init__(self) -> None:
        self.road_calls: list[str] = []
        self.infra_calls = 0

    def get_road(self, slug: str) -> dict:
        self.road_calls.append(slug)
        return _road_fixture()

    def list_infra_rules(self) -> list[dict]:
        self.infra_calls += 1
        return _infra_fixture()


def _resolve(spec: EnrichmentSpec, *, when: datetime = WHEN, client=None) -> dict:
    return resolve_enrichment(
        spec,
        profile="software-delivery",
        change_class="software-delivery",
        client=client or FakeBrainClient(),
        now=when,
    )


def test_resolves_the_named_road_and_its_rules() -> None:
    doc = _resolve(EnrichmentSpec(code_road_slugs=("error-logging",)))

    assert doc["schema_version"] == 1
    assert [road["slug"] for road in doc["roads"]] == ["error-logging"]
    assert doc["roads"][0]["decided_approach"]
    assert len([rule for rule in doc["rules"] if rule["brain"] == "code"]) == 9
    assert len(doc["exemplars"]) == 2


def test_infra_rules_are_filtered_by_authority_not_severity() -> None:
    """The REST route has no min_authority filter, so the client applies the floor.

    12 infra rules are BLOCK-severity and only 4 are authority=required. A resolver
    keyed on severity would carry three times the material, most of it unrelated.
    """
    doc = _resolve(EnrichmentSpec(infra_min_authority="required"))

    infra = [rule for rule in doc["rules"] if rule["brain"] == "infra"]
    assert len(infra) == 4
    assert {rule["authority"] for rule in infra} == {"required"}
    assert sum(1 for rule in _infra_fixture() if rule["severity"] == "BLOCK") == 12


def test_an_empty_spec_resolves_to_an_empty_but_present_document() -> None:
    """dependency-update today. Empty by content is not the same as absent."""
    doc = _resolve(EnrichmentSpec(code_road_slugs=(), infra_min_authority="no-such-rank"))

    assert doc["roads"] == []
    assert doc["rules"] == []
    assert doc["schema_version"] == 1
    assert doc["content_fingerprint"].startswith("sha256:")


def test_the_fingerprint_ignores_resolution_time() -> None:
    """Same brain state, same fingerprint. Otherwise a clock defeats the audit."""
    spec = EnrichmentSpec(code_road_slugs=("error-logging",))

    first = _resolve(spec, when=WHEN)
    second = _resolve(spec, when=datetime(2027, 1, 1, tzinfo=UTC))

    assert first["resolved_at"] != second["resolved_at"]
    assert first["content_fingerprint"] == second["content_fingerprint"]


def test_the_document_is_byte_identical_across_runs() -> None:
    spec = EnrichmentSpec(code_road_slugs=("error-logging",))

    first = json.dumps(_resolve(spec), sort_keys=True, separators=(",", ":"))
    second = json.dumps(_resolve(spec), sort_keys=True, separators=(",", ":"))

    assert first == second


def test_the_fingerprint_changes_when_content_changes() -> None:
    """A fingerprint that never moves is attesting nothing."""
    base = _resolve(EnrichmentSpec(code_road_slugs=("error-logging",)))
    mutated = {**base, "rules": base["rules"][:-1]}

    assert content_fingerprint(mutated) != base["content_fingerprint"]


def test_only_approved_records_are_carried() -> None:
    """Containment: the REST API serves approved-only, and the resolver keeps it so."""
    doc = _resolve(EnrichmentSpec(code_road_slugs=("error-logging",)))

    approved_code_ids = {rule["id"] for rule in _road_fixture()["rules"]}
    assert all(rule["status"] == "approved" for rule in _road_fixture()["rules"])
    carried_code_ids = {rule["id"] for rule in doc["rules"] if rule["brain"] == "code"}
    assert carried_code_ids == approved_code_ids


def test_the_document_carries_no_free_text_beyond_the_named_fields() -> None:
    """Containment: only the picked fields ride, so a new brain column cannot.

    The brains are governed, but the projection is still an allowlist — a field
    added upstream reaches a worker only when someone names it here.
    """
    doc = _resolve(EnrichmentSpec(code_road_slugs=("error-logging",)))

    for rule in doc["rules"]:
        assert set(rule) == {
            "brain",
            "road_slug",
            "id",
            "category",
            "severity",
            "authority",
            "rule",
            "reason",
        }
    # good_example / bad_example / check exist upstream and must NOT be carried.
    assert any("good_example" in rule for rule in _road_fixture()["rules"])


def test_the_infra_brain_is_queried_once_not_per_road() -> None:
    client = FakeBrainClient()

    _resolve(EnrichmentSpec(code_road_slugs=("error-logging",)), client=client)

    assert client.infra_calls == 1
    assert client.road_calls == ["error-logging"]


@pytest.mark.parametrize("brain", list(BrainKey))
def test_every_brain_key_has_a_manifest_entry(brain: BrainKey) -> None:
    assert brain_secret_uuid(brain)
