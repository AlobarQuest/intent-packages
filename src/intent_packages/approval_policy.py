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
from typing import Any, Final

from intent_packages.profiles import PROFILES

# The shape of an approver that is a policy rather than a person. Anchored, lower-case,
# and carrying the schema version of the document that granted it.
POLICY_APPROVER_RE: Final = re.compile(r"^policy:([a-z0-9][a-z0-9-]*)@v([1-9][0-9]*)$")

# The versions this loader understands. An exact set, never a floor: an older process
# meeting a newer document would silently ignore whatever narrowing the new version
# introduced, which is the permissive reading of a version skew.
SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({1})

# Why policy objects. The whole output vocabulary of this module.
PROFILE_UNDECLARED: Final = "profile_undeclared"
PROFILE_UNRECOGNISED: Final = "profile_unrecognised"
PROFILE_NOT_POLICY_APPROVABLE: Final = "profile_not_policy_approvable"
TARGET_REPOSITORY_NOT_PERMITTED: Final = "target_repository_not_permitted"
REACH_NOT_PERMITTED: Final = "reach_not_permitted"
AUTHORITY_TERMS_NOT_PERMITTED: Final = "authority_terms_not_permitted"
BUDGET_ABOVE_CEILING: Final = "budget_above_ceiling"
ACCEPTANCE_NOT_PERMITTED: Final = "acceptance_not_permitted"
MAX_IMPACT_NOT_PERMITTED: Final = "max_impact_not_permitted"
BUMP_VERSIONS_NOT_DISTINCT: Final = "bump_versions_not_distinct"
NOT_A_STANDING_PACKAGE: Final = "not_a_standing_package"

_ROW_REQUIRED_FIELDS: Final = frozenset({"rationale", "decided"})
_ROW_OPTIONAL_FIELDS: Final = frozenset({"grant"})
_GRANT_FIELDS: Final = frozenset(
    {
        "rationale",
        "decided",
        "target_repositories",
        "reach",
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


class ApprovalPolicyError(Exception):
    """The artifact is missing, malformed, or at a schema version this loader does not know.

    Never a refusal: a refusal is an answer about one revision, and this is the document
    being unusable, which must stop the operation rather than produce an empty objection
    list that reads as consent.
    """


@dataclass(frozen=True)
class Grant:
    """The shape a profile's revisions may be approved by conformance to.

    Every field is a bound, and every bound narrows: the sets are what a revision may
    declare and the numbers are ceilings. There is no field whose value permits something
    the rest of the approval path would otherwise refuse.
    """

    rationale: str
    decided: str
    target_repositories: frozenset[str]
    reach: tuple[str, ...]
    authority_allowed: tuple[str, ...]
    authority_requires_approval: tuple[str, ...]
    authority_prohibited: tuple[str, ...]
    max_attempts: int
    max_llm_calls: int
    acceptance_evidence_types: frozenset[str]
    acceptance_approvers: frozenset[str]
    max_impact: frozenset[str]


@dataclass(frozen=True)
class ApprovalPolicy:
    version: int
    grants: dict[str, Grant | None]

    def approver_for(self, profile: str) -> str:
        """The approver string a conformant revision of this profile is approved under."""
        return f"policy:{profile}@v{self.version}"

    def refusals_for(self, package: dict[str, Any]) -> tuple[str, ...]:
        """Why this policy objects to approving this package. Empty means no objection.

        Fail-closed in every direction a package can be surprising: an absent profile, a
        profile outside the registry, a profile with no grant, and a field whose value is
        not the shape a grant describes all produce an objection rather than the absence
        of one.
        """
        profile = package.get("profile")
        if not isinstance(profile, str) or not profile:
            return (PROFILE_UNDECLARED,)
        if profile not in self.grants:
            return (PROFILE_UNRECOGNISED,)
        grant = self.grants[profile]
        if grant is None:
            return (PROFILE_NOT_POLICY_APPROVABLE,)
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
        grants={name: _row(name, table) for name, table in rows.items()},
    )


def _row(name: str, table: object) -> Grant | None:
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
    return _grant(f"{where}.grant", table["grant"])


def _grant(where: str, table: object) -> Grant:
    if not isinstance(table, dict):
        raise ApprovalPolicyError(f"{where}: must be a table")
    missing = _GRANT_FIELDS - set(table)
    if missing:
        raise ApprovalPolicyError(f"{where}: missing {sorted(missing)}")
    unknown = set(table) - _GRANT_FIELDS
    if unknown:
        raise ApprovalPolicyError(f"{where}: unknown fields {sorted(unknown)}")
    return Grant(
        rationale=_text(table, "rationale", where),
        decided=_text(table, "decided", where),
        target_repositories=frozenset(_strings(table, "target_repositories", where)),
        reach=_strings(table, "reach", where),
        authority_allowed=_strings(table, "authority_allowed", where),
        authority_requires_approval=_strings(table, "authority_requires_approval", where),
        authority_prohibited=_strings(table, "authority_prohibited", where),
        max_attempts=_positive_int(table, "max_attempts", where),
        max_llm_calls=_positive_int(table, "max_llm_calls", where),
        acceptance_evidence_types=frozenset(_strings(table, "acceptance_evidence_types", where)),
        acceptance_approvers=frozenset(_strings(table, "acceptance_approvers", where)),
        max_impact=frozenset(_strings(table, "max_impact", where)),
    )


def _text(table: dict, key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApprovalPolicyError(f"{where}: {key} must be a non-empty string")
    return value


def _strings(table: dict, key: str, where: str) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, list) or not value:
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
    if not isinstance(target, str) or target not in grant.target_repositories:
        return TARGET_REPOSITORY_NOT_PERMITTED
    return None


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
    """EXACTLY the declared reach, never a subset.

    A subset test would withhold the objection from a package declaring nothing, which is
    the reading `reach: []` should never get; and adding a member to a reach set can only
    make work touch MORE, so "at most what was granted" is the only safe direction and
    equality is the cheapest way to say it.
    """
    reach = package.get("reach")
    if not isinstance(reach, list) or list(reach) != list(grant.reach):
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

    A null budget is refused rather than read as "the default": the profile default is
    four LLM calls, which is under a tenth of the smallest burn measured here, and a
    revision that declares nothing would take it silently.
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
