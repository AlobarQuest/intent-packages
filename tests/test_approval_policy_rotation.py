"""The rotation grant (approval-policy.toml schemas 4 and 5, orchestrator ADR-0055 amendments 22
and 39).

It lets the policy approver `policy:non-software-operational@v5` approve a lane credential's
proposer-generated revision 1 and, at schema 5, a reissue of an `orchestrator` or
`change-manager` bearer (the reissue sections at the end). Like the dependency-update grant's
tests, these are mostly REFUSALS, one per condition, each changing one thing and asserting the one
refusal it draws: a test that only proved the fixtures pass would pass against a grant that
approves everything.

THE SUBJECTS are copies of the two proposer-generated revision 1 packages on `main` when the
grant shipped (`tests/fixtures/standing_approval/`, from intent-packages 4f57bef and 2191e86),
and the orchestrator's issue-plan fixtures `test_create_rotation` pins. They are copies so that
the live packages' lifecycle can move without moving these tests. The reissue subjects are copies
of the eight packages amendment 39 measured, and the execute bearer, at intent-packages c0cb0a9
(`tests/fixtures/standing_reissue/`), and `approval-policy-schema-4.toml` is the document as it
stood before schema 5.
"""

from __future__ import annotations

import copy
import json
import pathlib
import shutil

import pytest
import yaml

from intent_packages import lineage as ln
from intent_packages.approval_policy import ApprovalPolicyError, RotationGrant, load_policy
from intent_packages.canonical import package_hash
from intent_packages.loader import load_package
from intent_packages.operations import OperationError, do_approve, do_transition

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
STANDING = FIXTURES / "standing_approval"
PING_URL = "rotation-deploy-watcher-ping-url"
LANE_TOKEN = "rotation-revision-watcher-bws-token"
APPROVER = "policy:non-software-operational@v5"
NOW = "2026-11-11T12:00:00Z"


def _shipped(name: str) -> dict:
    return yaml.safe_load((STANDING / name / "package.yaml").read_text(encoding="utf-8"))


def _issue_fixture(type_name: str) -> dict:
    path = FIXTURES / f"rotation_package_issue_{type_name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _lineage(*, revisions=(1,), approvals=()) -> dict:
    """A lineage as `ready_for_review` leaves it: the listed revisions, and the approvals given."""
    return {
        "package_id": "p",
        "current_state": "ready_for_review",
        "revisions": [{"revision": r, "hash": "0" * 64} for r in revisions],
        "transitions": [],
        "approvals": list(approvals),
        "grants": [],
    }


def _ping_url(**changes) -> dict:
    package = copy.deepcopy(_shipped(PING_URL))
    package.update(changes)
    return package


def _lane_token(**changes) -> dict:
    package = copy.deepcopy(_shipped(LANE_TOKEN))
    package.update(changes)
    return package


def _with_destinations(package: dict, destinations: list) -> dict:
    package["profile_fields"]["destinations"] = destinations
    return package


@pytest.fixture(scope="module")
def policy():
    return load_policy()


# --- what passes ------------------------------------------------------------------


@pytest.mark.parametrize("name", [PING_URL, LANE_TOKEN])
def test_each_shipped_revision_1_draws_no_objection(policy, name) -> None:
    """The positive case, on both types the grant names."""
    assert policy.refusals_for(_shipped(name), _lineage()) == ()


@pytest.mark.parametrize("type_name", ["bws-lane-token", "healthchecks-ping-url"])
def test_the_orchestrator_s_issue_render_draws_no_objection(policy, type_name) -> None:
    """The orchestrator's own issue-plan render (pinned by `test_create_rotation`) passes, so
    the grant's sets are `generate.authority`'s for the issue plan and not only these two."""
    assert policy.refusals_for(_issue_fixture(type_name), _lineage()) == ()


# --- one refusal per condition ------------------------------------------------------


@pytest.mark.parametrize("standing", [False, "true", None])
def test_a_package_not_declared_standing_is_refused(policy, standing) -> None:
    package = _ping_url()
    package["profile_fields"]["standing"] = standing
    assert policy.refusals_for(package, _lineage()) == ("not_a_standing_package",)


@pytest.mark.parametrize("revision", [0, True, "1", "2"])
def test_a_revision_other_than_1_is_refused(policy, revision) -> None:
    """Kills: dropping the revision check. `True` is refused by type, because `True == 1`, and
    `"2"` by type, so a string revision never reaches the reissue branch."""
    package = _lane_token(revision=revision)
    assert policy.refusals_for(package, _lineage()) == ("not_revision_one",)


@pytest.mark.parametrize("revisions", [(1, 2), (2,), ()])
def test_a_lineage_listing_anything_but_revision_1_alone_is_refused(policy, revisions) -> None:
    assert policy.refusals_for(_ping_url(), _lineage(revisions=revisions)) == ("not_revision_one",)


def test_a_lineage_with_an_earlier_approval_is_refused(policy) -> None:
    """Kills: dropping the approval check. Revision 1 approved once already is not a first issue
    waiting for its approval, whoever approved it."""
    earlier = {"revision": 1, "approved_hash": "1" * 64, "approver": "devon"}
    lineage = _lineage(approvals=[earlier])
    assert policy.refusals_for(_ping_url(), lineage) == ("lineage_has_approval",)


