import subprocess
import sys
from pathlib import Path

import pytest

from intent_packages.factory_cli import _HANDLERS, main

ALL_COMMANDS = sorted(_HANDLERS)

# `--reach` is required (WS-P2.18 Increment 4): a scaffold that defaulted it would be a
# declaration made by a tool and attributed to the author. Append the `--out` directory.
CREATE_PROBE = [
    "create",
    "--profile",
    "software-delivery",
    "--name",
    "probe",
    "--reach",
    "source_repository",
    "--out",
]


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

    rc = main(CREATE_PROBE + [str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "probe" / "package.yaml").exists()


def test_validate_through_the_entrypoint(tmp_path):
    from intent_packages.factory_cli import main

    main(CREATE_PROBE + [str(tmp_path)])
    assert main(["validate", str(tmp_path / "probe")]) == 0


def test_validate_reports_an_invalid_package_as_a_failure(tmp_path, capsys):
    """B2. `factory validate`'s FAILURE path had no coverage at all: replacing
    the whole body with `return 0` kept every test green, because the only
    existing test validated a package `create` had just written and already
    validated. Exit 1, and the validator's own errors on stderr."""
    import yaml

    main(CREATE_PROBE + [str(tmp_path)])
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
    main(CREATE_PROBE + [str(tmp_path)])
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
            "--expected-conclusion",
            "success",
        ]
    )
    assert rc == 0
    assert seen["args"] == ("r1", "bump-fastapi")
    assert seen["kwargs"]["ac_id"] == "AC-001"
    assert seen["kwargs"]["check_name"] == "Quality"
    assert seen["kwargs"]["expected_conclusion"] == "success"
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
                "--expected-conclusion",
                "stale",
            ]
        )


# -- B1: submit through the real parser wiring ---------------------------------
#
# `submit` was the ONE verb never driven through `main(argv)`: replacing
# `_run_submit`'s body with `return 0` kept all 197 factory tests green. Spec §6's
# first testing requirement is that command functions are reached through the real
# parser wiring, and `submit` is also the verb carrying the ADR-0006 gate -- so a
# broken `_run_submit` would silently disable the front door's only human handoff.


def _approved_package_dir(tmp_path):
    """A package `submit` will accept: scaffolded, then flipped to approved in
    both files (intake requires `status == current_state == approved`)."""
    import yaml

    main(CREATE_PROBE + [str(tmp_path)])
    for name, key in (("package.yaml", "status"), ("lineage.yaml", "current_state")):
        path = tmp_path / "probe" / name
        document = yaml.safe_load(path.read_text())
        document[key] = "approved"
        path.write_text(yaml.safe_dump(document, sort_keys=False))
    return tmp_path / "probe"


class _FakeOrchestratorClient:
    """Stands in for the `OrchestratorClient` `submit` constructs itself.

    Patched at `journey.OrchestratorClient` -- the construction site -- rather
    than injected, because `_run_submit` passes no `client`: injecting one would
    test a path the CLI never takes.
    """

    calls: list[tuple] = []

    def __init__(self, *args, **kwargs):
        pass

    def emit_intake_payload(self, package_path, source_repository, idempotency_key):
        _FakeOrchestratorClient.calls.append((package_path, source_repository, idempotency_key))
        return {"idempotency_key": idempotency_key, "source_repository": source_repository}


SUBMIT_TOKEN = "SENTINEL-CLI-TOKEN-91c2"
STAGED_PATH = "/review/staged-intakes/22222222-2222-2222-2222-222222222222"


class _Boundaries:
    """What the default process boundaries `submit` reaches for recorded."""

    def __init__(self):
        self.copied: list[str] = []
        self.requests: list = []


