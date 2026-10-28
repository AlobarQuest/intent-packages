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
        "allowed": ["repository_read", "repository_write", "test_execution", "merge_to_main"],
        "requires_approval": [],
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


@pytest.fixture(autouse=True)
def _infraops_is_granted(member_record):
    """The member double: infraops-mcp-server holds the `dependency_updates` grant."""
    member_record("AlobarQuest/infraops-mcp-server")


def test_the_shipped_artifact_loads_and_covers_every_registered_profile(policy) -> None:
    assert set(policy.grants) == set(PROFILES)
    assert policy.version == 3


def test_a_conformant_revision_draws_no_objection(policy) -> None:
    """The one positive case. It is here so the refusals below mean something --
    a policy that refused everything would pass every other test in this file."""
    assert policy.refusals_for(CONFORMANT) == ()


def test_approver_is_v3(policy) -> None:
    """Kills: the approver string reading a stale version. Approvals already recorded at @v2
    stay recognised, because `is_policy_approver` matches any version."""
    assert policy.approver_for("dependency-update") == "policy:dependency-update@v3"
    assert is_policy_approver("policy:dependency-update@v2")


# --- what the grant refuses -------------------------------------------------------


def test_another_repository_is_refused(policy) -> None:
    """Kills: dropping `_target_refusal`. The grant is the member record's, not any repository."""
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


def test_a_revision_that_still_asks_approval_for_the_merge_is_refused(policy) -> None:
    """Kills: the grant keeping `merge_to_main` in `authority_requires_approval`. The grant
    puts the merge in `allowed`; a revision that moves it back no longer matches."""
    package = _package(
        **{
            "authority.allowed": ["repository_read", "repository_write", "test_execution"],
            "authority.requires_approval": ["merge_to_main"],
        }
    )
    assert policy.refusals_for(package) == ("authority_terms_not_permitted",)


def test_the_shipped_grant_allows_the_merge_and_asks_for_no_approval(policy) -> None:
    grant = policy.grants["dependency-update"]
    assert grant is not None
    assert "merge_to_main" in grant.authority_allowed
    assert grant.authority_requires_approval == ()


def test_only_requires_approval_may_be_an_empty_grant_list(tmp_path) -> None:
    """Kills: relaxing `_strings` for every list. An empty allowed list would read as
    "nothing permitted", so it still stops the document loading."""
    grant = _GRANT.replace(
        'authority_allowed = ["repository_read", "merge_to_main"]', "authority_allowed = []"
    )
    text = (
        "version = 1\n"
        + _rows(omit="dependency-update")
        + '\n[profile.dependency-update]\nrationale = "r"\ndecided = "d"\n'
        + grant
    )
    with pytest.raises(ApprovalPolicyError, match="authority_allowed must be a non-empty list"):
        load_policy(_write(tmp_path, text))


def test_a_missing_authority_term_is_refused(policy) -> None:
    package = _package(**{"authority.prohibited": []})
    assert policy.refusals_for(package) == ("authority_terms_not_permitted",)


def test_a_budget_above_the_ceiling_is_refused(policy) -> None:
    """Kills: dropping or loosening the ceiling comparison in `_budget_refusal`.

    The over-ceiling value is DERIVED rather than written, because this test's subject is the
    COMPARISON and not the number. It was the literal 121 until 2026-09-03; raising the ceiling
    to 240 left it quietly under the bar, so it asserted a refusal that no longer applied and
    reddened for a reason unrelated to what it guards. The ceiling's VALUE is pinned elsewhere,
    by `test_the_envelope_budget_the_profile_stamps_equals_the_policy_ceiling` against the
    profile constant the envelope is actually stamped from.
    """
    grant = policy.grants["dependency-update"]
    assert grant is not None
    over = grant.max_llm_calls + 1
    package = _package(**{"authority.budgets": {"max_attempts": 3, "max_llm_calls": over}})
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
authority_allowed = ["repository_read", "merge_to_main"]
authority_requires_approval = []
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
    with pytest.raises(ApprovalPolicyError, match="schema version 4"):
        load_policy(_write(tmp_path, "version = 4\n" + _rows()))


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


