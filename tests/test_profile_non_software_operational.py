"""non-software-operational profile (WS-P2.10): the WS-P2.13 vehicle, shaped
from the historical listing-launch package. No repo, no CI, no authority
envelope — evidence is human/external/observation only, so automated_test is
structurally unreachable AND explicitly forbidden."""

import datetime
from pathlib import Path

import pytest
import yaml

from intent_packages import lineage as ln
from intent_packages import profiles
from intent_packages.approval_policy import PROFILE_NOT_POLICY_APPROVABLE, load_policy
from intent_packages.canonical import package_hash
from intent_packages.loader import load_package
from intent_packages.operations import do_approve, do_revise, do_transition
from intent_packages.validate import validate_package

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-07T00:00:00Z"


class StubEmitter:
    def emit(self, action, ref, evidence):
        return "evt-1"


VALID_FIELDS = {
    "owner": "Devon",
    "operating_procedure": "listing-description skill + listing-launch checklist",
}
VALID_AC = [
    {
        "id": "AC-001",
        "condition": "listing is live on the MLS",
        "evidence_type": "external_attestation",
        "evidence": "external: MLS listing number recorded",
        "approver": "external:mls",
    },
    {
        "id": "AC-002",
        "condition": "Devon confirms marketing assets shipped",
        "evidence_type": "human_review",
        "evidence": "human: Devon signs off",
        "approver": "human:devon",
    },
]


def _pkg(fields: dict, acceptance: list) -> dict:
    return {
        "profile": "non-software-operational",
        "profile_fields": fields,
        "acceptance": acceptance,
    }


def test_registered_without_envelope_or_tooling():
    profile = profiles.PROFILES["non-software-operational"]
    assert profile.change_class is None
    assert profile.default_authority is None
    assert profile.tooling is None
    assert profile.forbidden_evidence_types == frozenset({"automated_test"})


def test_declares_enrichment_despite_not_being_factory_executable():
    """The one profile with no change_class that still tells its workers something.

    `enrichment_for_profile` returns None for an absent spec because "a profile the factory
    cannot execute has no workers to tell". This profile's units are discharged by a human or a
    local operator reading the runner brief, so it has workers; without a spec their briefs
    carried nothing, which is the dead-config shape rather than a considered emptiness.
    """
    profile = profiles.PROFILES["non-software-operational"]
    assert profile.change_class is None
    assert profile.enrichment is not None
    assert profile.enrichment.code_road_slugs == ()
    assert profile.enrichment.infra_min_authority == "required"


def test_valid_package_passes():
    assert profiles.validate_profile(_pkg(VALID_FIELDS, VALID_AC)) == []


def test_optional_external_systems_list():
    fields = dict(VALID_FIELDS, external_systems=["MLS", "Zillow"])
    assert profiles.validate_profile(_pkg(fields, VALID_AC)) == []
    bad = dict(VALID_FIELDS, external_systems="MLS")
    errs = profiles.validate_profile(_pkg(bad, VALID_AC))
    assert "profile_fields.external_systems: expected a list, got str" in errs


def test_ci_tag_is_not_in_this_profiles_vocabulary():
    bad = [dict(VALID_AC[0], evidence="ci: something automated")]
    errs = profiles.validate_profile(_pkg(VALID_FIELDS, bad))
    assert any("does not start with a recognized producer tag" in e for e in errs)


def test_observation_tag_maps_to_observation_type():
    ac = [
        dict(
            VALID_AC[0],
            evidence="observation: post-launch signals recorded",
            evidence_type="observation",
            approver="role:verifier",
        )
    ]
    assert profiles.validate_profile(_pkg(VALID_FIELDS, ac)) == []


def test_missing_owner_fails():
    errs = profiles.validate_profile(_pkg({"operating_procedure": "x"}, VALID_AC))
    assert "profile_fields.owner: missing required key" in errs


def test_new_prefixes_are_known():
    assert {"external:", "observation:"} <= profiles.KNOWN_EVIDENCE_PREFIXES


# ---- standing rotation packages (ADR-0054) ---------------------------------------------------

STANDING_FIELDS = dict(
    VALID_FIELDS,
    standing=True,
    credential_id="bws-machine-token",
    occurrence="2026-10-07-exposure",
)
STANDING_MESSAGE = "required, as a non-empty string, when profile_fields.standing is true"


def test_standing_package_with_credential_and_occurrence_passes():
    assert profiles.validate_profile(_pkg(STANDING_FIELDS, VALID_AC)) == []


@pytest.mark.parametrize("key", ["credential_id", "occurrence"])
def test_standing_package_requires_each_rotation_field(key):
    fields = {k: v for k, v in STANDING_FIELDS.items() if k != key}
    errs = profiles.validate_profile(_pkg(fields, VALID_AC))
    assert errs == [f"profile_fields.{key}: {STANDING_MESSAGE}"]


@pytest.mark.parametrize("key", ["credential_id", "occurrence"])
def test_standing_package_refuses_a_blank_rotation_field(key):
    errs = profiles.validate_profile(_pkg(dict(STANDING_FIELDS, **{key: "  "}), VALID_AC))
    assert errs == [f"profile_fields.{key}: {STANDING_MESSAGE}"]


def test_non_standing_package_needs_neither_rotation_field():
    """`standing: false` is a declared one-off, which is what every package before ADR-0054 is."""
    assert profiles.validate_profile(_pkg(dict(VALID_FIELDS, standing=False), VALID_AC)) == []


