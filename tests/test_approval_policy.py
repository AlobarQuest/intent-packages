"""The approval-by-conformance policy (ADR-0028) and the approver arm it opens.

WHAT THESE TESTS ARE ACTUALLY DEFENDING. ADR-0028 relaxes a human gate, and the whole of
its caution is that the relaxation must be a POLICY -- narrow, versioned, and raisable by
one clause -- rather than a removal. So the cases below are mostly REFUSALS: each one
pins a way the grant could silently widen. A test that only proved a conformant revision
is approved would pass just as happily against a policy that approves everything.

Every case here names the mutation it exists to kill, because a guard read is not a guard
tested; the mutation set and its attribution are in the build report.
"""

from __future__ import annotations

import pathlib

import pytest

from intent_packages.approval_policy import (
    ApprovalPolicyError,
    default_policy_path,
    is_policy_approver,
    load_policy,
)
from intent_packages.profiles import PROFILES
from intent_packages.profiles.dependency_update import PinSite, build_envelope

CONFORMANT = {
    "profile": "dependency-update",
    "profile_fields": {
        "target_repo": "AlobarQuest/infraops-mcp-server",
        "package": "zod",
        "from_version": "3.25.76",
        "to_version": "4.4.3",
        "standing": True,
    },
    "reach": ["source_repository"],
    "authority": {
        "allowed": ["repository_read", "repository_write", "test_execution"],
        "requires_approval": ["merge_to_main"],
        "prohibited": ["secret_write"],
        "budgets": {"max_attempts": 3, "max_llm_calls": 120},
    },
    "acceptance": [{"evidence_type": "automated_check", "approver": "policy"}],
    "risk": {"max_impact": "low"},
}


def _package(**overrides):
    """A conformant package with one thing changed, deep-copied so cases cannot leak."""
    import copy

    package = copy.deepcopy(CONFORMANT)
    for path, value in overrides.items():
        keys = path.split(".")
        target = package
        for key in keys[:-1]:
            target = target[key]
        if value is _ABSENT:
            target.pop(keys[-1], None)
        else:
            target[keys[-1]] = value
    return package


_ABSENT = object()


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def test_the_shipped_artifact_loads_and_covers_every_registered_profile(policy) -> None:
    assert set(policy.grants) == set(PROFILES)
    assert policy.version == 1


def test_a_conformant_revision_draws_no_objection(policy) -> None:
    """The one positive case. It is here so the refusals below mean something --
    a policy that refused everything would pass every other test in this file."""
    assert policy.refusals_for(CONFORMANT) == ()


def test_the_approver_string_carries_the_policy_version(policy) -> None:
    assert policy.approver_for("dependency-update") == "policy:dependency-update@v1"


# --- what the grant refuses -------------------------------------------------------


def test_another_repository_is_refused(policy) -> None:
    """Kills: dropping `_target_refusal`. The grant is one repository by decision."""
    package = _package(**{"profile_fields.target_repo": "AlobarQuest/orchestrator"})
    assert policy.refusals_for(package) == ("target_repository_not_permitted",)


def test_an_unfilled_shell_is_refused(policy) -> None:
    """Kills: dropping `_bump_refusal`.

    THE INTERLOCK. A standing package is authored with the same placeholder in both
    version fields, so this is what stops it being approved into a revision that
    describes no bump.
    """
    package = _package(
        **{"profile_fields.from_version": "unassigned", "profile_fields.to_version": "unassigned"}
    )
    assert policy.refusals_for(package) == ("bump_versions_not_distinct",)


def test_a_package_that_is_not_declared_standing_is_refused(policy) -> None:
    """Kills: dropping `_standing_refusal`.

    The historical population is the subject: eight dependency-update packages in the
    authoring repository each name one finished bump, declare this same profile, and would
    otherwise satisfy every other clause for their own target repository.
    """
    package = _package(**{"profile_fields.standing": _ABSENT})
    assert policy.refusals_for(package) == ("not_a_standing_package",)


def test_standing_declared_false_is_refused(policy) -> None:
    package = _package(**{"profile_fields.standing": False})
    assert policy.refusals_for(package) == ("not_a_standing_package",)


def test_an_empty_reach_is_refused(policy) -> None:
    """Kills: `_reach_refusal` weakened from equality to a subset test.

    A subset test passes an empty reach, which is the reading `reach: []` must never
    get -- and it is the case that discriminates, because a reach with an EXTRA member
    refuses under both readings.
    """
    assert policy.refusals_for(_package(reach=[])) == ("reach_not_permitted",)


def test_a_wider_reach_is_refused(policy) -> None:
    package = _package(reach=["source_repository", "live_estate"])
    assert policy.refusals_for(package) == ("reach_not_permitted",)


def test_an_extra_authority_term_is_refused(policy) -> None:
    """Kills: `_authority_refusal` weakened from equality to "the granted terms are
    present". This is the field that stops a policy approval widening what work may do."""
    package = _package(
        **{
            "authority.allowed": [
                "repository_read",
                "repository_write",
                "test_execution",
                "secret_read",
            ]
        }
    )
    assert policy.refusals_for(package) == ("authority_terms_not_permitted",)