@pytest.mark.parametrize(
    "lineage",
    [
        None,
        "not a lineage",
        {"revisions": [{"revision": 1}]},
        {"approvals": []},
        {"revisions": "1", "approvals": []},
        {"revisions": [{"revision": 1}], "approvals": None},
    ],
)
def test_a_missing_or_unreadable_lineage_is_refused(policy, lineage) -> None:
    """Kills: reading an absent lineage, or an absent `approvals`, as "no approval"."""
    assert policy.refusals_for(_ping_url(), lineage) == ("lineage_unreadable",)


@pytest.mark.parametrize("created_by", ["claude-code-interactive", "factory-create", None])
def test_a_package_the_proposer_did_not_write_is_refused(policy, created_by) -> None:
    package = _lane_token(created_by=created_by)
    assert policy.refusals_for(package, _lineage()) == ("not_proposer_generated",)


def test_a_third_rotation_type_is_refused(policy) -> None:
    """Kills: a grant that accepts any provider. The ping URL's own shape, naming a type the
    grant doesn't list, refuses on the type alone."""
    package = _ping_url()
    package["profile_fields"]["destinations"][-1] = 'provider name="openrouter"'
    assert policy.refusals_for(package, _lineage()) == ("rotation_type_not_permitted",)


def test_the_orchestrator_s_github_render_is_refused_as_a_third_type(policy) -> None:
    refusals = policy.refusals_for(
        json.loads((FIXTURES / "rotation_package_generated.json").read_text(encoding="utf-8")),
        _lineage(),
    )
    assert "rotation_type_not_permitted" in refusals


@pytest.mark.parametrize(
    "destinations",
    [
        ['bws-secret uuid="11111111-1111-4111-8111-111111111111"'],
        [
            'bws-secret uuid="11111111-1111-4111-8111-111111111111"',
            'provider name="healthchecks-ping-url"',
            'provider name="bws-lane-token"',
        ],
        ['bws-secret uuid="11111111-1111-4111-8111-111111111111"', "provider name=healthchecks"],
    ],
    ids=["no-provider", "two-providers", "malformed-provider"],
)
def test_no_single_readable_provider_is_refused(policy, destinations) -> None:
    package = _with_destinations(_ping_url(), destinations)
    assert policy.refusals_for(package, _lineage()) == ("rotation_type_not_permitted",)


_KEEPER = 'bws-secret uuid="11111111-1111-4111-8111-111111111111"'
_SECOND_KEEPER = 'bws-secret uuid="22222222-2222-4222-8222-222222222222"'
_LANE_ENV = (
    'coolify-env instance="prod" resource_type="service" uuid="lanesvc0000000000000000" '
    'key="EXAMPLE_BWS_ACCESS_TOKEN" redeploy={redeploy}'
)
_LANE_PROVIDER = 'provider name="bws-lane-token"'
_PING_PROVIDER = 'provider name="healthchecks-ping-url"'


@pytest.mark.parametrize(
    ("make", "destinations"),
    [
        (_lane_token, [_KEEPER, _LANE_ENV.format(redeploy="true"), _LANE_PROVIDER]),
        (_lane_token, [_KEEPER, _LANE_PROVIDER]),
        (
            _lane_token,
            [_KEEPER, _SECOND_KEEPER, _LANE_ENV.format(redeploy="false"), _LANE_PROVIDER],
        ),
        (_lane_token, ['gh-actions-secret repo="AlobarQuest/x" name="T"', _KEEPER, _LANE_PROVIDER]),
        (_ping_url, [_KEEPER, _LANE_ENV.format(redeploy="false"), _PING_PROVIDER]),
        (_ping_url, [_KEEPER, _SECOND_KEEPER, _PING_PROVIDER]),
        (_ping_url, [_PING_PROVIDER]),
        (_ping_url, ['bws-secret uuid=" padded "', _PING_PROVIDER]),
    ],
    ids=[
        "lane-redeploys",
        "lane-without-its-coolify-copy",
        "lane-second-keeper",
        "lane-another-kind",
        "ping-with-a-coolify-copy",
        "ping-second-keeper",
        "ping-without-a-keeper",
        "ping-malformed-keeper",
    ],
)
def test_destinations_not_of_the_type_s_kinds_are_refused(policy, make, destinations) -> None:
    """Kills: dropping or loosening the kinds check -- a redeploying copy, a missing copy, a
    second keeper, and a kind the type doesn't have each refuse alone."""
    package = _with_destinations(make(), destinations)
    assert policy.refusals_for(package, _lineage()) == ("destinations_not_permitted",)


def _move(package: dict, term: str, *, into: str, out_of: str) -> dict:
    authority = package["authority"]
    authority[out_of].remove(term)
    authority[into].append(term)
    return package


@pytest.mark.parametrize(
    "mutate",
    [
        lambda: _move(_ping_url(), "infra_mutation", into="allowed", out_of="prohibited"),
        lambda: _move(_ping_url(), "credential_create", into="allowed", out_of="prohibited"),
        lambda: _move(_lane_token(), "infra_mutation", into="prohibited", out_of="allowed"),
        lambda: _move(
            _lane_token(), "credential_revoke", into="requires_approval", out_of="prohibited"
        ),
    ],
    ids=[
        "ping+infra_mutation",
        "ping+credential_create",
        "lane-infra_mutation",
        "lane-asks-revoke",
    ],
)
def test_an_authority_one_capability_away_is_refused(policy, mutate) -> None:
    """Kills: comparing as a subset, or comparing one list. One capability moved refuses."""
    assert policy.refusals_for(mutate(), _lineage()) == ("authority_terms_not_permitted",)


