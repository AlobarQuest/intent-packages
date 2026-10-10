"""Non-software-operational delivery profile (WS-P2.10): work with no repo,
no CI, and no authority envelope — listing launches and similar operational
workflows. Shaped from archive/ws-2.4-historical-listing-launch (the
reference exemplar); WS-P2.13's native run authors the first package that
declares it. Evidence comes from humans, external systems, and observations
only — the tag map has no ci:/gate: entries, so automated_test is
structurally unreachable, and it is explicitly forbidden for defense in
depth."""

from __future__ import annotations

from intent_packages.profiles._evidence_tags import check_evidence_tags
from intent_packages.profiles.base import DeliveryProfile, EnrichmentSpec
from intent_packages.schema import ListSpec, MapSpec, OptionalKey, _s, _walk

PROFILE_FIELDS_SCHEMA = MapSpec(
    {
        "owner": _s(str),
        "operating_procedure": _s(str),
        "external_systems": OptionalKey(ListSpec(_s(str))),
        # ADR-0054. A STANDING package rotates one credential and is revised once per
        # rotation (the ADR-0028 shape). Declared by the AUTHOR, never by the producer that
        # revises it. The two fields below are required when it is set, and optional
        # otherwise, so every package written before ADR-0054 validates and hashes as before.
        "standing": OptionalKey(_s(bool)),
        # The id this credential has in infraops' `.cred-consumers.toml`. A standing fact:
        # written once by the author, never by a revision.
        "credential_id": OptionalKey(_s(str)),
        # What THIS revision rotates for: the per-revision value, as from_version/to_version
        # are for a standing dependency-update package. A free string naming the trigger
        # (e.g. '2026-10-07-exposure'), not a date: two rotations of one credential on one
        # day must still be told apart, and a format rule here would be a second vocabulary.
        # QUOTE IT: an unquoted 2026-10-07 loads as a YAML date and fails `str`.
        "occurrence": OptionalKey(_s(str)),
        # ADR-0055. Everywhere this credential's value is minted, stored and consumed, one flat
        # string per destination (consumer kind and destination), sorted and unique so a
        # revision's diff shows exactly what changed. Written by the AUTHOR; the producer that
        # revises a standing package carries it forward unchanged. Devon reads its change against
        # the last approved revision before approving. Optional, as `standing` is: a package
        # approved before ADR-0055 carries none and hashes as before. The rotation executor
        # refuses unless this list, the unit envelope's and the registry's are equal.
        "destinations": OptionalKey(ListSpec(_s(str))),
    }
)

TAG_TO_EVIDENCE_TYPE = {
    "human:": "human_review",
    "external:": "external_attestation",
    "observation:": "observation",
}

_NON_EMPTY_STRING_FIELDS = ("owner", "operating_procedure")
_STANDING_REQUIRED_FIELDS = ("credential_id", "occurrence")


def _check_profile_fields(package: dict) -> list[str]:
    errors: list[str] = []
    if "profile_fields" not in package:
        errors.append("profile_fields: missing required key")
        return errors
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        return errors
    _walk(fields, PROFILE_FIELDS_SCHEMA, "profile_fields", errors)
    if errors:
        return errors
    for key in _NON_EMPTY_STRING_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and not value.strip():
            errors.append(f"profile_fields.{key}: must be a non-empty string")
    destinations = fields.get("destinations")
    if isinstance(destinations, list):
        errors.extend(_destination_errors(destinations))
    if fields.get("standing") is True:
        for key in _STANDING_REQUIRED_FIELDS:
            value = fields.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"profile_fields.{key}: required, as a non-empty string, when "
                    "profile_fields.standing is true"
                )
    return errors


def _destination_errors(destinations: list[str]) -> list[str]:
    if not destinations:
        return ["profile_fields.destinations: must name at least one destination"]
    if any(not value.strip() or value != value.strip() for value in destinations):
        return ["profile_fields.destinations: each entry must be a non-blank, trimmed string"]
    if destinations != sorted(set(destinations)):
        return ["profile_fields.destinations: entries must be sorted and unique"]
    return []


def validate(package: dict) -> list[str]:
    errors = _check_profile_fields(package)
    errors.extend(check_evidence_tags(package, TAG_TO_EVIDENCE_TYPE))
    return errors


DELIVERY_PROFILE = DeliveryProfile(
    name="non-software-operational",
    # `enrichment_for_profile` returns None for a profile that declares no spec, on the reasoning
    # that a profile the factory cannot execute "has no workers to tell". That reasoning does not
    # hold here: this profile's units are discharged by a human or a local operator who reads the
    # runner brief, so there IS a worker, and telling them nothing is a choice rather than an
    # absence. WS-P2.13's rotation package is the proof -- an infra-authority projection returns
    # `bws.no-token-in-tracked-files`, `bws.no-token-in-git-history`,
    # `bws.bootstrap-token-not-inline` and `cred.exposure-rotate`, which is precisely the governed
    # knowledge a credential rotation must honour. No code road applies: the Code Brain's only
    # substantive road is `error-logging`, and this profile ships no code.
    enrichment=EnrichmentSpec(code_road_slugs=(), infra_min_authority="required"),
    profile_fields_schema=PROFILE_FIELDS_SCHEMA,
    tag_to_evidence_type=TAG_TO_EVIDENCE_TYPE,
    forbidden_evidence_types=frozenset({"automated_test"}),
    evidence_expectations=(
        "human_review, external_attestation, and observation only; no automated "
        "producers exist for this profile's work."
    ),
    observation_window=(
        "Declared per package via follow_up (e.g. days-on-market signals for a listing launch)."
    ),
    validate=validate,
)
