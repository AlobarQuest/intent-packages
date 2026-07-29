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


def test_create_through_the_entrypoint(tmp_path):
    from intent_packages.factory_cli import main

    rc = main(
        ["create", "--profile", "software-delivery", "--name", "probe", "--out", str(tmp_path)]
    )
    assert rc == 0
    assert (tmp_path / "probe" / "package.yaml").exists()


def test_validate_through_the_entrypoint(tmp_path):
    from intent_packages.factory_cli import main

    main(["create", "--profile", "software-delivery", "--name", "probe", "--out", str(tmp_path)])
    assert main(["validate", str(tmp_path / "probe")]) == 0


def test_verify_requires_its_flags():
    with pytest.raises(SystemExit):
        main(["verify", "--unit-key", "bump-fastapi"])


def test_verify_delegates_to_verify_module(monkeypatch):
    seen = {}

    def fake_verify(revision_id, unit_key, **kwargs):
        seen["args"] = (revision_id, unit_key)
        seen["kwargs"] = kwargs
        return 0

    monkeypatch.setattr("intent_packages.factory.verify.verify", fake_verify)
    rc = main(
        [
            "verify",
            "--revision",
            "r1",
            "--unit-key",
            "bump-fastapi",
            "--ac",
            "AC-001",
            "--check-name",
            "Quality",
            "--conclusion",
            "success",
            "--run-id",
            "99",
            "--run-url",
            "https://github.com/x/y/actions/runs/99",
            "--assert",
            "collected=295:295",
            "--assert",
            "passed=true:true",
        ]
    )
    assert rc == 0
    assert seen["args"] == ("r1", "bump-fastapi")
    assert seen["kwargs"]["ac_id"] == "AC-001"
    assert seen["kwargs"]["check_name"] == "Quality"
    assert seen["kwargs"]["conclusion"] == "success"
    assert seen["kwargs"]["run_id"] == "99"
    assert seen["kwargs"]["run_url"] == "https://github.com/x/y/actions/runs/99"
    assert seen["kwargs"]["assertions"] == ["collected=295:295", "passed=true:true"]
    assert seen["kwargs"]["repository"] == ""


def test_verify_rejects_an_unknown_conclusion():
    with pytest.raises(SystemExit):
        main(
            [
                "verify",
                "--unit-key",
                "k",
                "--ac",
                "AC-001",
                "--check-name",
                "Quality",
                "--conclusion",
                "stale",
                "--run-id",
                "99",
                "--run-url",
                "u",
            ]
        )