def _patch_submit_boundaries(monkeypatch, *, status=201, body=None):
    """Replace the three process boundaries `submit` reaches for by default:
    the `orchestrator` subprocess, `pbcopy`, and the network.

    The network is replaced BELOW `OrchestratorApi` -- the real client is
    constructed at `journey.OrchestratorApi`, with only its transport and token
    resolver swapped -- so the headers, path, body and error mapping under test
    are the production ones. Any request to a path other than
    `/api/v1/staged-intakes` fails the test: `submit` may stage, never register.
    """
    import httpx

    from intent_packages.factory import api as api_module

    _FakeOrchestratorClient.calls = []
    seen = _Boundaries()
    monkeypatch.setattr(
        "intent_packages.factory.journey.OrchestratorClient", _FakeOrchestratorClient
    )
    monkeypatch.setattr(
        "intent_packages.factory.journey._default_clipboard", lambda text: seen.copied.append(text)
    )

    def handler(request):
        assert request.url.path == "/api/v1/staged-intakes", request.url.path
        seen.requests.append(request)
        return httpx.Response(
            status,
            json=body
            if body is not None
            else {
                "id": "22222222-2222-2222-2222-222222222222",
                "state": "staged",
                "idempotency_key": "k",
                "package_id": "probe",
                "revision": 1,
                "staged_by": "orchestrator-system",
                "staged_at": "2026-10-06T00:00:00Z",
                "registered_revision_id": None,
                "review_path": STAGED_PATH,
            },
        )

    real_api = api_module.OrchestratorApi

    def _constructed_by_submit(*args, **kwargs):
        return real_api(
            *args,
            transport=httpx.MockTransport(handler),
            token_resolver=lambda role: SUBMIT_TOKEN,
            **kwargs,
        )

    monkeypatch.setattr("intent_packages.factory.journey.OrchestratorApi", _constructed_by_submit)
    return seen


def _submit_argv(package, *extra):
    return [
        "submit",
        "--package",
        str(package),
        "--source-repository",
        "AlobarQuest/intent-packages",
        *extra,
    ]


def test_submit_through_the_entrypoint(tmp_path, capsys, monkeypatch):
    """The whole verb, driven by `main(argv)`: parser wiring, package resolution,
    payload emission, the staging POST, the review link, and the resume line."""
    import json

    monkeypatch.setenv("ORCHESTRATOR_API_URL", "https://sds.example")
    seen = _patch_submit_boundaries(monkeypatch)
    package = _approved_package_dir(tmp_path)
    capsys.readouterr()

    rc = main(["--verbose", *_submit_argv(package)])
    assert rc == 0
    captured = capsys.readouterr()
    assert f"https://sds.example{STAGED_PATH}" in captured.out
    assert "registers nothing" in captured.out
    assert "factory status --revision" in captured.out
    assert "POST /api/v1/staged-intakes -> 201" in captured.out
    assert SUBMIT_TOKEN not in captured.out + captured.err
    # The parsed flags actually reached `emit_intake_payload`...
    [(package_path, source_repository, idempotency_key)] = _FakeOrchestratorClient.calls
    assert package_path == str(package)
    assert source_repository == "AlobarQuest/intent-packages"
    assert idempotency_key.startswith("factory-submit-probe-r1-")
    # ...and the emitted payload is exactly what was staged, as SYSTEM.
    [request] = seen.requests
    assert request.method == "POST"
    assert request.headers["x-credential-key-id"] == "orchestrator-system"
    assert request.headers["authorization"] == f"Bearer {SUBMIT_TOKEN}"
    assert json.loads(request.content) == {
        "idempotency_key": idempotency_key,
        "source_repository": "AlobarQuest/intent-packages",
    }
    assert seen.copied == []


def test_submit_through_the_entrypoint_rerun_stages_under_the_same_key(tmp_path, monkeypatch):
    seen = _patch_submit_boundaries(monkeypatch)
    package = _approved_package_dir(tmp_path)
    assert main(_submit_argv(package)) == 0
    assert main(_submit_argv(package)) == 0
    first, second = (call[2] for call in _FakeOrchestratorClient.calls)
    assert first == second
    assert len(seen.requests) == 2


def test_submit_through_the_entrypoint_passes_the_key_override(tmp_path, monkeypatch):
    _patch_submit_boundaries(monkeypatch)
    package = _approved_package_dir(tmp_path)
    assert main(_submit_argv(package, "--idempotency-key", "restage-2")) == 0
    assert _FakeOrchestratorClient.calls[0][2] == "restage-2"


def test_submit_through_the_entrypoint_reports_a_refusal(tmp_path, capsys, monkeypatch):
    _patch_submit_boundaries(
        monkeypatch,
        status=409,
        body={
            "error": {
                "code": "intake_already_registered",
                "message": "package revision is already registered",
                "recovery": None,
            }
        },
    )
    package = _approved_package_dir(tmp_path)
    capsys.readouterr()
    assert main(_submit_argv(package)) == 1
    captured = capsys.readouterr()
    assert "intake_already_registered: package revision is already registered" in captured.err
    assert SUBMIT_TOKEN not in captured.out + captured.err


