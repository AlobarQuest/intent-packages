from pathlib import Path

import pytest

from intent_packages.factory_cli import _HANDLERS, main

ALL_COMMANDS = sorted(_HANDLERS)


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


def test_validate_reports_an_invalid_package_as_a_failure(tmp_path, capsys):
    """B2. `factory validate`'s FAILURE path had no coverage at all: replacing
    the whole body with `return 0` kept every test green, because the only
    existing test validated a package `create` had just written and already
    validated. Exit 1, and the validator's own errors on stderr."""
    import yaml

    main(["create", "--profile", "software-delivery", "--name", "probe", "--out", str(tmp_path)])
    package_path = tmp_path / "probe" / "package.yaml"
    document = yaml.safe_load(package_path.read_text())
    del document["acceptance"]
    package_path.write_text(yaml.safe_dump(document, sort_keys=False))
    capsys.readouterr()

    rc = main(["validate", str(package_path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "acceptance" in captured.err
    assert ": valid" not in captured.out


def test_validate_accepts_the_package_yaml_path_as_well_as_the_directory(tmp_path, capsys):
    """`validate` takes "a package directory or its package.yaml"; the happy path
    was only ever exercised with the directory."""
    main(["create", "--profile", "software-delivery", "--name", "probe", "--out", str(tmp_path)])
    capsys.readouterr()
    assert main(["validate", str(tmp_path / "probe" / "package.yaml")]) == 0
    assert "valid" in capsys.readouterr().out


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
    assert "repository" not in seen["kwargs"]


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


# -- Task 10: entrypoint coverage for every verb -------------------------------


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_every_command_is_reachable_and_has_help(command, capsys):
    """Drive every `_HANDLERS` key through the real parser wiring -- `main`,
    not the module function. `ALL_COMMANDS` is derived from `_HANDLERS` itself
    (not a hand-maintained list), so a future verb added to the dispatch table
    without a matching subparser fails this test the moment it lands."""
    with pytest.raises(SystemExit) as exit_info:
        main([command, "--help"])
    assert exit_info.value.code == 0
    assert command in capsys.readouterr().out


@pytest.mark.parametrize("command", ["status", "evidence", "ready", "dispatch", "verify"])
def test_revision_falls_back_to_the_environment(command, monkeypatch):
    """--revision defaults to $FACTORY_REVISION; neither set is exit 2.

    `decompose` is deliberately excluded: its `--revision` is `required=True`
    at the parser level (a missing value is a parser SystemExit, not this
    fallback), and `create`/`validate`/`route`/`submit` take no `--revision`
    at all.
    """
    monkeypatch.delenv("FACTORY_REVISION", raising=False)
    argv = [command]
    if command in {"ready", "dispatch", "verify"}:
        argv += ["--unit-key", "k"]
    if command == "verify":
        argv += [
            "--ac",
            "AC-001",
            "--check-name",
            "Q",
            "--conclusion",
            "success",
            "--run-id",
            "1",
            "--run-url",
            "u",
        ]
    assert main(argv) == 2


def test_no_command_can_impersonate_a_human():
    """ADR-0006: human gates are browser-only permanently, so no flag may
    exist that could be read as satisfying `_require_human`. This is a
    SOURCE SCAN, not a proof -- it only shows these four known spellings are
    absent from this file, not that no functionally-equivalent flag exists.
    """
    import intent_packages.factory_cli as cli

    text = Path(cli.__file__).read_text()
    for forbidden in ("--as-human", "--human", "--force", "--impersonate"):
        assert forbidden not in text


# -- Task 10: --verbose ---------------------------------------------------------


def test_verbose_prints_the_request_line_and_no_token(capsys):
    """`OrchestratorApi(verbose=True)` prints method/path/status and never the
    token -- verified directly against the real client, independent of any
    particular verb's wiring."""
    import httpx

    from intent_packages.factory.api import OrchestratorApi

    api = OrchestratorApi(
        "https://sds.example",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        token_resolver=lambda role: "supersecret",
        verbose=True,
    )
    api.get_intake("r1")
    out = capsys.readouterr().out
    assert "GET /api/v1/package-intakes/r1 -> 200" in out
    assert "supersecret" not in out


class _VerboseCaptured(Exception):
    """Raised by the spy `OrchestratorApi` stand-ins below, immediately after
    recording the `verbose` kwarg they were constructed with. This proves
    `--verbose` reached that verb's OWN `OrchestratorApi(...)` construction
    site -- not merely that the CLI parsed the flag -- for each of the six
    sites across journey.py, execution.py, verify.py and decompose.py: a flag
    that works for three verbs and silently does nothing for the other two
    would be worse than no flag at all.
    """


def _capturing_api(monkeypatch, target: str) -> list[bool | None]:
    seen: list[bool | None] = []

    class _Spy:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs.get("verbose"))
            raise _VerboseCaptured

    monkeypatch.setattr(target, _Spy)
    return seen


def test_verbose_reaches_decompose(monkeypatch):
    seen = _capturing_api(monkeypatch, "intent_packages.factory.decompose.OrchestratorApi")
    with pytest.raises(_VerboseCaptured):
        main(
            [
                "--verbose",
                "decompose",
                "--revision",
                "r1",
                "--ac",
                "AC-001",
                "--target-repo",
                "AlobarQuest/brain",
                "--tooling",
                "pip",
                "--package",
                "fastapi",
                "--from",
                "1.0",
                "--to",
                "1.1",
            ]
        )
    assert seen == [True]


def test_verbose_reaches_status(monkeypatch):
    seen = _capturing_api(monkeypatch, "intent_packages.factory.journey.OrchestratorApi")
    with pytest.raises(_VerboseCaptured):
        main(["--verbose", "status", "--revision", "r1"])
    assert seen == [True]


def test_verbose_reaches_evidence(monkeypatch):
    seen = _capturing_api(monkeypatch, "intent_packages.factory.journey.OrchestratorApi")
    with pytest.raises(_VerboseCaptured):
        main(["--verbose", "evidence", "--revision", "r1"])
    assert seen == [True]


def test_verbose_reaches_ready(monkeypatch):
    seen = _capturing_api(monkeypatch, "intent_packages.factory.execution.OrchestratorApi")
    with pytest.raises(_VerboseCaptured):
        main(["--verbose", "ready", "--revision", "r1", "--unit-key", "k"])
    assert seen == [True]


def test_verbose_reaches_dispatch(monkeypatch):
    seen = _capturing_api(monkeypatch, "intent_packages.factory.execution.OrchestratorApi")
    with pytest.raises(_VerboseCaptured):
        main(["--verbose", "dispatch", "--revision", "r1", "--unit-key", "k"])
    assert seen == [True]


def test_verbose_reaches_verify(monkeypatch):
    seen = _capturing_api(monkeypatch, "intent_packages.factory.verify.OrchestratorApi")
    with pytest.raises(_VerboseCaptured):
        main(
            [
                "--verbose",
                "verify",
                "--revision",
                "r1",
                "--unit-key",
                "k",
                "--ac",
                "AC-001",
                "--check-name",
                "Q",
                "--conclusion",
                "success",
                "--run-id",
                "1",
                "--run-url",
                "u",
            ]
        )
    assert seen == [True]


def test_verbose_defaults_to_false(monkeypatch):
    """Without --verbose, the constructed api gets verbose=False -- the flag
    is opt-in, not sticky."""
    seen = _capturing_api(monkeypatch, "intent_packages.factory.journey.OrchestratorApi")
    with pytest.raises(_VerboseCaptured):
        main(["status", "--revision", "r1"])
    assert seen == [False]
