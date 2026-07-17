import pytest

from intent_packages.factory_cli import main


def test_no_subcommand_errors():
    with pytest.raises(SystemExit):
        main([])


def test_decompose_requires_revision():
    with pytest.raises(SystemExit):
        main(["decompose", "--ac", "AC-001"])


def test_decompose_delegates_to_run(monkeypatch):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr("intent_packages.factory.decompose.run", fake_run)
    rc = main(
        [
            "decompose",
            "--revision",
            "rev-1",
            "--ac",
            "AC-002",
            "--target-repo",
            "AlobarQuest/brain",
            "--tooling",
            "pip",
            "--package",
            "fastapi",
            "--from",
            "0.139.0",
            "--to",
            "0.139.2",
            "--submit",
        ]
    )
    assert rc == 0
    assert seen["revision"] == "rev-1" and seen["ac"] == "AC-002"
    assert seen["from_version"] == "0.139.0" and seen["to_version"] == "0.139.2"
    assert seen["submit"] is True