def test_an_authority_missing_a_prohibition_is_refused(policy) -> None:
    package = _ping_url()
    package["authority"]["prohibited"].remove("email_send")
    assert policy.refusals_for(package, _lineage()) == ("authority_terms_not_permitted",)


def test_the_other_type_s_authority_is_refused(policy) -> None:
    """Each type's sets are its own: the lane token's set doesn't cover a ping URL."""
    package = _ping_url()
    package["authority"] = copy.deepcopy(_shipped(LANE_TOKEN)["authority"])
    assert policy.refusals_for(package, _lineage()) == ("authority_terms_not_permitted",)


@pytest.mark.parametrize(
    "budgets",
    [
        {"max_attempts": 4, "max_llm_calls": None},
        {"max_attempts": 2, "max_llm_calls": None},
        {"max_attempts": True, "max_llm_calls": None},
        {"max_attempts": 3, "max_llm_calls": 120},
        {"max_attempts": 3},
        None,
    ],
)
def test_budgets_other_than_the_standard_are_refused(policy, budgets) -> None:
    """Compared whole, not as a ceiling: the standard is three attempts and no LLM budget."""
    package = _lane_token()
    package["authority"]["budgets"] = budgets
    assert policy.refusals_for(package, _lineage()) == ("authority_terms_not_permitted",)


def test_a_human_review_criterion_is_refused(policy) -> None:
    package = _ping_url()
    package["acceptance"].append(
        {
            "id": "AC-006",
            "condition": "Devon confirms it.",
            "evidence_type": "human_review",
            "evidence": "human: Devon signs off",
            "approver": "devon",
        }
    )
    assert policy.refusals_for(package, _lineage()) == ("acceptance_not_permitted",)


@pytest.mark.parametrize("acceptance", [[], None, ["AC-001"]])
def test_no_readable_criteria_is_refused(policy, acceptance) -> None:
    package = _ping_url(acceptance=acceptance)
    assert policy.refusals_for(package, _lineage()) == ("acceptance_not_permitted",)


def test_every_refusal_is_reported_not_just_the_first(policy) -> None:
    package = _lane_token(revision=0, created_by="someone")
    package["profile_fields"]["standing"] = False
    package["authority"]["budgets"]["max_attempts"] = 9
    package["profile_fields"]["destinations"] = [_KEEPER, _LANE_PROVIDER]
    package["acceptance"][0]["evidence_type"] = "human_review"
    lineage = _lineage(approvals=[{"revision": 1, "approved_hash": "1" * 64, "approver": "devon"}])
    assert policy.refusals_for(package, lineage) == (
        "not_a_standing_package",
        "not_revision_one",
        "lineage_has_approval",
        "not_proposer_generated",
        "destinations_not_permitted",
        "authority_terms_not_permitted",
        "acceptance_not_permitted",
    )


# --- the grant as written ---------------------------------------------------------------


def test_the_shipped_grant_is_the_rotation_grant(policy) -> None:
    grant = policy.grants["non-software-operational"]
    assert isinstance(grant, RotationGrant)
    assert grant.created_by == "rotation-proposer"
    assert grant.decided == "2026-11-28"
    assert sorted(grant.types) == ["bws-lane-token", "healthchecks-ping-url"]
    assert sorted(grant.reissue_types) == ["change-manager", "orchestrator"]


# --- loading ----------------------------------------------------------------------------

_ROTATION_GRANT = """
[profile.non-software-operational.grant]
rationale = "r"
decided = "2026-11-10"
created_by = "rotation-proposer"

[profile.non-software-operational.grant.types.healthchecks-ping-url]
destinations = [{{ kind = "bws-secret" }}, {{ kind = "provider" }}{extra_destination}]
authority_options = [
  {{ allowed = ["secret_read"], requires_approval = [], prohibited = ["email_send"], \
max_attempts = 3{extra_authority} }},
]
"""


def _document(version: int, *, profile: str = "non-software-operational", **parts) -> str:
    from intent_packages.profiles import PROFILES

    rows = "\n".join(
        f'[profile."{name}"]\nrationale = "r"\ndecided = "2026-08-19"\n'
        for name in sorted(PROFILES)
    )
    grant = _ROTATION_GRANT.format(
        extra_destination=parts.get("extra_destination", ""),
        extra_authority=parts.get("extra_authority", ""),
    ).replace("profile.non-software-operational.grant", f'profile."{profile}".grant')
    return f"version = {version}\n{rows}\n{grant}"


def _load(tmp_path: pathlib.Path, text: str):
    artifact = tmp_path / "approval-policy.toml"
    artifact.write_text(text, encoding="utf-8")
    return load_policy(artifact)


def test_a_rotation_grant_loads_at_schema_4(tmp_path) -> None:
    grant = _load(tmp_path, _document(4)).grants["non-software-operational"]
    assert isinstance(grant, RotationGrant)
    assert sorted(grant.types) == ["healthchecks-ping-url"]


