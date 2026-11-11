"""Approval-by-conformance policy: the loader for approval-policy.toml (ADR-0028).

A standing dependency-update package is revised once per bump, and each revision needs an
approval. This module decides whether a given revision may take that approval from the
policy instead of from a named human -- and it can only ever answer with reasons to
REFUSE. :meth:`ApprovalPolicy.refusals_for` returns why policy objects; an empty tuple
means *this policy raises no objection*, which is strictly weaker than "approve it".
:func:`do_approve <intent_packages.operations.do_approve>` still requires a valid
package, a legal current state, no open questions, and a writable tamper-evident chain,
and nothing writable here can widen any of them.

**There is no way to express a permission.** A profile's grant is a description of the
shape the objections are withheld from; a profile with no grant draws
``profile_not_policy_approvable`` for every revision, forever. So the human requirement
is the default and recognition is the exception -- the arrangement
``factory-policy.toml`` uses for known-good authority patterns, and for the same reason:
a document that fails to load, a profile nobody described, and a field no grant accounts
for must all resolve the same way, to asking a person.

**Total coverage over the profile registry.** Every member of
:data:`~intent_packages.profiles.PROFILES` has exactly one row, and a row naming a
profile that registry does not know is an error. A profile shipped without a row stops
this document loading, and a document that does not load approves nothing.

**Nothing is cached.** The artifact is read and parsed on every consultation.

**The approver string carries the policy version, and that is ADR-0028's substantive
requirement** -- the ledger and the chain record which pre-decision was relied on, which
is re-derivable in a way a person's name is not. It is spelled
``policy:<profile>@v<version>``, a shape no registry agent id can take, so a policy
approval and a human approval can never be mistaken for one another.

**Schema 4 adds a second grant shape, the rotation grant** (orchestrator ADR-0055 amendment 22).
It gives ``non-software-operational`` a grant that withholds its objections only from a lane
credential's proposer-generated revision 1: a standing package at revision 1 whose lineage holds
no approval, ``created_by`` the proposer, one ``provider name=`` destination naming a granted
type, destinations of that type's kinds, an authority equal to one of the type's listed sets, and
no ``human_review`` criterion. It needs the lineage, so :meth:`ApprovalPolicy.refusals_for` takes
it, and a missing or unreadable lineage is a refusal. The orchestrator re-renders the package from
the registry; this module can't read the registry, so it checks only the shape it can see.

**THE SAME LITERAL IS SPELLED IN THE ORCHESTRATOR**
(``orchestrator.package_sources``), which re-verifies the approval before an intake and
which imports nothing from this repository. Both sides carry a test naming the shape, so
a change on one side is a red test rather than an intake that silently refuses every
policy-approved revision.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeGuard

from intent_packages.destination_format import (
    BOOLEAN_FIELDS,
    IDENTITY_FIELDS,
    DestinationFormatError,
    parse,
)
from intent_packages.members import MembersUnreadable, granted_targets
from intent_packages.profiles import PROFILES

# The shape of an approver that is a policy rather than a person. Anchored, lower-case,
# and carrying the schema version of the document that granted it.
POLICY_APPROVER_RE: Final = re.compile(r"^policy:([a-z0-9][a-z0-9-]*)@v([1-9][0-9]*)$")

# The versions this loader understands. An exact set, never a floor: an older process
# meeting a newer document would silently ignore whatever narrowing the new version
# introduced, which is the permissive reading of a version skew.
SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({1, 2, 3, 4})

# Schema 2 replaces a grant's hand-kept `target_repositories` with `targets_from`, which names a
# service in the SDS member record. A document at schema 1 must still carry the list, and a
# document at schema 2 must not: each version has exactly one source for the targets. Schema 3
# keeps `targets_from` and changes the reach: `reach_options` (a list of sets) replaces `reach`.
# Schema 4 keeps schema 3's grant shape and adds the rotation grant (`RotationGrant`).
TARGETS_FROM_PREFIX: Final = "sds-member-record:"

# Why policy objects. The whole output vocabulary of this module.
PROFILE_UNDECLARED: Final = "profile_undeclared"
PROFILE_UNRECOGNISED: Final = "profile_unrecognised"
PROFILE_NOT_POLICY_APPROVABLE: Final = "profile_not_policy_approvable"
TARGET_REPOSITORY_NOT_PERMITTED: Final = "target_repository_not_permitted"
MEMBER_RECORD_UNREADABLE: Final = "member_record_unreadable"
REACH_NOT_PERMITTED: Final = "reach_not_permitted"
AUTHORITY_TERMS_NOT_PERMITTED: Final = "authority_terms_not_permitted"
BUDGET_ABOVE_CEILING: Final = "budget_above_ceiling"
ACCEPTANCE_NOT_PERMITTED: Final = "acceptance_not_permitted"
MAX_IMPACT_NOT_PERMITTED: Final = "max_impact_not_permitted"
BUMP_VERSIONS_NOT_DISTINCT: Final = "bump_versions_not_distinct"
NOT_A_STANDING_PACKAGE: Final = "not_a_standing_package"
# The rotation grant's own refusals (schema 4). It also uses NOT_A_STANDING_PACKAGE,
# AUTHORITY_TERMS_NOT_PERMITTED and ACCEPTANCE_NOT_PERMITTED, in the sense each already has.
NOT_REVISION_ONE: Final = "not_revision_one"
LINEAGE_UNREADABLE: Final = "lineage_unreadable"
LINEAGE_HAS_APPROVAL: Final = "lineage_has_approval"
NOT_PROPOSER_GENERATED: Final = "not_proposer_generated"
ROTATION_TYPE_NOT_PERMITTED: Final = "rotation_type_not_permitted"
DESTINATIONS_NOT_PERMITTED: Final = "destinations_not_permitted"

_ROW_REQUIRED_FIELDS: Final = frozenset({"rationale", "decided"})
_ROW_OPTIONAL_FIELDS: Final = frozenset({"grant"})
_TARGET_FIELD_BY_SCHEMA: Final = {
    1: "target_repositories",
    2: "targets_from",
    3: "targets_from",
    4: "targets_from",
}
# Each schema has exactly one reach field: `reach` (one set) before schema 3, `reach_options`
# (any one of several sets) from it.
_REACH_FIELD_BY_SCHEMA: Final = {1: "reach", 2: "reach", 3: "reach_options", 4: "reach_options"}
_GRANT_FIELDS: Final = frozenset(
    {
        "rationale",
        "decided",
        "authority_allowed",
        "authority_requires_approval",
        "authority_prohibited",
        "max_attempts",
        "max_llm_calls",
        "acceptance_evidence_types",
        "acceptance_approvers",
        "max_impact",
    }
)
_TOP_LEVEL_FIELDS: Final = frozenset({"version", "profile"})

# The rotation grant (schema 4). Only this profile may carry one, and a grant is this shape
# exactly when it carries `types`; at schemas 1 to 3 `types` is an unknown grant field.
ROTATION_GRANT_PROFILE: Final = "non-software-operational"
ROTATION_GRANT_MIN_SCHEMA: Final = 4
_ROTATION_GRANT_FIELDS: Final = frozenset({"rationale", "decided", "created_by", "types"})
_ROTATION_TYPE_FIELDS: Final = frozenset({"destinations", "authority_options"})
_AUTHORITY_SET_FIELDS: Final = frozenset(
    {"allowed", "requires_approval", "prohibited", "max_attempts"}
)
_PROVIDER_KIND: Final = "provider"


class ApprovalPolicyError(Exception):
    """The artifact is missing, malformed, or at a schema version this loader does not know.

    Never a refusal: a refusal is an answer about one revision, and this is the document
    being unusable, which must stop the operation rather than produce an empty objection
    list that reads as consent.
    """


@dataclass(frozen=True)
class Grant:
    """The shape a profile's revisions may be approved by conformance to.

    The targets come from one source per schema version: ``target_repositories`` (schema 1,
    a fixed list; ``target_service`` is None) or ``targets_from`` (schemas 2 and 3, the member
    record's grant for ``target_service``; ``target_repositories`` is empty).

    ``reach_options`` holds the reach sets a revision may declare, any ONE of them exactly.
    Schemas 1 and 2 carry a single ``reach`` and load it as a one-option tuple.

    Every field is a bound, and every bound narrows: the sets are what a revision may
    declare and the numbers are ceilings. There is no field whose value permits something
    the rest of the approval path would otherwise refuse.
    """

    rationale: str
    decided: str
    target_repositories: frozenset[str]
    target_service: str | None
    reach_options: tuple[tuple[str, ...], ...]
    authority_allowed: tuple[str, ...]
    authority_requires_approval: tuple[str, ...]
    authority_prohibited: tuple[str, ...]
    max_attempts: int
    max_llm_calls: int
    acceptance_evidence_types: frozenset[str]
    acceptance_approvers: frozenset[str]
    max_impact: frozenset[str]


@dataclass(frozen=True)
class DestinationPattern:
    """One destination a rotation type has: its kind, and any identity fields it must hold.

    The provider pattern holds no fields; its `name` is the type's own name.
    """

    kind: str
    fields: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class AuthoritySet:
    """One authority a rotation type's package may declare, compared whole.

    ``max_llm_calls`` has no field: a rotation package declares it null, because the rotation
    executor makes no LLM call, and TOML can't write null. Any other value refuses.
    """

    allowed: tuple[str, ...]
    requires_approval: tuple[str, ...]
    prohibited: tuple[str, ...]
    max_attempts: int


@dataclass(frozen=True)
class RotationType:
    destinations: tuple[DestinationPattern, ...]
    authority_options: tuple[AuthoritySet, ...]


@dataclass(frozen=True)
class RotationGrant:
    """The shape a lane credential's proposer-generated revision 1 may be approved by (schema 4).

    ``types`` is keyed by the name the package's ``provider name=`` destination carries.
    """

    rationale: str
    decided: str
    created_by: str
    types: dict[str, RotationType]


@dataclass(frozen=True)
class ApprovalPolicy:
    version: int
    grants: dict[str, Grant | RotationGrant | None]

    def approver_for(self, profile: str) -> str:
        """The approver string a conformant revision of this profile is approved under."""
        return f"policy:{profile}@v{self.version}"

    def refusals_for(
        self, package: dict[str, Any], lineage: dict[str, Any] | None = None
    ) -> tuple[str, ...]:
        """Why this policy objects to approving this package. Empty means no objection.

        Fail-closed in every direction a package can be surprising: an absent profile, a
        profile outside the registry, a profile with no grant, and a field whose value is
        not the shape a grant describes all produce an objection rather than the absence
        of one. ``lineage`` is the package's ``lineage.yaml``; the rotation grant reads it,
        and refuses ``lineage_unreadable`` when it is None or not a lineage's shape.
        """
        profile = package.get("profile")
        if not isinstance(profile, str) or not profile:
            return (PROFILE_UNDECLARED,)
        if profile not in self.grants:
            return (PROFILE_UNRECOGNISED,)
        grant = self.grants[profile]
        if grant is None:
            return (PROFILE_NOT_POLICY_APPROVABLE,)
        if isinstance(grant, RotationGrant):
            return _rotation_refusals(package, lineage, grant)
        return tuple(
            refusal
            for refusal in (
                _target_refusal(package, grant),
                _standing_refusal(package),
                _bump_refusal(package),
                _reach_refusal(package, grant),
                _authority_refusal(package, grant),
                _budget_refusal(package, grant),
                _acceptance_refusal(package, grant),
                _impact_refusal(package, grant),
            )
            if refusal is not None
        )


def is_policy_approver(approver: object) -> bool:
    """Whether this approver string is a policy rather than a registry identity."""
    return isinstance(approver, str) and POLICY_APPROVER_RE.match(approver) is not None


def default_policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "approval-policy.toml"


def load_policy(path: Path | None = None) -> ApprovalPolicy:
    """Read and parse the artifact. Raises rather than yielding an empty policy.

    An empty policy is the permissive reading of a broken file for a caller that treats
    "no objections" as consent, so a malformed document must not be able to produce one.
    """
    artifact = path or default_policy_path()
    try:
        raw = tomllib.loads(artifact.read_text(encoding="utf-8"))
    except OSError as error:
        raise ApprovalPolicyError(f"the approval policy is unreadable: {artifact}") from error
    except tomllib.TOMLDecodeError as error:
        raise ApprovalPolicyError(f"the approval policy is malformed: {error}") from error

    unknown = set(raw) - _TOP_LEVEL_FIELDS
    if unknown:
        raise ApprovalPolicyError(f"the approval policy has unknown fields: {sorted(unknown)}")
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ApprovalPolicyError("the approval policy declares no schema version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ApprovalPolicyError(
            f"the approval policy is at schema version {version}, which this build does "
            f"not know; supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    rows = raw.get("profile")
    if not isinstance(rows, dict):
        raise ApprovalPolicyError("the approval policy declares no profile rows")
    if set(rows) != set(PROFILES):
        missing = sorted(set(PROFILES) - set(rows))
        extra = sorted(set(rows) - set(PROFILES))
        raise ApprovalPolicyError(
            f"the approval policy must have exactly one row per registered profile; "
            f"missing: {missing}; unknown: {extra}"
        )
    return ApprovalPolicy(
        version=version,
        grants={name: _row(name, table, version) for name, table in rows.items()},
    )


def _row(name: str, table: object, version: int) -> Grant | RotationGrant | None:
    where = f"profile.{name}"
    if not isinstance(table, dict):
        raise ApprovalPolicyError(f"{where}: must be a table")
    missing = _ROW_REQUIRED_FIELDS - set(table)
    if missing:
        raise ApprovalPolicyError(f"{where}: missing {sorted(missing)}")
    unknown = set(table) - _ROW_REQUIRED_FIELDS - _ROW_OPTIONAL_FIELDS
    if unknown:
        raise ApprovalPolicyError(f"{where}: unknown fields {sorted(unknown)}")
    _text(table, "rationale", where)
    _text(table, "decided", where)
    if "grant" not in table:
        return None
    grant = table["grant"]
    if version >= ROTATION_GRANT_MIN_SCHEMA and isinstance(grant, dict) and "types" in grant:
        if name != ROTATION_GRANT_PROFILE:
            raise ApprovalPolicyError(
                f"{where}.grant: only {ROTATION_GRANT_PROFILE} may carry a rotation grant"
            )
        return _rotation_grant(f"{where}.grant", grant)
    return _grant(f"{where}.grant", grant, version)


def _rotation_grant(where: str, table: dict) -> RotationGrant:
    _exact_fields(table, _ROTATION_GRANT_FIELDS, where)
    types = table["types"]
    if not isinstance(types, dict) or not types:
        raise ApprovalPolicyError(f"{where}: types must be a non-empty table")
    return RotationGrant(
        rationale=_text(table, "rationale", where),
        decided=_text(table, "decided", where),
        created_by=_text(table, "created_by", where),
        types={
            name: _rotation_type(f"{where}.types.{name}", entry) for name, entry in types.items()
        },
    )


def _rotation_type(where: str, table: object) -> RotationType:
    if not isinstance(table, dict):
        raise ApprovalPolicyError(f"{where}: must be a table")
    _exact_fields(table, _ROTATION_TYPE_FIELDS, where)
    patterns = _tables(table, "destinations", where)
    destinations = tuple(_destination_pattern(f"{where}.destinations", p) for p in patterns)
    kinds = [pattern.kind for pattern in destinations]
    if len(set(kinds)) != len(kinds):
        raise ApprovalPolicyError(f"{where}: destinations repeat a kind")
    if _PROVIDER_KIND not in kinds:
        raise ApprovalPolicyError(f"{where}: destinations must include the provider")
    options = _tables(table, "authority_options", where)
    return RotationType(
        destinations=destinations,
        authority_options=tuple(
            _authority_set(f"{where}.authority_options", option) for option in options
        ),
    )


def _destination_pattern(where: str, table: dict) -> DestinationPattern:
    kind = table.get("kind")
    if not isinstance(kind, str) or kind not in IDENTITY_FIELDS:
        raise ApprovalPolicyError(f"{where}: kind {kind!r} is no destination kind")
    fields = {key: value for key, value in table.items() if key != "kind"}
    unknown = set(fields) - set(IDENTITY_FIELDS[kind])
    if kind == _PROVIDER_KIND:
        unknown = set(fields)  # The provider's name is the type's own.
    if unknown:
        raise ApprovalPolicyError(f"{where}: {kind} may not pin {sorted(unknown)}")
    for key, value in fields.items():
        typed = (
            isinstance(value, bool)
            if key in BOOLEAN_FIELDS
            else isinstance(value, str) and bool(value.strip())
        )
        if not typed:
            raise ApprovalPolicyError(f"{where}: {kind} pins {key} to {value!r}, the wrong type")
    return DestinationPattern(kind=kind, fields=tuple(sorted(fields.items())))


def _authority_set(where: str, table: dict) -> AuthoritySet:
    _exact_fields(table, _AUTHORITY_SET_FIELDS, where)
    authority = AuthoritySet(
        allowed=_strings(table, "allowed", where),
        requires_approval=_strings(table, "requires_approval", where, allow_empty=True),
        prohibited=_strings(table, "prohibited", where),
        max_attempts=_positive_int(table, "max_attempts", where),
    )
    terms = [*authority.allowed, *authority.requires_approval, *authority.prohibited]
    if len(set(terms)) != len(terms):
        raise ApprovalPolicyError(f"{where}: a term appears twice across the three lists")
    return authority


def _exact_fields(table: dict, fields: frozenset[str], where: str) -> None:
    missing = fields - set(table)
    if missing:
        raise ApprovalPolicyError(f"{where}: missing {sorted(missing)}")
    unknown = set(table) - fields
    if unknown:
        raise ApprovalPolicyError(f"{where}: unknown fields {sorted(unknown)}")


def _tables(table: dict, key: str, where: str) -> list[dict]:
    value = table.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(v, dict) for v in value):
        raise ApprovalPolicyError(f"{where}: {key} must be a non-empty list of tables")
    return value


def _grant(where: str, table: object, version: int) -> Grant:
    if not isinstance(table, dict):
        raise ApprovalPolicyError(f"{where}: must be a table")
    fields = _GRANT_FIELDS | {_TARGET_FIELD_BY_SCHEMA[version], _REACH_FIELD_BY_SCHEMA[version]}
    missing = fields - set(table)
    if missing:
        raise ApprovalPolicyError(f"{where}: missing {sorted(missing)}")
    unknown = set(table) - fields
    if unknown:
        raise ApprovalPolicyError(f"{where}: unknown fields {sorted(unknown)}")
    return Grant(
        rationale=_text(table, "rationale", where),
        decided=_text(table, "decided", where),
        target_repositories=(
            frozenset(_strings(table, "target_repositories", where))
            if version == 1
            else frozenset()
        ),
        target_service=_target_service(table, where) if version >= 2 else None,
        reach_options=_reach_options(table, version, where),
        authority_allowed=_strings(table, "authority_allowed", where),
        authority_requires_approval=_strings(
            table, "authority_requires_approval", where, allow_empty=True
        ),
        authority_prohibited=_strings(table, "authority_prohibited", where),
        max_attempts=_positive_int(table, "max_attempts", where),
        max_llm_calls=_positive_int(table, "max_llm_calls", where),
        acceptance_evidence_types=frozenset(_strings(table, "acceptance_evidence_types", where)),
        acceptance_approvers=frozenset(_strings(table, "acceptance_approvers", where)),
        max_impact=frozenset(_strings(table, "max_impact", where)),
    )


def _reach_options(table: dict, version: int, where: str) -> tuple[tuple[str, ...], ...]:
    if version < 3:
        return (_strings(table, "reach", where),)
    options = table.get("reach_options")
    if not isinstance(options, list) or not options:
        raise ApprovalPolicyError(f"{where}: reach_options must be a non-empty list")
    parsed = []
    for option in options:
        valid = (
            isinstance(option, list)
            and option
            and all(isinstance(item, str) and item for item in option)
        )
        if not valid:
            raise ApprovalPolicyError(
                f"{where}: reach_options option {option!r} must be a non-empty list of strings"
            )
        if len(set(option)) != len(option):
            raise ApprovalPolicyError(f"{where}: reach_options option {option!r} repeats a member")
        parsed.append(tuple(option))
    return tuple(parsed)


def _target_service(table: dict, where: str) -> str:
    source = _text(table, "targets_from", where)
    service = source.removeprefix(TARGETS_FROM_PREFIX)
    if service == source or not re.fullmatch(r"[a-z][a-z_]*", service):
        raise ApprovalPolicyError(
            f"{where}: targets_from must be '{TARGETS_FROM_PREFIX}<service>', got {source!r}"
        )
    return service


def _text(table: dict, key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApprovalPolicyError(f"{where}: {key} must be a non-empty string")
    return value


def _strings(table: dict, key: str, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    """A list of non-empty strings. Empty is refused unless the field says "nothing" is a
    legitimate grant: `authority_requires_approval` is empty once the merge is allowed."""
    value = table.get(key)
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ApprovalPolicyError(f"{where}: {key} must be a non-empty list")
    if not all(isinstance(item, str) and item for item in value):
        raise ApprovalPolicyError(f"{where}: {key} must hold non-empty strings")
    return tuple(value)


def _positive_int(table: dict, key: str, where: str) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ApprovalPolicyError(f"{where}: {key} must be a positive integer")
    return value


def _target_refusal(package: dict[str, Any], grant: Grant) -> str | None:
    fields = package.get("profile_fields")
    target = fields.get("target_repo") if isinstance(fields, dict) else None
    if not isinstance(target, str):
        return TARGET_REPOSITORY_NOT_PERMITTED
    if grant.target_service is None:
        return None if target in grant.target_repositories else TARGET_REPOSITORY_NOT_PERMITTED
    try:
        granted = granted_targets(grant.target_service)
    except MembersUnreadable as error:
        # Fail closed: an unreadable record is a refusal naming the cause, never an approval.
        return f"{MEMBER_RECORD_UNREADABLE}: {error}"
    return None if target.casefold() in granted else TARGET_REPOSITORY_NOT_PERMITTED


def _standing_refusal(package: dict[str, Any]) -> str | None:
    """Only a STANDING package may be approved by policy, and the author declares which.

    UNCONDITIONAL for a granted profile, with no field in the grant to relax it. The
    alternative was measured rather than imagined: every dependency-update package in
    this repository declares the same profile and the same target-repository field, so a
    grant keyed on those alone covers the whole historical population -- eight packages
    naming one finished bump each, any of which a producer scanning the checkout would
    happily revise. `standing` is the only thing that distinguishes a lane from a
    completed one-off, and it is what the pre-decision was actually about.
    """
    fields = package.get("profile_fields")
    standing = fields.get("standing") if isinstance(fields, dict) else None
    return None if standing is True else NOT_A_STANDING_PACKAGE


def _bump_refusal(package: dict[str, Any]) -> str | None:
    """A revision whose two versions are the same is not a bump, so it cannot be one.

    THIS IS THE INTERLOCK THAT STOPS AN UNFILLED SHELL BEING APPROVED. A standing package
    is authored with its target repository and its dependency name -- which are standing
    facts -- and with both version fields holding the same placeholder, because nobody
    knows the bump yet. The producer writes the two versions and only then approves. An
    approval attempted before that finds them equal and refuses, so a shell can never
    become an approved revision describing no work.

    Deliberately NOT a version parse. Ordering, precedence and pre-release rules differ
    per ecosystem, and re-deciding them here would be a second answer to a question the
    producer has already answered against the transcribed cascade -- the fourth copy of a
    vocabulary this estate has paid for three times. Distinctness is the strongest claim
    that needs no such knowledge.
    """
    fields = package.get("profile_fields")
    if not isinstance(fields, dict):
        return BUMP_VERSIONS_NOT_DISTINCT
    before, after = fields.get("from_version"), fields.get("to_version")
    if not isinstance(before, str) or not isinstance(after, str) or before == after:
        return BUMP_VERSIONS_NOT_DISTINCT
    return None


def _reach_refusal(package: dict[str, Any], grant: Grant) -> str | None:
    """EXACTLY one of the granted reach sets, never a subset.

    A subset test would withhold the objection from a package declaring nothing, which is
    the reading `reach: []` should never get; and adding a member to a reach set can only
    make work touch MORE, so "at most what was granted" is the only safe direction and
    equality is the cheapest way to say it.
    """
    reach = package.get("reach")
    if not isinstance(reach, list) or not any(list(reach) == list(o) for o in grant.reach_options):
        return REACH_NOT_PERMITTED
    return None


def _authority_refusal(package: dict[str, Any], grant: Grant) -> str | None:
    authority = package.get("authority")
    if not isinstance(authority, dict):
        return AUTHORITY_TERMS_NOT_PERMITTED
    expected = (
        ("allowed", grant.authority_allowed),
        ("requires_approval", grant.authority_requires_approval),
        ("prohibited", grant.authority_prohibited),
    )
    for key, permitted in expected:
        declared = authority.get(key)
        if not isinstance(declared, list) or sorted(declared) != sorted(permitted):
            return AUTHORITY_TERMS_NOT_PERMITTED
    return None


def _budget_refusal(package: dict[str, Any], grant: Grant) -> str | None:
    """A ceiling, so a revision may spend less and never more.

    A null budget is refused rather than read as "the default", so that a revision
    declaring nothing cannot silently acquire whatever the profile constant happens
    to be. That constant was four LLM calls when this refusal was written -- under a
    tenth of the smallest burn ever measured here -- and it has since been 120, 240
    and 360. The number moving is the reason the rule is about DECLARING rather than
    about any particular default.
    """
    authority = package.get("authority")
    budgets = authority.get("budgets") if isinstance(authority, dict) else None
    if not isinstance(budgets, dict):
        return BUDGET_ABOVE_CEILING
    for key, ceiling in (
        ("max_attempts", grant.max_attempts),
        ("max_llm_calls", grant.max_llm_calls),
    ):
        value = budgets.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > ceiling:
            return BUDGET_ABOVE_CEILING
    return None


def _acceptance_refusal(package: dict[str, Any], grant: Grant) -> str | None:
    criteria = package.get("acceptance")
    if not isinstance(criteria, list) or not criteria:
        return ACCEPTANCE_NOT_PERMITTED
    for criterion in criteria:
        if not isinstance(criterion, dict):
            return ACCEPTANCE_NOT_PERMITTED
        if criterion.get("evidence_type") not in grant.acceptance_evidence_types:
            return ACCEPTANCE_NOT_PERMITTED
        if criterion.get("approver") not in grant.acceptance_approvers:
            return ACCEPTANCE_NOT_PERMITTED
    return None


def _impact_refusal(package: dict[str, Any], grant: Grant) -> str | None:
    risk = package.get("risk")
    impact = risk.get("max_impact") if isinstance(risk, dict) else None
    if impact not in grant.max_impact:
        return MAX_IMPACT_NOT_PERMITTED
    return None


# --- the rotation grant (schema 4) ---------------------------------------------------


def _rotation_refusals(
    package: dict[str, Any], lineage: dict[str, Any] | None, grant: RotationGrant
) -> tuple[str, ...]:
    """Every condition of ADR-0055 amendment 22's grant, each refused on its own.

    The destinations and authority checks need the type, so they are skipped when the type
    refusal already stands: one wrong provider then reads as one refusal, not three.
    """
    rotation_type = _granted_type(package, grant)
    return tuple(
        refusal
        for refusal in (
            _standing_refusal(package),
            _first_revision_refusal(package, lineage),
            _lineage_approval_refusal(lineage),
            _proposer_refusal(package, grant),
            None if rotation_type is not None else ROTATION_TYPE_NOT_PERMITTED,
            None if rotation_type is None else _destinations_refusal(package, rotation_type),
            None if rotation_type is None else _rotation_authority_refusal(package, rotation_type),
            _human_review_refusal(package),
        )
        if refusal is not None
    )


def _readable_lineage(lineage: object) -> TypeGuard[dict[str, Any]]:
    """A lineage's shape: a missing key or a wrong type is unreadable, never empty."""
    return (
        isinstance(lineage, dict)
        and isinstance(lineage.get("revisions"), list)
        and isinstance(lineage.get("approvals"), list)
    )


def _first_revision_refusal(package: dict[str, Any], lineage: dict[str, Any] | None) -> str | None:
    """Revision 1, and a lineage that lists revision 1 alone.

    `True == 1` in Python, so a boolean revision is refused by type. An unreadable lineage is
    `_lineage_approval_refusal`'s to report, so this checks only the package then.
    """
    revision = package.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision != 1:
        return NOT_REVISION_ONE
    if not _readable_lineage(lineage):
        return None
    revisions = lineage["revisions"]
    if len(revisions) != 1 or not isinstance(revisions[0], dict):
        return NOT_REVISION_ONE
    listed = revisions[0].get("revision")
    if not isinstance(listed, int) or isinstance(listed, bool) or listed != 1:
        return NOT_REVISION_ONE
    return None


def _lineage_approval_refusal(lineage: dict[str, Any] | None) -> str | None:
    """No approval at all. Any entry refuses, a matching one included, so a replay of a
    policy approval that crashed after writing its lineage refuses too and waits for a person."""
    if not _readable_lineage(lineage):
        return LINEAGE_UNREADABLE
    return LINEAGE_HAS_APPROVAL if lineage["approvals"] else None


def _proposer_refusal(package: dict[str, Any], grant: RotationGrant) -> str | None:
    """The author's word only: the orchestrator's re-render is what proves it."""
    return None if package.get("created_by") == grant.created_by else NOT_PROPOSER_GENERATED


def _parsed_destinations(package: dict[str, Any]) -> list[dict[str, object]] | None:
    """Every destination parsed, or None when any isn't a canonical destination string."""
    fields = package.get("profile_fields")
    destinations = fields.get("destinations") if isinstance(fields, dict) else None
    if not isinstance(destinations, list) or not all(isinstance(d, str) for d in destinations):
        return None
    try:
        return [parse(destination) for destination in destinations]
    except DestinationFormatError:
        return None


def _granted_type(package: dict[str, Any], grant: RotationGrant) -> RotationType | None:
    """The granted type the package's one `provider name=` destination names, or None.

    Reads only the provider strings, so a malformed keeper or copy is the destinations
    refusal's to report, not this one's.
    """
    fields = package.get("profile_fields")
    destinations = fields.get("destinations") if isinstance(fields, dict) else None
    if not isinstance(destinations, list):
        return None
    providers = [
        d for d in destinations if isinstance(d, str) and d.startswith(f"{_PROVIDER_KIND} ")
    ]
    if len(providers) != 1:
        return None
    try:
        name = parse(providers[0])["name"]
    except DestinationFormatError:
        return None
    return grant.types.get(name) if isinstance(name, str) else None


def _destinations_refusal(package: dict[str, Any], rotation_type: RotationType) -> str | None:
    """Exactly the type's kinds, one of each, each holding any field its pattern pins."""
    parsed = _parsed_destinations(package)
    if parsed is None:
        return DESTINATIONS_NOT_PERMITTED
    patterns = {pattern.kind: pattern for pattern in rotation_type.destinations}
    if sorted(str(d["kind"]) for d in parsed) != sorted(patterns):
        return DESTINATIONS_NOT_PERMITTED
    for destination in parsed:
        pattern = patterns[str(destination["kind"])]
        if any(destination.get(key) != value for key, value in pattern.fields):
            return DESTINATIONS_NOT_PERMITTED
    return None


def _rotation_authority_refusal(package: dict[str, Any], rotation_type: RotationType) -> str | None:
    """Equal to one of the type's sets, compared whole: the three lists and both budgets."""
    authority = package.get("authority")
    if not isinstance(authority, dict):
        return AUTHORITY_TERMS_NOT_PERMITTED
    budgets = authority.get("budgets")
    if not isinstance(budgets, dict) or budgets.get("max_llm_calls", 0) is not None:
        return AUTHORITY_TERMS_NOT_PERMITTED
    attempts = budgets.get("max_attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool):
        return AUTHORITY_TERMS_NOT_PERMITTED
    if any(
        _authority_equals(authority, attempts, option) for option in rotation_type.authority_options
    ):
        return None
    return AUTHORITY_TERMS_NOT_PERMITTED


def _authority_equals(authority: dict, attempts: int, option: AuthoritySet) -> bool:
    for key, permitted in (
        ("allowed", option.allowed),
        ("requires_approval", option.requires_approval),
        ("prohibited", option.prohibited),
    ):
        declared = authority.get(key)
        if not isinstance(declared, list) or not all(isinstance(d, str) for d in declared):
            return False
        if sorted(declared) != sorted(permitted):
            return False
    return attempts == option.max_attempts


def _human_review_refusal(package: dict[str, Any]) -> str | None:
    """No `human_review` criterion: a person's judgement is a gate nobody chose by policy."""
    criteria = package.get("acceptance")
    if not isinstance(criteria, list) or not criteria:
        return ACCEPTANCE_NOT_PERMITTED
    for criterion in criteria:
        if not isinstance(criterion, dict) or criterion.get("evidence_type") == "human_review":
            return ACCEPTANCE_NOT_PERMITTED
    return None
