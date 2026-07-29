import yaml

from intent_packages.factory import journey


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
    """ADR-0006: intake is a human gate. This must not reach the API at all."""
    monkeypatch.setenv("ORCHESTRATOR_API_URL", "https://sds.example")

    class ExplodingApi:
        def __getattr__(self, name):
            raise AssertionError(f"submit must not call the API ({name})")

    package = _approved_package(tmp_path)
    rc = journey.submit(
        str(package),
        "AlobarQuest/probe",
        api=ExplodingApi(),
        client=FakeClient({"idempotency_key": "k"}),
        clipboard=lambda text: None,
    )
    assert rc == 0