def test_a_missing_authority_term_is_refused(policy) -> None:
    package = _package(**{"authority.prohibited": []})
    assert policy.refusals_for(package) == ("authority_terms_not_permitted",)


def test_a_budget_above_the_ceiling_is_refused(policy) -> None:
    """Kills: dropping or loosening the ceiling comparison in `_budget_refusal`."""
    package = _package(**{"authority.budgets": {"max_attempts": 3, "max_llm_calls": 121}})
    assert policy.refusals_for(package) == ("budget_above_ceiling",)


def test_a_budget_below_the_ceiling_is_permitted(policy) -> None:
    package = _package(**{"authority.budgets": {"max_attempts": 1, "max_llm_calls": 4}})
    assert policy.refusals_for(package) == ()


def test_an_absent_budget_is_refused(policy) -> None:
    """Kills: `_budget_refusal` reading an absent budget as "the default".

    The profile default is four LLM calls, under a tenth of the smallest burn measured
    here, so a revision declaring nothing would take a fatal ceiling silently.
    """
    package = _package(**{"authority.budgets": _ABSENT})
    assert policy.refusals_for(package) == ("budget_above_ceiling",)


def test_a_human_judgment_criterion_is_refused(policy) -> None:
    """Kills: widening `acceptance_evidence_types`.

    `factory create` scaffolds exactly this criterion, so without the refusal a lane
    package that was scaffolded rather than authored acquires a fourth human gate that
    nobody chose -- and is disqualified from the autonomous landing lane by it.
    """
    package = _package(
        acceptance=[
            {"evidence_type": "automated_check", "approver": "policy"},
            {"evidence_type": "human_review", "approver": "devon"},
        ]
    )
    assert policy.refusals_for(package) == ("acceptance_not_permitted",)


def test_a_human_judgment_criterion_is_refused_on_its_TYPE_alone(policy) -> None:
    """Kills: widening `acceptance_evidence_types` -- and NOTHING ELSE DOES.

    The scaffolded criterion carries `approver: devon` as well as
    `evidence_type: human_review`, so the obvious case above is killed by the APPROVER
    arm and leaves the type arm unpinned. Measured: a mutation deleting the type check
    survived that test. This one holds the approver at a permitted value so only the type
    can refuse it -- the twin below does the same for the approver.
    """
    package = _package(acceptance=[{"evidence_type": "human_review", "approver": "policy"}])
    assert policy.refusals_for(package) == ("acceptance_not_permitted",)


def test_an_unpermitted_approver_is_refused_on_its_APPROVER_alone(policy) -> None:
    package = _package(acceptance=[{"evidence_type": "automated_check", "approver": "devon"}])
    assert policy.refusals_for(package) == ("acceptance_not_permitted",)


def test_no_acceptance_criteria_is_refused(policy) -> None:
    assert policy.refusals_for(_package(acceptance=[])) == ("acceptance_not_permitted",)


def test_a_higher_impact_is_refused(policy) -> None:
    """Kills: dropping `_impact_refusal`."""
    package = _package(**{"risk.max_impact": "high"})
    assert policy.refusals_for(package) == ("max_impact_not_permitted",)


def test_every_refusal_is_reported_not_just_the_first(policy) -> None:
    """A caller fixing one objection should not discover the next one on the next run."""
    package = _package(
        **{"profile_fields.target_repo": "AlobarQuest/orchestrator", "risk.max_impact": "high"}
    )
    assert policy.refusals_for(package) == (
        "target_repository_not_permitted",
        "max_impact_not_permitted",
    )


# --- what has no grant at all -----------------------------------------------------


@pytest.mark.parametrize(
    "profile",
    sorted(set(PROFILES) - {"dependency-update"}),
)
def test_every_other_profile_has_no_policy_grant(policy, profile) -> None:
    """Kills: `refusals_for` returning () for a profile whose row declares no grant.

    Parametrized over the registry rather than listing four names, so a profile added
    with a grant nobody meant to give reddens here.
    """
    assert policy.refusals_for(_package(profile=profile)) == ("profile_not_policy_approvable",)


def test_an_undeclared_profile_is_refused(policy) -> None:
    assert policy.refusals_for(_package(profile=_ABSENT)) == ("profile_undeclared",)


def test_an_unregistered_profile_is_refused(policy) -> None:
    assert policy.refusals_for(_package(profile="invented")) == ("profile_unrecognised",)


# --- the document itself ----------------------------------------------------------


def _write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    artifact = tmp_path / "approval-policy.toml"
    artifact.write_text(text, encoding="utf-8")
    return artifact


_GRANT = """[profile.dependency-update.grant]
rationale = "r"
decided = "2026-08-19"
target_repositories = ["AlobarQuest/infraops-mcp-server"]
reach = ["source_repository"]
authority_allowed = ["repository_read"]
authority_requires_approval = ["merge_to_main"]
authority_prohibited = ["secret_write"]
max_attempts = 3
max_llm_calls = 120
acceptance_evidence_types = ["automated_check"]
acceptance_approvers = ["policy"]
max_impact = ["low"]
"""