@pytest.mark.parametrize("version", [1, 2, 3])
def test_a_rotation_grant_before_schema_4_stops_the_document_loading(tmp_path, version) -> None:
    """Kills: an older document acquiring the grant. Before schema 4 every grant is the
    dependency-update shape, which a rotation grant doesn't have."""
    with pytest.raises(ApprovalPolicyError, match="grant: missing"):
        _load(tmp_path, _document(version))


_SCHEMA_3_GRANT_FIELDS = """targets_from = "sds-member-record:dependency_updates"
reach_options = [["external_system"]]
authority_allowed = ["secret_read"]
authority_requires_approval = []
authority_prohibited = ["email_send"]
max_attempts = 3
max_llm_calls = 10
acceptance_evidence_types = ["external_attestation"]
acceptance_approvers = ["devon"]
max_impact = ["low"]
"""


def test_types_on_a_complete_schema_3_grant_stops_the_document_loading(tmp_path) -> None:
    """Kills: schema 3 accepting `types` beside a complete grant: it's an unknown field there."""
    text = _document(3).replace('created_by = "rotation-proposer"\n', _SCHEMA_3_GRANT_FIELDS)
    with pytest.raises(ApprovalPolicyError, match=r"unknown fields \['types'\]"):
        _load(tmp_path, text)


def test_a_rotation_grant_on_another_profile_stops_the_document_loading(tmp_path) -> None:
    with pytest.raises(ApprovalPolicyError, match="only non-software-operational"):
        _load(tmp_path, _document(4, profile="software-delivery"))


@pytest.mark.parametrize(
    ("parts", "message"),
    [
        ({"extra_destination": ', { kind = "bws-secret" }'}, "repeat a kind"),
        ({"extra_destination": ', { kind = "nonsense" }'}, "no destination kind"),
        ({"extra_destination": ', { kind = "coolify-env", colour = "red" }'}, "may not pin"),
        ({"extra_authority": ", max_llm_calls = 10"}, "unknown fields"),
        ({"extra_destination": ', { kind = "coolify-env", redeploy = "false" }'}, "wrong type"),
        ({"extra_destination": ', { kind = "coolify-env", key = 7 }'}, "wrong type"),
    ],
)
def test_a_malformed_rotation_grant_stops_the_document_loading(tmp_path, parts, message) -> None:
    with pytest.raises(ApprovalPolicyError, match=message):
        _load(tmp_path, _document(4, **parts))


def test_a_term_in_two_authority_lists_stops_the_document_loading(tmp_path) -> None:
    text = _document(4).replace('prohibited = ["email_send"]', 'prohibited = ["secret_read"]')
    with pytest.raises(ApprovalPolicyError, match="appears twice"):
        _load(tmp_path, text)


def test_a_provider_pattern_may_not_pin_its_name(tmp_path) -> None:
    text = _document(4).replace('{ kind = "provider" }', '{ kind = "provider", name = "x" }')
    with pytest.raises(ApprovalPolicyError, match="provider may not pin"):
        _load(tmp_path, text)


def test_a_type_without_a_provider_pattern_stops_the_document_loading(tmp_path) -> None:
    text = _document(4).replace(', { kind = "provider" }', "")
    with pytest.raises(ApprovalPolicyError, match="must include the provider"):
        _load(tmp_path, text)


# --- through do_approve -------------------------------------------------------------------

_CAPABILITIES = "schema: capability-vocabulary/v1\nterms:\n" + "".join(
    f'  {term}: "{term}"\n'
    for term in (
        "credential_create",
        "credential_revoke",
        "secret_read",
        "secret_write",
        "repository_write",
        "infra_mutation",
        "outward_publish",
        "email_send",
    )
)


class StubEmitter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, action, ref, evidence):
        self.calls.append((action, ref, evidence))
        return f"evt-{len(self.calls)}"


@pytest.fixture
def ready(tmp_path, monkeypatch, fake_registry):
    """A copy of the shipped lane-token package, put in `ready_for_review` from a fresh draft."""
    (fake_registry / "registry" / "capabilities.yaml").write_text(_CAPABILITIES, encoding="utf-8")
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    pkg_dir = tmp_path / LANE_TOKEN
    shutil.copytree(STANDING / LANE_TOKEN, pkg_dir)
    text = (pkg_dir / "package.yaml").read_text(encoding="utf-8")
    (pkg_dir / "package.yaml").write_text(
        text.replace("status: ready_for_review", "status: draft"), encoding="utf-8"
    )
    lineage = {
        "package_id": LANE_TOKEN,
        "current_state": "draft",
        "revisions": [
            {
                "revision": 1,
                "hash": package_hash(load_package(pkg_dir)),
                "created_at": "2026-11-11T14:14:38Z",
                "author": "claude-code-interactive",
            }
        ],
        "transitions": [],
        "approvals": [],
        "grants": [],
    }
    ln.write(pkg_dir, lineage)
    do_transition(pkg_dir, "ready_for_review", emitter=StubEmitter(), now=NOW)
    return pkg_dir


