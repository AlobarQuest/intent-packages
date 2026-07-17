import pytest

from intent_packages.factory_cli import main


def test_no_subcommand_errors():
    with pytest.raises(SystemExit):
        main([])


def test_decompose_requires_revision():
    with pytest.raises(SystemExit):
        main(["decompose", "--ac", "AC-001"])


def test_decompose_parses_all_args(capsys):
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
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "rev-1" in out and "AC-002" in out and "pip" in out
