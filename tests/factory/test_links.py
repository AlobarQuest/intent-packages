from intent_packages.factory import links

BASE = "https://sds.alobar.net"


def test_every_link_builder():
    """Three builders, and the module's docstring says three -- the previous
    version of this test was named for five while the docstring claimed four,
    and two of the five had no caller anywhere (C4)."""
    assert links.intake_new(BASE) == f"{BASE}/review/intakes/new"
    assert links.decomposition_proposal(BASE, "p1") == f"{BASE}/review/decomposition-proposals/p1"
    assert links.unit(BASE, "u1") == f"{BASE}/review/units/u1"


def test_the_module_exposes_no_uncalled_builders():
    """Every public builder in `links` must be referenced by a `factory` verb.

    The deleted `intake`/`unit_evidence_pack` pair was dead for the whole
    branch and only a docstring noticed. This asserts the inventory rather than
    trusting prose: a new builder added without a call site fails here.
    """
    from pathlib import Path

    from intent_packages.factory import execution, journey, verify

    builders = {
        name for name in vars(links) if not name.startswith("_") and callable(getattr(links, name))
    }
    callers = "".join(
        Path(module.__file__ or "").read_text() for module in (journey, execution, verify)
    )
    assert builders == {"intake_new", "decomposition_proposal", "unit"}
    for name in builders:
        assert f"links.{name}(" in callers, f"links.{name} has no caller in a factory verb"


def test_trailing_slash_on_base_is_normalised():
    assert links.intake_new(f"{BASE}/") == f"{BASE}/review/intakes/new"