def test_do_approve_takes_the_policy_approval_for_a_lane_credential_s_revision_1(ready) -> None:
    """Kills: `_authorize_approver` not passing the lineage through. Without it the grant
    refuses `lineage_unreadable`, and this approval raises."""
    emitter = StubEmitter()
    do_approve(ready, emitter=emitter, approver=APPROVER, commit="abc1234", now=NOW)

    lineage = ln.read(ready)
    assert lineage["current_state"] == "approved"
    assert [a["approver"] for a in lineage["approvals"]] == [APPROVER]
    assert emitter.calls[0][0] == "package.approved"
    assert emitter.calls[0][2]["approver"] == APPROVER


def test_a_repeated_policy_approval_refuses(ready) -> None:
    """Pins the fail-closed cost: the grant reads ANY approval as an earlier one, so calling
    `approve` again on an approved revision refuses `lineage_has_approval` rather than being
    the no-op a repeated dependency-update approval is. Nothing is written the second time."""
    do_approve(ready, emitter=StubEmitter(), approver=APPROVER, commit="abc1234", now=NOW)
    emitter = StubEmitter()
    with pytest.raises(OperationError, match="lineage_has_approval"):
        do_approve(ready, emitter=emitter, approver=APPROVER, commit="abc1234", now=NOW)
    assert emitter.calls == []
    assert len(ln.read(ready)["approvals"]) == 1


def test_do_approve_still_takes_a_named_human(ready) -> None:
    """The human arm is tried first and untouched by the grant."""
    do_approve(ready, emitter=StubEmitter(), approver="devon", commit="abc1234", now=NOW)
    assert [a["approver"] for a in ln.read(ready)["approvals"]] == ["devon"]


def test_do_approve_refuses_another_policy_version(ready) -> None:
    with pytest.raises(OperationError, match="not the approver this policy grants"):
        do_approve(
            ready,
            emitter=StubEmitter(),
            approver="policy:non-software-operational@v4",
            commit="abc1234",
            now=NOW,
        )


# --- the reissue grant (schema 5) -------------------------------------------------------

REISSUE = FIXTURES / "standing_reissue"
COVERED = [
    "rotation-orchestrator-operator-bearer",
    "rotation-orchestrator-observer-bearer",
    "rotation-orchestrator-drift-reporter-bearer",
    "rotation-change-manager-full-bearer",
    "rotation-change-manager-read-bearer",
    "rotation-change-manager-propose-bearer",
    "rotation-change-manager-observe-bearer",
]
FIRST_HAND_OVERS = [
    "rotation-orchestrator-factory-runner-bearer",
    "rotation-change-manager-execute-bearer",
]
OPERATOR = "rotation-orchestrator-operator-bearer"  # revision 2, revision 1 approved by devon
OBSERVER = "rotation-orchestrator-observer-bearer"  # revision 3, revisions 1 and 2 by devon
CM_FULL = "rotation-change-manager-full-bearer"


def _reissue(name: str) -> tuple[dict, dict]:
    """A fresh read of a fixture's package and lineage."""

    def read(part: str) -> dict:
        return yaml.safe_load((REISSUE / name / f"{part}.yaml").read_text(encoding="utf-8"))

    return read("package"), read("lineage")


def _operator(**changes) -> dict:
    package, _ = _reissue(OPERATOR)
    package.update(changes)
    return package


def _operator_lineage() -> dict:
    return _reissue(OPERATOR)[1]


def _approval(revision: object, approver: object = "devon") -> dict:
    return {"revision": revision, "approved_hash": "1" * 64, "approver": approver}


@pytest.mark.parametrize("name", COVERED)
def test_each_covered_reissue_draws_no_objection(policy, name) -> None:
    """The positive case, on all seven packages amendment 39 covers, both types."""
    assert policy.refusals_for(*_reissue(name)) == ()


@pytest.mark.parametrize("name", FIRST_HAND_OVERS)
def test_a_reissue_type_s_revision_1_is_refused(policy, name) -> None:
    """Kills: one map for both branches. A reissue type's revision 1 is a first hand-over and
    stays Devon's (D88-A): `types` lists neither reissue type."""
    assert policy.refusals_for(*_reissue(name)) == ("rotation_type_not_permitted",)


def test_a_lane_type_at_revision_2_is_refused(policy) -> None:
    """Kills: the reissue branch reading `types`. A lane credential's revision 2 refuses."""
    package = _lane_token(revision=2)
    lineage = _lineage(revisions=(1, 2), approvals=[_approval(1)])
    assert policy.refusals_for(package, lineage) == ("rotation_type_not_permitted",)


@pytest.mark.parametrize("provider", ["openrouter", "postgres-role", "github-pat"])
def test_a_type_not_in_reissue_types_is_refused(policy, provider) -> None:
    """Kills: a reissue grant that accepts any provider (amendment 39 reading 4)."""
    package = _operator()
    package["profile_fields"]["destinations"][2] = f'provider name="{provider}"'
    assert policy.refusals_for(package, _operator_lineage()) == ("rotation_type_not_permitted",)


def test_two_providers_are_refused_on_a_reissue(policy) -> None:
    package = _operator()
    package["profile_fields"]["destinations"].append('provider name="change-manager"')
    assert policy.refusals_for(package, _operator_lineage()) == ("rotation_type_not_permitted",)


def test_a_reissue_not_declared_standing_is_refused(policy) -> None:
    package = _operator()
    package["profile_fields"]["standing"] = False
    assert policy.refusals_for(package, _operator_lineage()) == ("not_a_standing_package",)


