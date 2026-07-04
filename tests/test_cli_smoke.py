import pytest

from intent_packages import lineage as ln
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


def test_approve_subcommand_approves_package(valid_package, monkeypatch, fake_registry, capsys):
    # fake_registry supplies a human-operator identity for "devon" but is not
    # a full security-standards checkout (no factory_events module), so the
    # real FactoryEventsEmitter can't actually emit here. Approval's emit is
    # fatal-on-failure by design, so exercising the CLI's success path
    # requires stubbing the emitter class the CLI constructs -- same
    # dependency-injection point `_run_approve` uses in production.
    class _StubEmitter:
        def emit(self, action, ref, evidence):
            return "evt-cli-approve"

    monkeypatch.setenv("SECURITY_STANDARDS_DIR", str(fake_registry))
    monkeypatch.setattr("intent_packages.emitter.FactoryEventsEmitter", _StubEmitter)
    main(["transition", str(valid_package), "--to", "ready_for_review"])
    capsys.readouterr()  # discard the transition output

    rc = main(["approve", str(valid_package), "--approver", "devon"])
    assert rc == 0
    assert load_package(valid_package)["status"] == "approved"
    assert "approved by devon" in capsys.readouterr().out


def test_approve_subcommand_non_human_approver_exits_nonzero(valid_package, capsys):
    # Hermetic env has no security-standards checkout, so no identity ever
    # resolves as a human operator -- approve must refuse and exit nonzero.
    main(["transition", str(valid_package), "--to", "ready_for_review"])
    capsys.readouterr()

    rc = main(["approve", str(valid_package), "--approver", "devon"])
    assert rc == 1
    assert "approve failed" in capsys.readouterr().err


def test_revise_subcommand_bumps_revision(valid_package, capsys):
    rc = main(["revise", str(valid_package)])
    assert rc == 0
    package = load_package(valid_package)
    assert package["revision"] == 2
    assert package["status"] == "draft"
    assert "revised" in capsys.readouterr().out


def test_revise_subcommand_from_execution_state_exits_nonzero(valid_package, capsys):
    lin = ln.read(valid_package)
    lin["current_state"] = "in_execution"
    ln.write(valid_package, lin)

    rc = main(["revise", str(valid_package)])
    assert rc == 1
    assert "revise failed" in capsys.readouterr().err


def test_supersede_subcommand_marks_superseded(valid_package, capsys):
    lin = ln.read(valid_package)
    lin["current_state"] = "approved"
    ln.write(valid_package, lin)

    rc = main(["supersede", str(valid_package), "--by", "sample-replacement-package"])
    assert rc == 0
    assert load_package(valid_package)["status"] == "superseded"
    assert "superseded by sample-replacement-package" in capsys.readouterr().out


def test_supersede_subcommand_illegal_exits_nonzero(valid_package, capsys):
    rc = main(["supersede", str(valid_package), "--by", "sample-replacement-package"])
    assert rc == 1
    assert "supersede failed" in capsys.readouterr().err