_GRANT_V2 = _GRANT.replace(
    'target_repositories = ["AlobarQuest/infraops-mcp-server"]',
    'targets_from = "sds-member-record:dependency_updates"',
)


def _document(version: int, grant: str) -> str:
    return (
        f"version = {version}\n"
        + _rows(omit="dependency-update")
        + '\n[profile.dependency-update]\nrationale = "r"\ndecided = "d"\n'
        + grant
    )


def test_schema_1_grants_still_load(tmp_path) -> None:
    """Kills: schema 2 replacing schema 1 outright. A schema-1 document keeps its fixed list
    and never consults the member record."""
    loaded = load_policy(_write(tmp_path, _document(1, _GRANT)))
    grant = loaded.grants["dependency-update"]
    assert grant is not None
    assert grant.target_repositories == {"AlobarQuest/infraops-mcp-server"}
    assert grant.target_service is None
    assert loaded.approver_for("dependency-update") == "policy:dependency-update@v1"


def test_a_schema_1_grant_does_not_consult_the_member_record(tmp_path, member_record) -> None:
    member_record()  # an empty record: nothing is granted there
    loaded = load_policy(_write(tmp_path, _document(1, _GRANT)))
    assert "target_repository_not_permitted" not in loaded.refusals_for(CONFORMANT)


def test_a_schema_2_grant_names_its_service(tmp_path) -> None:
    grant = load_policy(_write(tmp_path, _document(2, _GRANT_V2))).grants["dependency-update"]
    assert grant is not None
    assert grant.target_service == "dependency_updates"
    assert grant.target_repositories == frozenset()


@pytest.mark.parametrize(
    ("version", "grant", "message"),
    [
        (2, _GRANT, r"missing \['targets_from'\]"),
        (1, _GRANT_V2, r"missing \['target_repositories'\]"),
        (2, _GRANT_V2 + 'target_repositories = ["a/b"]\n', "unknown fields"),
        (2, _GRANT_V2.replace("sds-member-record:", "elsewhere:"), "targets_from must be"),
        (
            2,
            _GRANT_V2.replace("sds-member-record:dependency_updates", "sds-member-record:"),
            "targets_from must be",
        ),
    ],
)
def test_each_schema_has_exactly_one_target_source(tmp_path, version, grant, message) -> None:
    with pytest.raises(ApprovalPolicyError, match=message):
        load_policy(_write(tmp_path, _document(version, grant)))


_GRANT_V3 = _GRANT_V2.replace(
    'reach = ["source_repository"]',
    'reach_options = [["source_repository"], ["live_estate"]]',
)


def test_schema_2_document_still_loads(tmp_path) -> None:
    """Kills: schema 3 replacing schema 2 outright. Its single `reach` loads as one option."""
    loaded = load_policy(_write(tmp_path, _document(2, _GRANT_V2)))
    grant = loaded.grants["dependency-update"]
    assert grant is not None
    assert grant.reach_options == (("source_repository",),)
    assert loaded.approver_for("dependency-update") == "policy:dependency-update@v2"


def test_schema_3_rejects_reach_field(tmp_path) -> None:
    """Kills: schema 3 accepting both reach fields, which would leave two sources of truth."""
    with pytest.raises(ApprovalPolicyError, match="unknown fields"):
        load_policy(_write(tmp_path, _document(3, _GRANT_V3 + 'reach = ["source_repository"]\n')))


def test_schema_2_rejects_reach_options(tmp_path) -> None:
    with pytest.raises(ApprovalPolicyError, match="unknown fields"):
        load_policy(
            _write(tmp_path, _document(2, _GRANT_V2 + 'reach_options = [["live_estate"]]\n'))
        )