@pytest.mark.parametrize("revisions", [(1,), (1, 3), (2,), (1, 2, 3), (2, 1), (True, 2)])
def test_a_lineage_not_listing_revisions_1_to_the_tip_is_refused(policy, revisions) -> None:
    """Kills: dropping the 1-to-N check, or accepting `True` for revision 1."""
    lineage = _operator_lineage()
    lineage["revisions"] = [{"revision": r, "hash": "0" * 64} for r in revisions]
    assert policy.refusals_for(_operator(), lineage) == ("lineage_not_revisions_1_to_n",)


def test_a_tip_already_approved_is_refused(policy) -> None:
    """Kills: dropping the unapproved-tip check, so a replay of a policy approval refuses and
    waits for a person, as on the revision-1 branch."""
    lineage = _operator_lineage()
    lineage["approvals"].append(_approval(2, APPROVER))
    assert policy.refusals_for(_operator(), lineage) == ("revision_already_approved",)


@pytest.mark.parametrize(
    "approvals",
    [[], [_approval(2, "devon")]],
    ids=["no-approval", "only-revision-2-approved"],
)
def test_a_revision_1_never_approved_is_refused(policy, approvals) -> None:
    """Kills: dropping the revision-1 approval check. Revision 2 approved alone still refuses,
    on the observer's revision 3."""
    package, lineage = _reissue(OBSERVER)
    lineage["approvals"] = approvals
    assert policy.refusals_for(package, lineage) == ("revision_one_not_approved",)


@pytest.mark.parametrize(
    "approvers",
    [
        [APPROVER],
        ["policy:non-software-operational@v4"],
        ["claude-code-interactive"],
        ["Devon"],
        ["devon", APPROVER],
    ],
    ids=["policy-v5", "policy-v4", "an-agent", "case-differs", "devon-and-a-policy"],
)
def test_a_revision_1_approver_not_on_the_list_is_refused(policy, approvers) -> None:
    """Kills: reading "not `policy:`" instead of the fixed list, or accepting any one listed
    approver among others. HQ's settled change 1."""
    lineage = _operator_lineage()
    lineage["approvals"] = [_approval(1, approver) for approver in approvers]
    assert policy.refusals_for(_operator(), lineage) == ("revision_one_approver_not_permitted",)


@pytest.mark.parametrize(
    "lineage",
    [
        None,
        {"revisions": [{"revision": 1}, {"revision": 2}]},
        {"revisions": [{"revision": 1}, {"revision": 2}], "approvals": [None]},
        {"revisions": [{"revision": 1}, {"revision": 2}], "approvals": [_approval(1, 7)]},
        {"revisions": [{"revision": 1}, {"revision": 2}], "approvals": [_approval(True)]},
        {"revisions": [{"revision": 1}, {"revision": 2}], "approvals": [_approval(3)]},
        {"revisions": [{"revision": 1}, {"revision": 2}], "approvals": [{"approver": "devon"}]},
    ],
    ids=[
        "none",
        "no-approvals",
        "approval-not-a-table",
        "approver-not-a-string",
        "approval-revision-a-bool",
        "approval-past-the-tip",
        "approval-without-revision",
    ],
)
def test_an_unreadable_reissue_lineage_is_refused(policy, lineage) -> None:
    """Kills: skipping an approval entry it can't read. A check that can't be made refuses."""
    assert policy.refusals_for(_operator(), lineage) == ("lineage_unreadable",)


def test_a_revision_between_approved_by_policy_passes(policy) -> None:
    """The steady state after the first D-88 approval: revision 2 approved by policy, revision 3
    waiting. Kills: tightening the rule to "every earlier approver is a person"."""
    package, lineage = _reissue(OBSERVER)
    lineage["approvals"][1]["approver"] = APPROVER
    assert policy.refusals_for(package, lineage) == ()


def test_a_revision_between_never_approved_passes(policy) -> None:
    """A revision rejected before a later one doesn't refuse (R1's `reissue_lineage` rule).
    Kills: tightening the rule to "every revision approved"."""
    package, lineage = _reissue(OBSERVER)
    lineage["approvals"] = lineage["approvals"][:1]
    assert policy.refusals_for(package, lineage) == ()


@pytest.mark.parametrize("created_by", ["claude-code-interactive", None, ""])
def test_a_reissue_by_another_author_is_refused(policy, created_by) -> None:
    package = _operator(created_by=created_by)
    assert policy.refusals_for(package, _operator_lineage()) == ("not_proposer_generated",)


def test_a_reissue_the_proposer_wrote_passes(policy) -> None:
    """Both `created_by` values pass (amendment 39 reading 1)."""
    package = _operator(created_by="rotation-proposer")
    assert policy.refusals_for(package, _operator_lineage()) == ()


_CM_HELD = (
    'coolify-env-held instance="prod" resource_type="application" uuid="eqj5l7k705fhi12x9i74fqf0" '
    'key="EXAMPLE_TOKEN"'
)
_GH_COPY = 'gh-actions-secret repo="AlobarQuest/x" name="T"'
_RUNTIME = 'runtime-fetch repo="orchestrator" ref="scripts/run-example.sh"'