def test_standing_must_be_a_real_boolean():
    """A quoted 'true' is not a declaration; it is refused by type, not read as truthy."""
    errs = profiles.validate_profile(_pkg(dict(STANDING_FIELDS, standing="true"), VALID_AC))
    assert "profile_fields.standing: expected bool, got str" in errs


def test_an_unquoted_date_occurrence_is_refused_legibly():
    """YAML loads an unquoted 2026-10-07 as a date; it must fail as a type error, not a crash."""
    fields = dict(STANDING_FIELDS, occurrence=datetime.date(2026, 10, 7))
    errs = profiles.validate_profile(_pkg(fields, VALID_AC))
    assert "profile_fields.occurrence: expected str, got date" in errs


def test_existing_rotation_package_hashes_as_before():
    """The fields are optional, so a package that sets none of them is byte-for-byte unchanged.

    The literal is the hash this package was approved under, before ADR-0054 existed.
    """
    pkg_dir = REPO_ROOT / "packages" / "wsp213-bws-machine-token-rotation"
    assert validate_package(pkg_dir) == []
    package = yaml.safe_load((pkg_dir / "package.yaml").read_text(encoding="utf-8"))
    assert "standing" not in package["profile_fields"]
    assert package_hash(package) == (
        "c56ca4433cdbe0b5078db4252065254ae5b860f992fa7052d97f1136085f8449"
    )


def test_a_standing_rotation_package_is_not_policy_approvable():
    """No grant: Devon approves every rotation revision by name (ADR-0054 increment 2).

    `_standing_refusal` reads `standing` without regard to profile, so it is now satisfied by
    this package; the absent grant is what still refuses it.
    """
    package = _pkg(STANDING_FIELDS, VALID_AC)
    assert load_policy().refusals_for(package) == (PROFILE_NOT_POLICY_APPROVABLE,)


_STANDING_LINES = (
    '  external_systems: ["mls", "zillow"]\n'
    "  standing: true\n"
    "  credential_id: 'bws-machine-token'\n"
    "  occurrence: '2026-10-07-exposure'\n"
)


def test_a_standing_rotation_package_is_revised_per_occurrence(
    non_software_operational_package, monkeypatch, fake_registry
):
    """The ADR-0028 cycle, as bump_proposer drives it: revise, write the per-revision value,
    transition, approve -- here by a named human, since this profile has no grant."""
    pkg_dir = non_software_operational_package
    path = pkg_dir / "package.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('  external_systems: ["mls", "zillow"]\n', _STANDING_LINES), encoding="utf-8"
    )
    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))

    def approve():
        do_transition(pkg_dir, "ready_for_review", emitter=StubEmitter(), now=NOW)
        do_approve(pkg_dir, emitter=StubEmitter(), approver="devon", commit="abc1234", now=NOW)

    approve()
    first = package_hash(load_package(pkg_dir))

    do_revise(pkg_dir, emitter=StubEmitter(), actor="devon", now=NOW)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("'2026-10-07-exposure'", "'2026-10-07-retry'"), encoding="utf-8")
    approve()

    package = load_package(pkg_dir)
    assert package["revision"] == 2
    assert package["profile_fields"]["occurrence"] == "2026-10-07-retry"
    approvals = ln.read(pkg_dir)["approvals"]
    assert [a["revision"] for a in approvals] == [1, 2]
    assert approvals[0]["approved_hash"] == first
    assert approvals[1]["approved_hash"] == package_hash(package) != first


def test_the_approved_openrouter_rotation_package_hashes_as_approved():
    """`destinations` is optional, so revision 1, approved before ADR-0055, is unchanged.

    The literal is the `approved_hash` in that package's lineage.
    """
    pkg_dir = REPO_ROOT / "packages" / "rotation-openrouter-generic"
    assert validate_package(pkg_dir) == []
    package = yaml.safe_load((pkg_dir / "package.yaml").read_text(encoding="utf-8"))
    assert "destinations" not in package["profile_fields"]
    assert package_hash(package) == (
        "c1b259d7f6b876cdeac9c425385917ecf4068e95c4497947ba14a3f1b9405d8b"
    )


DESTINATIONS = ["bws-secret Rotation / Keeper / openrouter-generic", "provider openrouter"]


def test_a_sorted_unique_destination_list_is_accepted():
    fields = dict(STANDING_FIELDS, destinations=DESTINATIONS)
    assert profiles.validate_profile(_pkg(fields, VALID_AC)) == []


@pytest.mark.parametrize(
    ("destinations", "message"),
    [
        ([], "must name at least one destination"),
        (["provider openrouter", " "], "each entry must be a non-blank, trimmed string"),
        (["provider openrouter "], "each entry must be a non-blank, trimmed string"),
        (list(reversed(DESTINATIONS)), "entries must be sorted and unique"),
        (DESTINATIONS + DESTINATIONS[-1:], "entries must be sorted and unique"),
    ],
)
def test_a_malformed_destination_list_is_refused(destinations, message):
    fields = dict(STANDING_FIELDS, destinations=destinations)
    errs = profiles.validate_profile(_pkg(fields, VALID_AC))
    assert errs == [f"profile_fields.destinations: {message}"]


def test_destinations_must_be_strings():
    fields = dict(STANDING_FIELDS, destinations=[{"kind": "bws-secret"}])
    errs = profiles.validate_profile(_pkg(fields, VALID_AC))
    assert errs and all("destinations" in err for err in errs)
