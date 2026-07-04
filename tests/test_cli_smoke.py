import pytest

from intent_packages.cli import main
from intent_packages.loader import load_package


def test_no_subcommand_errors():
    with pytest.raises(SystemExit):
        main([])


def test_transition_subcommand_flips_status(valid_package, capsys):
    # No security-standards checkout in the hermetic test env, so the CLI's
    # real FactoryEventsEmitter degrades to a best-effort no-op (do_transition
    # swallows the EmitError internally) — the transition still succeeds.
    rc = main(["transition", str(valid_package), "--to", "ready_for_review"])
    assert rc == 0
    assert load_package(valid_package)["status"] == "ready_for_review"
    assert "transitioned to ready_for_review" in capsys.readouterr().out


def test_transition_subcommand_illegal_transition_exits_nonzero(valid_package, capsys):
    rc = main(["transition", str(valid_package), "--to", "approved"])
    assert rc == 1
    assert "transition failed" in capsys.readouterr().err
