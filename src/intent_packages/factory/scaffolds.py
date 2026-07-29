"""Registry-driven intent-package scaffolding (WS-P2.9 task 5, remediation 6.3).

`create` builds package.yaml + lineage.yaml from ONE universal skeleton,
parameterised by a registered `DeliveryProfile`: profile.name, typed stubs for
profile.profile_fields_schema's keys, an evidence type drawn from
profile.tag_to_evidence_type minus profile.forbidden_evidence_types (and
always minus automated_test), and authority.budgets from
profile.default_authority. That is what makes "every registered profile
scaffolds and validates" cheap and meaningful: there is no per-profile
template to keep in sync with the schema.

`create` always validates what it just wrote via `validate_package` — the
same code path `intent_packages validate` uses — and refuses to leave an
invalid package on disk while claiming success.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from intent_packages import canonical
from intent_packages.lineage import write as write_lineage
from intent_packages.profiles import PROFILES, DeliveryProfile
from intent_packages.schema import ListSpec, MapSpec, OpenMapSpec, OptionalKey, ScalarSpec
from intent_packages.validate import validate_package

_PROSE_PLACEHOLDER = "<edit: describe this field>"

_AC_ID_COMMENT = (
    "# ac_id means two different things and nothing checks the difference:\n"
    "#   - a decomposition proposal's ac_mappings[].ac_id / retained_acs[].ac_id want\n"
    "#     the criterion's database UUID\n"
    "#   - evidence and adjudication want the human string below, e.g. AC-001\n"
    "# Getting it wrong is a bare package_acceptance_criterion_not_found with no hint.\n"
)

_DEPENDENCY_UPDATE_ENVELOPE_COMMENT = (
    "# allowed_commands is an ORDERED list the worker re-executes at finalize, not a\n"
    "# permission set: put mutators first and the verifier last, or the recorded\n"
    "# evidence attests to a tree that is not the one pushed. `make check` must never\n"
    "# appear in this repo's envelope. Use `uv venv --clear`, never bare `uv venv`.\n"
)


def _evidence_type(profile: DeliveryProfile) -> str:
    """Pick an evidence type this profile permits.

    `automated_test` resolves to `judgment_required` in the verifier for every
    automated AC however good the evidence, and two profiles reject it
    outright, so it is excluded here regardless of what a profile's tag map
    contains.
    """
    forbidden = set(profile.forbidden_evidence_types) | {"automated_test"}
    permitted = [
        v for v in sorted(set(profile.tag_to_evidence_type.values())) if v not in forbidden
    ]
    return permitted[0] if permitted else "test"


def _tag_for_evidence_type(profile: DeliveryProfile, evidence_type: str) -> str:
    """The first tag (in the profile's own declaration order) that maps to
    `evidence_type` — guaranteed to exist because `evidence_type` was itself
    drawn from `profile.tag_to_evidence_type.values()`."""
    for tag, mapped in profile.tag_to_evidence_type.items():
        if mapped == evidence_type:
            return tag
    raise ValueError(f"profile {profile.name!r} has no tag mapping to {evidence_type!r}")


def _acceptance_items(profile: DeliveryProfile) -> list[dict]:
    """Exactly two acceptance items, both using an evidence type this profile
    permits and a producer tag that matches it (per `_evidence_tags.check_evidence_tags`)."""
    evidence_type = _evidence_type(profile)
    tag = _tag_for_evidence_type(profile, evidence_type)
    return [
        {
            "id": "AC-001",
            "condition": f"this {profile.name} package's primary outcome is achieved",
            "evidence_type": evidence_type,
            "evidence": f"{tag} describe the {evidence_type} evidence produced for AC-001",
            "approver": "policy",
        },
        {
            "id": "AC-002",
            "condition": "a reviewer confirms this package was ready before execution began",
            "evidence_type": evidence_type,
            "evidence": f"{tag} describe the {evidence_type} evidence produced for AC-002",
            "approver": "policy",
        },
    ]


def _stub_for(field: ScalarSpec | ListSpec | MapSpec | OpenMapSpec | OptionalKey) -> object:
    """A typed placeholder for one profile_fields_schema field.

    A bare "" would be wrong wherever a profile's own validator additionally
    rejects empty strings/lists (every profile's non-empty-string fields,
    software-delivery's non-empty `required_checks`) or an enum constrains the
    legal values (infrastructure-change's `blast_radius`) — a scaffold must
    validate, so the placeholder is non-empty wherever the type allows it.

    Explicit isinstance chain over the four spec classes actually used inside
    `profile_fields_schema` (ScalarSpec/ListSpec/MapSpec/OptionalKey).
    `OpenMapSpec` is accepted in the type (a `MapSpec.fields` value or an
    `OptionalKey.spec` can statically be one) but deliberately unhandled: no
    registered profile's schema uses it here, and a new spec kind — including
    this one, should it ever appear — must raise TypeError rather than
    default silently, forcing a deliberate decision at this call site.
    """
    if isinstance(field, OptionalKey):
        return _stub_for(field.spec)
    if isinstance(field, ScalarSpec):
        if field.nullable:
            return None
        if field.enum:
            return sorted(field.enum)[0]
        if field.py_type is bool:
            return False
        if field.py_type is int:
            return 0
        return _PROSE_PLACEHOLDER
    if isinstance(field, ListSpec):
        return [_stub_for(field.item)]
    if isinstance(field, MapSpec):
        return {key: _stub_for(value) for key, value in field.fields.items()}
    raise TypeError(f"unknown profile_fields schema spec class: {type(field).__name__}")


def _profile_fields(profile: DeliveryProfile) -> dict | None:
    """Emit one entry per key the profile's schema declares, with a typed stub."""
    spec = profile.profile_fields_schema
    if spec is None:
        return None
    return {key: _stub_for(field) for key, field in spec.fields.items()}


def _budgets(profile: DeliveryProfile) -> dict[str, int | None]:
    """`authority.budgets` from the profile's own `default_authority`, when it
    declares one (the two factory-executable profiles); null otherwise, same
    as the universal envelope's own default."""
    defaults = profile.default_authority
    if defaults is None:
        return {"max_attempts": None, "max_llm_calls": None}
    return {
        "max_attempts": defaults.budgets.get("max_attempts"),
        "max_llm_calls": defaults.budgets.get("max_llm_calls"),
    }


def render_package(
    profile: DeliveryProfile,
    package_id: str,
    title: str,
    owner: str,
    created_at: str,
) -> dict:
    """Build the complete package.yaml document for one registered profile.

    Covers every key in `intent_packages.schema.TOP_SCHEMA` (the schema is
    closed: a missing key and an unknown key are both errors). Profile-driven
    parts are `profile_fields` (`_profile_fields`), `acceptance`
    (`_acceptance_items`), and `authority.budgets` (`_budgets`).
    """
    return {
        "schema_version": 1,
        "package_id": package_id,
        "title": title,
        "revision": 1,
        "status": "draft",
        "created_by": "factory-create",
        "owner": owner,
        "created_at": created_at,
        "supersedes": None,
        "profile": profile.name,
        "profile_fields": _profile_fields(profile),
        "outcome": {
            "what": f"Describe the outcome this {profile.name} package delivers.",
            "why": "Describe why this outcome matters and what problem it resolves.",
            "beneficiary": f"Describe who benefits once {package_id} ships.",
            "success_signal": "Describe the observable signal that proves the outcome landed.",
        },
        "scope": {
            "included": [f"Describe what {package_id} includes."],
            "excluded": [],
            "non_goals": [],
            "assumptions": [],
            "open_questions": [],
        },
        "sources": [
            {
                "location": (
                    "Describe where this package's intent came from "
                    "(a conversation, a backlog item, a design doc)."
                ),
                "authority_level": "authoritative",
                "required_version": None,
                "trust": "trusted_instruction",
                "sensitivity": "internal",
            }
        ],
        "constraints": {
            "time_budget": None,
            "technology": None,
            "policy_legal": None,
            "privacy_security": None,
            "compatibility": None,
            "quality_accessibility": None,
            "operational": None,
            "other": [],
        },
        "acceptance": _acceptance_items(profile),
        "authority": {
            "allowed": ["repository_read", "repository_write", "test_execution"],
            "requires_approval": ["merge_to_main"],
            "prohibited": ["secret_write"],
            "budgets": _budgets(profile),
        },
        "deliverables": {
            "artifacts": ["Describe the artifacts this package produces."],
            "destination": "packages/",
            "recipient": owner,
            "definition_of_done": "Describe what must be true for this package to be done.",
            "operator_responsibilities": [],
        },
        "dependencies": {
            "predecessor_packages": [],
            "external_decisions": [],
            "required_people_systems": [],
            "required_capabilities": [],
            "blocking_conditions": [],
        },
        "risk": {
            "failure_modes": [],
            "max_impact": "low",
            "stop_conditions": [],
            "rollback": "Describe how to roll back this change if it goes wrong.",
            "escalation_target": owner,
        },
        "verification": {
            "independent_review": [],
            "non_mechanical": [],
        },
        "follow_up": {
            "required": False,
            "revisit_when": None,
            "signals": [],
            "owner": None,
        },
        "applicable_standards": {"project": "1.0"},
    }


def render_lineage(package_id: str, created_at: str) -> dict:
    """Build the lineage.yaml document a fresh scaffold starts with: draft
    status, one unapproved revision, no transitions/approvals/grants."""
    return {
        "package_id": package_id,
        "current_state": "draft",
        "revisions": [
            {
                "revision": 1,
                "hash": "",
                "created_at": created_at,
                "author": "factory-create",
            }
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }


def _splice_acceptance_comments(yaml_text: str, profile: DeliveryProfile) -> str:
    """Insert comment blocks above the `acceptance:` key. `yaml.safe_dump`
    does not preserve comments, so they are spliced into the rendered text
    rather than attached to the data."""
    lines = yaml_text.splitlines(keepends=True)
    marker = "acceptance:\n"
    for index, line in enumerate(lines):
        if line == marker:
            blocks = ""
            if profile.name == "dependency-update":
                blocks += _DEPENDENCY_UPDATE_ENVELOPE_COMMENT
            blocks += _AC_ID_COMMENT
            lines.insert(index, "\n" + blocks)
            return "".join(lines)
    raise ValueError("rendered package.yaml has no top-level 'acceptance:' key")  # pragma: no cover


def _render_package_yaml(package: dict, profile: DeliveryProfile) -> str:
    body = yaml.safe_dump(package, sort_keys=False, default_flow_style=False, allow_unicode=True)
    return _splice_acceptance_comments(body, profile)


def create(
    profile_name: str,
    package_id: str,
    out_dir: str,
    *,
    owner: str = "devon",
    title: str = "",
) -> int:
    """Scaffold `<out_dir>/<package_id>/{package.yaml,lineage.yaml}` from a
    registered profile, then validate what was written.

    Returns 0 on success; 1 (with errors on stderr) for an unregistered
    profile, an already-existing target directory, or a scaffold that fails
    its own validation — a front door that emits an invalid package is worse
    than a blank page.
    """
    if profile_name not in PROFILES:
        print(
            f"create: unknown profile {profile_name!r}; valid: {sorted(PROFILES)}",
            file=sys.stderr,
        )
        return 1

    profile = PROFILES[profile_name]
    pkg_dir = Path(out_dir) / package_id
    if pkg_dir.exists():
        print(f"create: {pkg_dir} already exists; refusing to overwrite", file=sys.stderr)
        return 1

    created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    resolved_title = title or package_id.replace("-", " ").replace("_", " ").title()
    package = render_package(profile, package_id, resolved_title, owner, created_at)
    lineage_doc = render_lineage(package_id, created_at)
    lineage_doc["revisions"][0]["hash"] = canonical.package_hash(package)

    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(_render_package_yaml(package, profile), encoding="utf-8")
    write_lineage(pkg_dir, lineage_doc)

    errors = validate_package(pkg_dir)
    if errors:
        print(f"create: scaffold at {pkg_dir} failed validation:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"created {pkg_dir}")
    return 0


def validate(path: str) -> int:
    """Validate the package at `path` (a package directory or its
    package.yaml) — delegates to `intent_packages.validate.validate_package`,
    the same code path `intent_packages validate` uses, not a reimplementation.
    """
    pkg_dir = Path(path)
    if pkg_dir.is_file():
        pkg_dir = pkg_dir.parent

    errors = validate_package(pkg_dir)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"{pkg_dir}: valid")
    return 0
