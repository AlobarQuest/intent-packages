"""DeliveryProfile: the one governed shape for every delivery profile (WS-P2.10).

Profiles layer ABOVE the authority envelope and never modify its shape — the
envelope is a byte-pinned cross-repo contract, and a profile that needs a new
envelope key is out of scope by definition. `default_authority` carries
envelope template PARAMETERS only: defaults, never grants. Every unit still
gets its own fingerprint-bound human authority approval.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from intent_packages.schema import MapSpec

if TYPE_CHECKING:
    from intent_packages.profiles.dependency_update import ToolingProfile


@dataclass(frozen=True)
class AuthorityDefaults:
    """Envelope template parameters for a factory-executable profile.

    budgets.max_llm_calls gates RE-CLAIM ELIGIBILITY, not spend-in-run —
    GAP-4 declared 4 and recorded 15 in one attempt, completing normally.
    The per-attempt cap is factory-runner's max_turns literal, a separate
    number this repo does not control.
    """

    budgets: Mapping[str, int]
    capabilities: Mapping[str, str]
    command_ordering: str


@dataclass(frozen=True)
class EnrichmentSpec:
    """What governed knowledge a change class projects onto its units (WS-P2.12).

    The single definition site. The orchestrator holds no copy of this
    vocabulary — it receives a resolved document and validates its shape, never
    its membership — so there is no second list to keep in sync.

    `infra_min_authority` is an AUTHORITY floor, not a severity floor. The two
    disagree: Infra Brain carries 12 BLOCK-severity rules of which only 4 are
    `authority: required`, and Code Brain has none at `required` at all.
    """

    code_road_slugs: tuple[str, ...] = ()
    infra_min_authority: str = "required"


@dataclass(frozen=True)
class DeliveryProfile:
    name: str
    change_class: str | None = None  # non-None => factory-executable => routing row required
    profile_fields_schema: MapSpec | None = None
    tag_to_evidence_type: Mapping[str, str] = field(default_factory=dict)
    forbidden_evidence_types: frozenset[str] = frozenset()
    required_checks: tuple[str, ...] = ()
    default_authority: AuthorityDefaults | None = None
    evidence_expectations: str = ""
    observation_window: str = ""
    validate: Callable[[dict], list[str]] | None = None
    tooling: Mapping[str, ToolingProfile] | None = None
    enrichment: EnrichmentSpec | None = None


def check_forbidden_evidence_types(package: dict, forbidden: frozenset[str]) -> list[str]:
    """Shared check: reject acceptance items whose evidence_type a profile forbids.

    Scoped per profile so the 14 pre-WS-P2.10 packages (whose profiles forbid
    nothing) stay valid — their YAML cannot be edited without invalidating
    lineage approvals.
    """
    if not forbidden:
        return []
    acceptance = package.get("acceptance")
    if not isinstance(acceptance, list):
        return []
    errors: list[str] = []
    for i, item in enumerate(acceptance):
        if not isinstance(item, dict):
            continue
        evidence_type = item.get("evidence_type")
        if evidence_type in forbidden:
            errors.append(
                f"acceptance[{i}].evidence_type: {evidence_type!r} is forbidden by this "
                f"profile (it resolves to judgment_required in the verifier; use "
                f"'automated_check' backed by a named check, until orchestrator "
                f"remediation 2.1/2.2/2.3 ship together)"
            )
    return errors