def test_submit_through_the_entrypoint_refuses_an_unapproved_package(tmp_path, capsys, monkeypatch):
    """The refusal path through the real wiring: a draft package must not even
    reach `emit_intake_payload`, nothing is staged, and the operator gets the
    `intent_packages` commands that would fix it."""
    seen = _patch_submit_boundaries(monkeypatch)
    main(CREATE_PROBE + [str(tmp_path)])
    capsys.readouterr()

    rc = main(_submit_argv(tmp_path / "probe"))
    assert rc == 1
    err = capsys.readouterr().err
    assert "is not approved" in err
    assert "intent_packages approve" in err
    assert _FakeOrchestratorClient.calls == []
    assert seen.requests == []


def test_submit_print_through_the_entrypoint_copies_and_never_stages(tmp_path, capsys, monkeypatch):
    """`--print`, the escape hatch, on the path the CLI actually takes: the
    payload goes to the clipboard for the paste form, and no request is made."""
    monkeypatch.setenv("ORCHESTRATOR_API_URL", "https://sds.example")
    seen = _patch_submit_boundaries(monkeypatch)
    package = _approved_package_dir(tmp_path)
    capsys.readouterr()

    assert main(_submit_argv(package, "--print")) == 0
    out = capsys.readouterr().out
    assert "https://sds.example/review/intakes/new" in out
    assert "factory status --revision" in out
    assert seen.requests == []
    [text] = seen.copied
    assert "factory-submit-probe-r1-" in text


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ((), f"https://sds.example{STAGED_PATH}"),
        (("--print",), "https://sds.example/review/intakes/new"),
    ],
)
def test_submit_open_flag_reaches_the_browser(tmp_path, monkeypatch, extra, expected):
    """`--open` opens the page that applies: the staged row, or the paste form."""
    monkeypatch.setenv("ORCHESTRATOR_API_URL", "https://sds.example")
    _patch_submit_boundaries(monkeypatch)
    opened: list[str] = []
    monkeypatch.setattr(
        "intent_packages.factory.journey.webbrowser.open", lambda url: opened.append(url)
    )

    package = _approved_package_dir(tmp_path)
    assert main(_submit_argv(package, "--open", *extra)) == 0
    assert opened == [expected]


def test_submit_without_open_does_not_touch_the_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_API_URL", "https://sds.example")
    _patch_submit_boundaries(monkeypatch)

    def _explode(url):
        raise AssertionError("submit must not open a browser without --open")

    monkeypatch.setattr("intent_packages.factory.journey.webbrowser.open", _explode)
    package = _approved_package_dir(tmp_path)
    assert main(_submit_argv(package)) == 0


def test_submit_requires_its_flags():
    with pytest.raises(SystemExit):
        main(["submit", "--package", "packages/probe"])


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
            "--expected-conclusion",
            "success",
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
                "--expected-conclusion",
                "success",
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


def test_onboard_passthrough_invokes_portfolio_and_passes_exit_code(monkeypatch):
    import subprocess as sp

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return sp.CompletedProcess(args=cmd, returncode=1)

    monkeypatch.setenv("PROJECT_STANDARDS_DIR", "/tmp/ps")
    monkeypatch.setattr(sp, "run", fake_run)
    rc = main(["onboard", "/tmp/some-repo"])
    assert rc == 1
    assert captured["cmd"] == [
        "uv",
        "run",
        "--project",
        "/tmp/ps",
        "portfolio",
        "onboard",
        "/tmp/some-repo",
    ]


def test_create_from_readiness_dispatches(monkeypatch):
    seen = {}

    def fake(readiness, package_id, out, owner="devon"):
        seen["args"] = (readiness, package_id, out, owner)
        return 0

    monkeypatch.setattr("intent_packages.factory.scaffolds.create_from_readiness", fake)
    rc = main(["create", "--from-readiness", "r.json", "--name", "x", "--out", "o"])
    assert rc == 0
    assert seen["args"] == ("r.json", "x", "o", "devon")


def test_create_from_readiness_rejects_profile(capsys):
    rc = main(["create", "--from-readiness", "r.json", "--profile", "software-delivery"])
    assert rc == 2
    assert "omit --profile" in capsys.readouterr().err


def test_create_without_profile_or_readiness_errors(capsys):
    rc = main(["create", "--name", "x"])
    assert rc == 2


def test_module_entrypoint_prints_usage():
    """`python -m intent_packages.factory_cli --help` must emit usage text, not
    merely exit 0: an empty stdout with exit 0 is indistinguishable from a
    `__main__` guard that runs the wrong thing (or nothing at all)."""
    result = subprocess.run(
        [sys.executable, "-m", "intent_packages.factory_cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