def test_schema_3_requires_reach_options(tmp_path) -> None:
    with pytest.raises(ApprovalPolicyError, match=r"missing \['reach_options'\]"):
        load_policy(_write(tmp_path, _document(3, _GRANT_V2)))


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ("[]", "must be a non-empty list"),
        ('["live_estate"]', r"option 'live_estate' must be a non-empty list of strings"),
        ("[[]]", r"option \[\] must be a non-empty list of strings"),
        ('[["live_estate", "live_estate"]]', r"option \['live_estate', 'live_estate'\] repeats"),
    ],
)
def test_schema_3_refuses_malformed_reach_options(tmp_path, options, message) -> None:
    """Kills: dropping the per-option shape or duplicate check; the error names the option."""
    grant = _GRANT_V3.replace(
        'reach_options = [["source_repository"], ["live_estate"]]', f"reach_options = {options}"
    )
    with pytest.raises(ApprovalPolicyError, match=message):
        load_policy(_write(tmp_path, _document(3, grant)))


def test_schema_3_accepts_each_option(policy) -> None:
    """Kills: `_reach_refusal` comparing only against the first option."""
    for option in (["source_repository"], ["live_estate"]):
        assert policy.refusals_for(_package(reach=option)) == ()


@pytest.mark.parametrize(
    "reach",
    [[], ["source_repository", "live_estate"], ["live_estate", "source_repository"],
     ["external_system"], _ABSENT],
)  # fmt: skip
def test_schema_3_refuses_other_reaches(policy, reach) -> None:
    """Kills: equality weakened to a subset or union test over the options."""
    assert policy.refusals_for(_package(reach=reach)) == ("reach_not_permitted",)


def test_the_shipped_grant_takes_its_targets_from_the_member_record(policy) -> None:
    grant = policy.grants["dependency-update"]
    assert grant is not None
    assert (grant.target_service, grant.target_repositories) == ("dependency_updates", frozenset())


def test_the_shipped_artifact_is_the_one_the_default_path_names() -> None:
    assert default_policy_path().name == "approval-policy.toml"
    assert default_policy_path().is_file()


# --- the member record is the scope -------------------------------------------------


def test_a_granted_target_is_approved(policy, member_record) -> None:
    member_record("AlobarQuest/example-app")
    package = _package(**{"profile_fields.target_repo": "AlobarQuest/example-app"})
    assert policy.refusals_for(package) == ()


def test_an_ungranted_target_is_refused(policy, member_record) -> None:
    """Kills: the target check reading a list instead of the record. infraops-mcp-server is
    named nowhere in the record this test installs."""
    member_record("AlobarQuest/example-app")
    assert policy.refusals_for(CONFORMANT) == ("target_repository_not_permitted",)


def test_the_target_check_folds_case(policy, member_record) -> None:
    """Kills: case-sensitive membership. GitHub repository names are case-insensitive."""
    member_record("alobarquest/INFRAOPS-mcp-server")
    assert policy.refusals_for(CONFORMANT) == ()


def test_an_unreadable_member_record_refuses(policy, monkeypatch) -> None:
    """Kills: treating an unreadable record as an empty or a permissive one. The cause is
    named, the revision is not approved."""
    from intent_packages import approval_policy
    from intent_packages.members import MembersUnreadable

    def unreadable(service):
        raise MembersUnreadable("the member record answered HTTP 503")

    monkeypatch.setattr(approval_policy, "granted_targets", unreadable)
    (refusal,) = policy.refusals_for(CONFORMANT)
    assert refusal == "member_record_unreadable: the member record answered HTTP 503"


def test_a_retired_member_is_refused(policy, member_record) -> None:
    """A retired member is dropped by the reader (tests/test_members.py), so it is absent from
    the granted set the policy consults."""
    member_record()
    assert policy.refusals_for(CONFORMANT) == ("target_repository_not_permitted",)


def test_the_record_is_not_consulted_for_a_package_that_names_no_target(
    policy, monkeypatch
) -> None:
    from intent_packages import approval_policy

    def must_not_be_called(service):
        raise AssertionError("the member record was read")

    monkeypatch.setattr(approval_policy, "granted_targets", must_not_be_called)
    package = _package(**{"profile_fields.target_repo": _ABSENT})
    assert policy.refusals_for(package) == ("target_repository_not_permitted",)


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