@pytest.mark.parametrize(
    ("name", "added"),
    [
        (OPERATOR, _LANE_ENV.format(redeploy="false")),
        (OPERATOR, 'keychain service="s" account="a"'),
        (OPERATOR, 'shell-export file="~/.zshenv" var="T"'),
        (OPERATOR, _CM_HELD),
        (CM_FULL, _GH_COPY),
        (CM_FULL, _LANE_ENV.format(redeploy="true")),
        (OPERATOR, 'runtime-fetch repo="orchestrator"'),
    ],
    ids=[
        "orchestrator+coolify-env",
        "orchestrator+keychain",
        "orchestrator+shell-export",
        "orchestrator+coolify-env-held",
        "change-manager+gh-actions-secret",
        "change-manager+coolify-env",
        "malformed",
    ],
)
def test_a_destination_of_a_kind_the_type_does_not_allow_is_refused(policy, name, added) -> None:
    """Kills: dropping or widening `destinations_allowed`. Each type's set is its own."""
    package, lineage = _reissue(name)
    package["profile_fields"]["destinations"].append(added)
    assert policy.refusals_for(package, lineage) == ("destinations_not_permitted",)


@pytest.mark.parametrize(
    ("name", "added"),
    [(OPERATOR, _RUNTIME), (OPERATOR, _GH_COPY), (CM_FULL, _CM_HELD), (OPERATOR, _KEEPER)],
    ids=["runtime-fetch", "orchestrator-gh-copy", "change-manager-held", "second-keeper"],
)
def test_an_allowed_kind_passes_at_any_count(policy, name, added) -> None:
    """Any count of an allowed kind passes: whether a written copy is new is the command's
    `no_new_copy` to decide, against the last approved revision this module can't read."""
    package, lineage = _reissue(name)
    package["profile_fields"]["destinations"].append(added)
    assert policy.refusals_for(package, lineage) == ()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: _move(p, "repository_write", into="allowed", out_of="prohibited"),
        lambda p: _move(p, "infra_mutation", into="prohibited", out_of="allowed"),
        lambda p: _move(p, "credential_revoke", into="requires_approval", out_of="allowed"),
        lambda p: p["authority"]["prohibited"].remove("email_send") or p,
        lambda p: p["authority"]["budgets"].update(max_attempts=4) or p,
        lambda p: p["authority"]["budgets"].update(max_llm_calls=10) or p,
        lambda p: p.update(authority=copy.deepcopy(_shipped(LANE_TOKEN)["authority"])) or p,
    ],
    ids=[
        "+repository_write",
        "-infra_mutation",
        "asks-revoke",
        "drops-a-prohibition",
        "four-attempts",
        "an-llm-budget",
        "the-lane-token-s-set",
    ],
)
def test_a_reissue_authority_other_than_the_standard_set_is_refused(policy, mutate) -> None:
    """Kills: dropping the authority check on the reissue branch, or comparing as a subset."""
    package = mutate(_operator())
    assert policy.refusals_for(package, _operator_lineage()) == ("authority_terms_not_permitted",)


def test_a_reissue_with_a_human_review_criterion_is_refused(policy) -> None:
    package = _operator()
    package["acceptance"][0]["evidence_type"] = "human_review"
    assert policy.refusals_for(package, _operator_lineage()) == ("acceptance_not_permitted",)


def test_every_reissue_refusal_is_reported(policy) -> None:
    package = _operator(created_by="someone")
    package["profile_fields"]["standing"] = False
    package["profile_fields"]["destinations"].append(_GH_COPY.replace("gh-actions", "nope"))
    package["authority"]["budgets"]["max_attempts"] = 9
    package["acceptance"][0]["evidence_type"] = "human_review"
    lineage = _operator_lineage()
    lineage["approvals"] = []
    assert policy.refusals_for(package, lineage) == (
        "not_a_standing_package",
        "revision_one_not_approved",
        "not_proposer_generated",
        "destinations_not_permitted",
        "authority_terms_not_permitted",
        "acceptance_not_permitted",
    )


# --- a document without the reissue fields refuses every reissue -----------------------

_REFUSED_BEFORE_SCHEMA_5 = (
    "not_revision_one",
    "lineage_has_approval",
    "not_proposer_generated",
    "rotation_type_not_permitted",
)


@pytest.mark.parametrize("name", COVERED)
def test_the_schema_4_document_still_loads_and_refuses_every_reissue(name) -> None:
    """The document as it stood before schema 5 draws the same refusals it did then."""
    schema_4 = load_policy(FIXTURES / "approval-policy-schema-4.toml")
    assert schema_4.version == 4
    assert schema_4.refusals_for(*_reissue(name)) == _REFUSED_BEFORE_SCHEMA_5


def _without_reissue_fields(text: str) -> str:
    """The shipped document with its three reissue fields deleted, as the rationale says."""
    head, _, rest = text.partition("[profile.non-software-operational.grant.reissue_types")
    _, _, tail = rest.partition("[profile.dependency-update]")
    head = "\n".join(line for line in head.splitlines() if not line.startswith("reissue_"))
    return f"{head}\n[profile.dependency-update]{tail}"


@pytest.mark.parametrize("name", COVERED)
def test_deleting_the_reissue_fields_refuses_every_reissue(tmp_path, name) -> None:
    """Kills: a reissue path that doesn't depend on `reissue_types`. The switch is the field."""
    text = _without_reissue_fields((FIXTURES.parent.parent / "approval-policy.toml").read_text())
    loaded = _load(tmp_path, text)
    grant = loaded.grants["non-software-operational"]
    assert isinstance(grant, RotationGrant)
    assert loaded.version == 5
    assert grant.reissue_types == {}
    assert loaded.refusals_for(*_reissue(name)) == _REFUSED_BEFORE_SCHEMA_5