def _rows(*, omit: str = "") -> str:
    return "\n".join(
        f'[profile."{name}"]\nrationale = "r"\ndecided = "2026-08-19"\n'
        for name in sorted(PROFILES)
        if name != omit
    )


def test_a_profile_with_no_row_stops_the_document_loading(tmp_path) -> None:
    """Kills: total coverage weakened to "every row names a known profile".

    A profile shipped without a row must not fall through to something permissive.
    """
    artifact = _write(tmp_path, "version = 1\n" + _rows(omit="dependency-update"))
    with pytest.raises(ApprovalPolicyError, match="exactly one row per registered profile"):
        load_policy(artifact)


def test_a_row_for_an_unknown_profile_stops_the_document_loading(tmp_path) -> None:
    text = "version = 1\n" + _rows() + '\n[profile.invented]\nrationale = "r"\ndecided = "d"\n'
    with pytest.raises(ApprovalPolicyError, match="exactly one row per registered profile"):
        load_policy(_write(tmp_path, text))


def test_an_unknown_schema_version_is_refused(tmp_path) -> None:
    """Kills: accepting any version. An older process meeting a newer document would
    silently ignore whatever narrowing that version introduced."""
    with pytest.raises(ApprovalPolicyError, match="schema version 2"):
        load_policy(_write(tmp_path, "version = 2\n" + _rows()))


def test_an_unreadable_document_raises_rather_than_yielding_an_empty_policy(tmp_path) -> None:
    with pytest.raises(ApprovalPolicyError, match="unreadable"):
        load_policy(tmp_path / "absent.toml")


def test_a_malformed_document_raises(tmp_path) -> None:
    with pytest.raises(ApprovalPolicyError, match="malformed"):
        load_policy(_write(tmp_path, "version = ["))


def test_an_unknown_grant_field_stops_the_document_loading(tmp_path) -> None:
    """The editing contract: a new field lands with the code that reads it, never before."""
    text = (
        "version = 1\n"
        + _rows(omit="dependency-update")
        + '\n[profile.dependency-update]\nrationale = "r"\ndecided = "d"\n'
        + _GRANT
        + "invented = 1\n"
    )
    with pytest.raises(ApprovalPolicyError, match="unknown fields"):
        load_policy(_write(tmp_path, text))


def test_a_grant_missing_a_field_stops_the_document_loading(tmp_path) -> None:
    text = (
        "version = 1\n"
        + _rows(omit="dependency-update")
        + '\n[profile.dependency-update]\nrationale = "r"\ndecided = "d"\n'
        + _GRANT.replace("max_llm_calls = 120\n", "")
    )
    with pytest.raises(ApprovalPolicyError, match=r"missing \['max_llm_calls'\]"):
        load_policy(_write(tmp_path, text))


def test_the_shipped_artifact_is_the_one_the_default_path_names() -> None:
    assert default_policy_path().name == "approval-policy.toml"
    assert default_policy_path().is_file()


# --- the approver shape -----------------------------------------------------------


@pytest.mark.parametrize(
    "approver",
    ["policy:dependency-update@v1", "policy:x@v12"],
)
def test_a_policy_approver_is_recognised(approver) -> None:
    assert is_policy_approver(approver)


@pytest.mark.parametrize(
    "approver",
    [
        "devon",
        "claude-code-interactive",
        "policy",
        "policy:X@v1",
        "policy:a@v0",
        "policy:a@v1 ",
        " policy:a@v1",
        "xpolicy:a@v1",
        "policy:a@v1x",
        "",
        None,
        1,
    ],
)
def test_anything_else_is_not_a_policy_approver(approver) -> None:
    """Kills: unanchoring the pattern, or accepting a non-string.

    An unanchored match would read a policy approver out of the middle of any string,
    which is how a lineage entry naming nothing in particular becomes a recognised one.
    """
    assert not is_policy_approver(approver)


def test_the_envelope_budget_the_profile_stamps_equals_the_policy_ceiling(tmp_path):
    """A package declared 120 while the unit envelope derived from it declared 4.

    `build_envelope` stamps `profiles.dependency_update.BUDGETS`; this policy grants a
    CEILING. Until 2026-08-19 nothing compared them, so every unit this lane produced
    carried a thirtieth of the budget its own package had been approved for. A lower
    default is not a safety margin: `budget_exceeded` is curable by nothing, the
    envelope is write-once, and its approval cannot be taken back. Equal, not merely
    ordered -- an assertion that the default is <= the ceiling passes against the
    defect it exists to catch.
    """
    grant = load_policy().grants["dependency-update"]
    assert grant is not None
    (tmp_path / "requirements.txt").write_text("fastapi==0.139.0\n", encoding="utf-8")
    envelope = build_envelope(
        "AlobarQuest/infraops-mcp-server",
        "pip",
        "fastapi",
        "0.139.0",
        "0.139.2",
        {"accepted_standards": [], "standards_touched": ["project"], "status": "green"},
        [PinSite("requirements.txt", "requirements.txt", "0.139.0")],
        repo=tmp_path,
    )
    assert envelope["budgets"] == {
        "max_attempts": grant.max_attempts,
        "max_llm_calls": grant.max_llm_calls,
    }
