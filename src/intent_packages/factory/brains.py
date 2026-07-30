"""Authoring-time governed-knowledge resolution for `factory decompose` (WS-P2.12).

Reads the brains' REST lookup API — the surface their own docstring describes as
"lets off-machine agents query Code Brain accurately without an MCP client" — and
projects a change class's declared roads and rules into one canonical document.

The document is attached to every proposed unit, so what a worker will be told is
inside the artifact a human approves, and the orchestrator never has to call out
to assemble it. That is the whole point of resolving here rather than at claim
time: the orchestrator stays push-only, and nothing reaches a worker that no
human saw.

Containment has two layers. The brains' repositories serve approved-only records,
so nothing proposed, deprecated, superseded, or retired can ride. And the field
picks below are an allowlist, so a column added upstream reaches a worker only
when someone names it here.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import tomllib
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from intent_packages.factory.credentials import CredentialError, Runner, _default_runner
from intent_packages.profiles import EnrichmentSpec

MANIFEST = Path(__file__).resolve().parents[3] / ".bws-secrets.toml"
SCHEMA_VERSION = 1
TIMEOUT_SECONDS = 15.0
USER_AGENT = "intent-packages-enrichment/1 (+AlobarQuest/intent-packages)"

# Ranked low to high, mirroring the brains' own AUTHORITY_RANK. An unrecognised
# floor name matches nothing, so a typo fails closed to an empty projection
# rather than quietly carrying everything.
AUTHORITY_RANK: Mapping[str, int] = {"informational": 0, "recommended": 1, "required": 2}

# Field allowlists. `check`, `good_example`, `bad_example`, `applicability` and
# `conflict` exist upstream and are deliberately NOT carried: they are tooling
# metadata, not guidance a worker acts on, and every field costs prompt budget.
ROAD_FIELDS: tuple[str, ...] = (
    "slug",
    "name",
    "category",
    "status",
    "summary",
    "decided_approach",
    "home",
    "owner_standard",
    "adr_ref",
)
RULE_FIELDS: tuple[str, ...] = ("id", "category", "severity", "authority", "rule", "reason")
EXEMPLAR_FIELDS: tuple[str, ...] = ("id", "label", "location", "note")


class BrainKey(enum.StrEnum):
    CODE = "code"
    INFRA = "infra"

    @property
    def base_url(self) -> str:
        return _BASE_URLS[self]

    @property
    def env_var(self) -> str:
        return f"{self.name}_BRAIN_KEY"


_BASE_URLS: Mapping[BrainKey, str] = {
    BrainKey.CODE: "https://code-brain.devonwatkins.com",
    BrainKey.INFRA: "https://infra-brain.devonwatkins.com",
}


class SupportsBrainReads(Protocol):
    def get_road(self, slug: str) -> dict[str, Any]: ...

    def list_infra_rules(self) -> list[dict[str, Any]]: ...


def brain_secret_uuid(brain: BrainKey) -> str:
    """The BWS UUID for `brain`'s access key, selected by the manifest's `brain` field.

    By UUID, never by name: BWS secret names are mutable labels, so a by-name
    lookup breaks silently on a rename.
    """
    try:
        manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    except OSError as error:
        raise CredentialError(f"cannot read {MANIFEST}") from error
    for entry in manifest.get("secret", []):
        if entry.get("brain") == brain.value:
            uuid = entry.get("uuid")
            if isinstance(uuid, str) and uuid:
                return uuid
    raise CredentialError(f"{MANIFEST} has no [[secret]] entry with brain = {brain.value!r}")


def resolve_brain_key(brain: BrainKey, *, runner: Runner | None = None) -> str:
    """Return `brain`'s access key, from the environment or BWS. Never logged.

    Env first so CI and tests never touch BWS, exactly as `credentials.resolve_token`
    does for the orchestrator bearers.
    """
    from_env = os.environ.get(brain.env_var, "")
    if from_env:
        return from_env
    uuid = brain_secret_uuid(brain)
    if not os.environ.get("BWS_ACCESS_TOKEN"):
        raise CredentialError(
            f"no credential for the {brain.value} brain: set {brain.env_var}, or set "
            f"BWS_ACCESS_TOKEN so it can be fetched from BWS secret {uuid}"
        )
    result = (runner or _default_runner)(["bws", "secret", "get", uuid, "--output", "env"])
    if result.returncode != 0:
        raise CredentialError(
            f"bws secret get failed for the {brain.value} brain (secret {uuid}), "
            f"exit {result.returncode}"
        )
    return _parse_key(result.stdout, brain, uuid)


def _parse_key(stdout: str, brain: BrainKey, uuid: str) -> str:
    """Extract the value from `bws secret get --output env`. Never echoes stdout."""
    saw_separator = False
    for line in stdout.splitlines():
        _, separator, value = line.partition("=")
        if not separator:
            continue
        saw_separator = True
        value = value.strip().strip('"')
        if value:
            return value
    if not saw_separator and (bare := stdout.strip()):
        return bare
    raise CredentialError(
        f"bws secret get returned no value for the {brain.value} brain (secret {uuid})"
    )


class BrainClient:
    """Read-only HTTP access to the brains' lookup API."""

    def __init__(
        self,
        keys: Mapping[BrainKey, str],
        *,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._keys = keys
        self._timeout = timeout

    def _get(self, brain: BrainKey, path: str) -> Any:
        response = httpx.get(
            f"{brain.base_url}{path}",
            headers={"x-brain-key": self._keys[brain], "User-Agent": USER_AGENT},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_road(self, slug: str) -> dict[str, Any]:
        return self._get(BrainKey.CODE, f"/api/road/{slug}")

    def list_infra_rules(self) -> list[dict[str, Any]]:
        payload = self._get(BrainKey.INFRA, "/api/rules")
        rules = payload.get("rules", [])
        return list(rules) if isinstance(rules, list) else []


def _pick(record: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    return {field: record.get(field) for field in fields}


def _meets_authority(record: Mapping[str, Any], floor: str) -> bool:
    minimum = AUTHORITY_RANK.get(floor)
    if minimum is None:
        return False
    rank = AUTHORITY_RANK.get(str(record.get("authority", "")))
    return rank is not None and rank >= minimum


def content_fingerprint(document: Mapping[str, Any]) -> str:
    """sha256 over the document's CONTENT — provenance deliberately excluded.

    `resolved_at` and `sources` sit outside the digest so that "same brain state
    yields the same fingerprint" is a real, testable property rather than one a
    clock defeats. Same reasoning as the authority envelope's `normalized()`:
    the fingerprint attests content, not circumstance.
    """
    content = {
        "schema_version": document["schema_version"],
        "profile": document["profile"],
        "change_class": document["change_class"],
        "roads": document["roads"],
        "rules": document["rules"],
        "exemplars": document["exemplars"],
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def resolve_enrichment(
    spec: EnrichmentSpec,
    *,
    profile: str,
    change_class: str,
    client: SupportsBrainReads,
    now: datetime,
) -> dict[str, Any]:
    """Project `spec` into the canonical enrichment document.

    Records are sorted before fingerprinting so the digest depends on content
    and not on the order the brains happened to return rows in.
    """
    roads: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    exemplars: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []

    for slug in spec.code_road_slugs:
        payload = client.get_road(slug)
        sources.append({"brain": "code", "endpoint": f"/api/road/{slug}", "query": slug})
        roads.append({"brain": "code", **_pick(payload["road"], ROAD_FIELDS)})
        rules.extend(
            {"brain": "code", "road_slug": slug, **_pick(rule, RULE_FIELDS)}
            for rule in payload.get("rules", [])
        )
        exemplars.extend(
            {"brain": "code", "road_slug": slug, **_pick(exemplar, EXEMPLAR_FIELDS)}
            for exemplar in payload.get("exemplars", [])
        )

    sources.append(
        {
            "brain": "infra",
            "endpoint": "/api/rules",
            "query": f"authority>={spec.infra_min_authority}",
        }
    )
    rules.extend(
        {"brain": "infra", "road_slug": None, **_pick(rule, RULE_FIELDS)}
        for rule in client.list_infra_rules()
        if _meets_authority(rule, spec.infra_min_authority)
    )

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "profile": profile,
        "change_class": change_class,
        "roads": sorted(roads, key=lambda road: (road["brain"], str(road["slug"]))),
        "rules": sorted(rules, key=lambda rule: (rule["brain"], int(rule["id"] or 0))),
        "exemplars": sorted(exemplars, key=lambda item: (item["brain"], int(item["id"] or 0))),
        "resolved_at": now.isoformat(),
        "sources": sources,
    }
    document["content_fingerprint"] = content_fingerprint(document)
    return document