# --- loading the reissue fields ---------------------------------------------------------

_REISSUE_FIELDS = """reissue_created_by = ["factory-create"]
reissue_revision_1_approvers = ["devon"]
"""
_REISSUE_TYPE = """
[profile.non-software-operational.grant.reissue_types.orchestrator]
destinations_allowed = [{kinds}]
authority_options = [
  {{ allowed = ["secret_read"], requires_approval = [], prohibited = ["email_send"], \
max_attempts = 3{extra} }},
]
"""


def _reissue_document(
    version: int = 5,
    *,
    fields: str = _REISSUE_FIELDS,
    kinds: str = '"bws-secret", "provider"',
    extra: str = "",
) -> str:
    text = _document(version).replace(
        'created_by = "rotation-proposer"\n', f'created_by = "rotation-proposer"\n{fields}'
    )
    return text + _REISSUE_TYPE.format(kinds=kinds, extra=extra)


def test_a_reissue_grant_loads_at_schema_5(tmp_path) -> None:
    grant = _load(tmp_path, _reissue_document()).grants["non-software-operational"]
    assert isinstance(grant, RotationGrant)
    assert sorted(grant.reissue_types) == ["orchestrator"]
    assert grant.reissue_types["orchestrator"].destinations_allowed == {"bws-secret", "provider"}
    assert grant.reissue_created_by == {"factory-create"}
    assert grant.reissue_revision_1_approvers == {"devon"}


def test_the_reissue_fields_at_schema_4_stop_the_document_loading(tmp_path) -> None:
    """Kills: a schema-4 document acquiring a reissue grant."""
    with pytest.raises(ApprovalPolicyError, match="unknown fields"):
        _load(tmp_path, _reissue_document(4))


@pytest.mark.parametrize(
    "fields",
    [
        'reissue_created_by = ["factory-create"]\n',
        'reissue_revision_1_approvers = ["devon"]\n',
        "",
    ],
    ids=["no-approvers", "no-created-by", "types-alone"],
)
def test_a_partial_reissue_grant_stops_the_document_loading(tmp_path, fields) -> None:
    """All three reissue fields or none: a reissue grant with no approver list is no grant."""
    with pytest.raises(ApprovalPolicyError, match="missing"):
        _load(tmp_path, _reissue_document(fields=fields))


@pytest.mark.parametrize(
    ("parts", "message"),
    [
        ({"kinds": '"bws-secret"'}, "must include the provider"),
        ({"kinds": '"bws-secret", "bws-secret", "provider"'}, "repeats a kind"),
        ({"kinds": '"nonsense", "provider"'}, "no destination kinds"),
        ({"kinds": ""}, "non-empty list"),
        ({"extra": ", max_llm_calls = 10"}, "unknown fields"),
        (
            {"fields": 'reissue_created_by = []\nreissue_revision_1_approvers = ["devon"]\n'},
            "non-empty",
        ),
        (
            {"fields": 'reissue_created_by = ["x"]\nreissue_revision_1_approvers = []\n'},
            "non-empty",
        ),
    ],
    ids=[
        "no-provider",
        "repeated-kind",
        "unknown-kind",
        "no-kinds",
        "authority-extra-field",
        "empty-created-by",
        "empty-approvers",
    ],
)
def test_a_malformed_reissue_grant_stops_the_document_loading(tmp_path, parts, message) -> None:
    with pytest.raises(ApprovalPolicyError, match=message):
        _load(tmp_path, _reissue_document(**parts))


# --- a reissue through do_approve -------------------------------------------------------


@pytest.fixture
def ready_reissue(tmp_path, monkeypatch, fake_registry):
    """A copy of the operator bearer's revision 2, `ready_for_review`, revision 1 by devon."""
    (fake_registry / "registry" / "capabilities.yaml").write_text(_CAPABILITIES, encoding="utf-8")
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    pkg_dir = tmp_path / OPERATOR
    shutil.copytree(REISSUE / OPERATOR, pkg_dir)
    return pkg_dir


def test_do_approve_takes_the_policy_approval_for_a_reissue(ready_reissue) -> None:
    emitter = StubEmitter()
    do_approve(ready_reissue, emitter=emitter, approver=APPROVER, commit="abc1234", now=NOW)

    lineage = ln.read(ready_reissue)
    assert lineage["current_state"] == "approved"
    assert [(a["revision"], a["approver"]) for a in lineage["approvals"]] == [
        (1, "devon"),
        (2, APPROVER),
    ]
    assert emitter.calls[0][2]["revision"] == 2


def test_a_repeated_policy_approval_of_a_reissue_refuses(ready_reissue) -> None:
    do_approve(ready_reissue, emitter=StubEmitter(), approver=APPROVER, commit="abc1234", now=NOW)
    emitter = StubEmitter()
    with pytest.raises(OperationError, match="revision_already_approved"):
        do_approve(ready_reissue, emitter=emitter, approver=APPROVER, commit="abc1234", now=NOW)
    assert emitter.calls == []
    assert len(ln.read(ready_reissue)["approvals"]) == 2
