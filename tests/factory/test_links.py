from intent_packages.factory import links

BASE = "https://sds.alobar.net"


def test_all_five_links():
    assert links.intake_new(BASE) == f"{BASE}/review/intakes/new"
    assert links.intake(BASE, "r1") == f"{BASE}/review/intakes/r1"
    assert links.decomposition_proposal(BASE, "p1") == f"{BASE}/review/decomposition-proposals/p1"
    assert links.unit(BASE, "u1") == f"{BASE}/review/units/u1"
    assert links.unit_evidence_pack(BASE, "u1") == f"{BASE}/review/units/u1/evidence-pack"


def test_trailing_slash_on_base_is_normalised():
    assert links.intake_new(f"{BASE}/") == f"{BASE}/review/intakes/new"
