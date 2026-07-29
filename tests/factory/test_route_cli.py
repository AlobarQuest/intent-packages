"""`factory route` (WS-P2.10): the query consumer of routing-policy.toml.
Session-model choices and handoff "Suggested model" lines cite this command."""

import pytest

from intent_packages.factory_cli import main


def test_route_surface_prints_model_and_rationale(capsys):
    assert main(["route", "--surface", "runner-implementation"]) == 0
    out = capsys.readouterr().out
    assert "runner-implementation: sonnet-5 (claude-sonnet-5)" in out
    assert "decided 2026-07-08" in out


def test_route_change_class_resolves(capsys):
    assert main(["route", "--change-class", "dependency-update"]) == 0
    assert "dependency-update: sonnet-5 (claude-sonnet-5)" in capsys.readouterr().out


def test_route_dual_model_surface_prints_both(capsys):
    assert main(["route", "--surface", "judgment-ac-verification"]) == 0
    out = capsys.readouterr().out
    assert "judgment-ac-verification: fable-5 (claude-fable-5)" in out
    assert "judgment-ac-verification: opus-4-8 (claude-opus-4-8)" in out


def test_route_unknown_surface_exits_1(capsys):
    assert main(["route", "--surface", "nope"]) == 1
    err = capsys.readouterr().err
    assert "route failed:" in err
    assert "nope" in err


def test_route_unknown_change_class_exits_1(capsys):
    assert main(["route", "--change-class", "docs-only"]) == 1
    assert "route failed:" in capsys.readouterr().err


def test_route_requires_exactly_one_selector():
    with pytest.raises(SystemExit) as excinfo:
        main(["route"])
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        main(["route", "--surface", "a", "--change-class", "b"])
    assert excinfo.value.code == 2


def test_route_explicit_policy_path(tmp_path, capsys):
    policy = tmp_path / "p.toml"
    policy.write_text(
        'version = 7\n[models]\nsonnet-5 = "claude-sonnet-5"\n'
        "[no_llm]\nitems = []\n"
        '[[surface]]\nid = "s"\nmodels = ["sonnet-5"]\nwhere = "w"\n'
        'rationale = "r"\ndecided = "2026-07-29"\n',
        encoding="utf-8",
    )
    assert main(["route", "--surface", "s", "--policy", str(policy)]) == 0
    assert "s: sonnet-5 (claude-sonnet-5)" in capsys.readouterr().out
