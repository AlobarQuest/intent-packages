import yaml

from intent_packages.factory import journey
from intent_packages.factory.api import OrchestratorApi
from intent_packages.factory.orchestrator_cli import OrchestratorCliError


class FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def emit_intake_payload(self, path, source_repository, idempotency_key):
        self.calls.append((path, source_repository, idempotency_key))
        return self._payload


def _approved_package(tmp_path):
    from intent_packages.factory import scaffolds

    scaffolds.create("software-delivery", "probe", str(tmp_path))
    package_path = tmp_path / "probe" / "package.yaml"
    document = yaml.safe_load(package_path.read_text())
    document["status"] = "approved"
    package_path.write_text(yaml.safe_dump(document, sort_keys=False))
    lineage_path = tmp_path / "probe" / "lineage.yaml"
    lineage = yaml.safe_load(lineage_path.read_text())
    lineage["current_state"] = "approved"
    lineage_path.write_text(yaml.safe_dump(lineage, sort_keys=False))
    return tmp_path / "probe"


def test_submit_refuses_an_unapproved_package(tmp_path, capsys):
    from intent_packages.factory import scaffolds

    scaffolds.create("software-delivery", "probe", str(tmp_path))
    rc = journey.submit(str(tmp_path / "probe"), "AlobarQuest/probe", client=FakeClient({}))
    assert rc == 1
    out = capsys.readouterr()
    assert "approved" in (out.err + out.out)
    assert "intent_packages" in (out.err + out.out)


def test_submit_stages_copies_and_stops(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_API_URL", "https://sds.example")
    copied = {}
    package = _approved_package(tmp_path)
    rc = journey.submit(
        str(package),
        "AlobarQuest/probe",
        client=FakeClient({"idempotency_key": "k", "expected_version": 0}),
        clipboard=lambda text: copied.setdefault("text", text),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "https://sds.example/review/intakes/new" in out
    assert "waiting on your approval" in out
    assert "factory status --revision" in out
    assert '"idempotency_key"' in copied["text"]


def test_submit_never_posts_an_intake(tmp_path, monkeypatch):
    """ADR-0006: intake is a human gate. `submit` must never even construct an
    `OrchestratorApi`, let alone call it. Patching `OrchestratorApi.__init__`
    (the class itself, not one injected instance) forecloses ANY construction
    anywhere in `submit`, including a future regression that constructs its
    own `OrchestratorApi()` internally the way it already does for the
    default `OrchestratorClient`."""
    monkeypatch.setenv("ORCHESTRATOR_API_URL", "https://sds.example")

    def _exploding_init(self, *args, **kwargs):
        raise AssertionError("submit must not construct an OrchestratorApi")

    monkeypatch.setattr(OrchestratorApi, "__init__", _exploding_init)

    package = _approved_package(tmp_path)
    rc = journey.submit(
        str(package),
        "AlobarQuest/probe",
        client=FakeClient({"idempotency_key": "k"}),
        clipboard=lambda text: None,
    )
    assert rc == 0


def test_submit_clipboard_failure_is_a_warning_not_a_lie(tmp_path, capsys):
    """A clipboard callable that fails must still surface the payload, and
    must never claim it was copied."""

    def failing_clipboard(text):
        raise RuntimeError("no clipboard on this session")

    package = _approved_package(tmp_path)
    rc = journey.submit(
        str(package),
        "AlobarQuest/probe",
        client=FakeClient({"idempotency_key": "k"}),
        clipboard=failing_clipboard,
    )
    assert rc == 0
    out = capsys.readouterr()
    assert "no clipboard on this session" in out.err
    assert '"idempotency_key"' in out.err
    assert "copied to your clipboard" not in out.out


def test_submit_reports_orchestrator_cli_errors_cleanly(tmp_path, capsys):
    """`emit_intake_payload` failing (binary missing, or the local
    emit-intake-payload subprocess refusing the package for its own reasons,
    e.g. no matching lineage approval) must be a clean `submit failed:`, not a
    raw traceback."""

    class ExplodingClient:
        def emit_intake_payload(self, path, source_repository, idempotency_key):
            raise OrchestratorCliError("no lineage approval matches the canonical hash")

    package = _approved_package(tmp_path)
    rc = journey.submit(
        str(package),
        "AlobarQuest/probe",
        client=ExplodingClient(),
        clipboard=lambda text: None,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "submit failed:" in err
    assert "no lineage approval matches the canonical hash" in err
