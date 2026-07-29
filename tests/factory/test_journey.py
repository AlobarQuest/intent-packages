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


def _fake_api(**overrides):
    class FakeApi:
        def get_intake(self, revision_id):
            return {"id": revision_id, "state": "intaken", "acceptance_criteria": []}

        def list_proposals(self, revision_id):
            return {"items": [{"id": "p1", "state": "approved"}]}

        def traceability(self, *, revision_id=None, work_unit_id=None):
            return {
                "anchor": {"kind": "revision"},
                "chains": [
                    {
                        "unit": {
                            "id": "u1",
                            "unit_key": "bump-fastapi",
                            "state": "draft",
                            "authority_fingerprint": "fp1",
                            "authority_approved_by": "devon",
                            "authority_decision": "approved",
                        },
                        "pr": None,
                    }
                ],
            }

        def readiness(self, unit_id):
            return {"status": "ready", "conditions": []}

        def history(self, unit_id):
            return {"events": []}

        def evidence_pack(self, unit_id):
            return {"unit_id": unit_id}

        def revision_evidence_pack(self, revision_id):
            return {"revision_id": revision_id}

        def evidence_pack_markdown(self, unit_id):
            return f"# evidence pack for {unit_id}"

    api = FakeApi()
    for name, value in overrides.items():
        setattr(api, name, value)
    return api


def test_status_flags_the_draft_with_authority_trap(capsys):
    rc = journey.status("r1", api=_fake_api())
    assert rc == 0
    out = capsys.readouterr().out
    assert "bump-fastapi" in out
    assert "factory ready" in out


def test_status_flags_an_action_approval_as_insufficient(capsys):
    def traceability(*, revision_id=None, work_unit_id=None):
        return {
            "anchor": {"kind": "revision"},
            "chains": [
                {
                    "unit": {
                        "id": "u1",
                        "unit_key": "k",
                        "state": "draft",
                        "authority_fingerprint": "fp1",
                        "authority_approved_by": None,
                        "authority_decision": None,
                    },
                    "pr": None,
                }
            ],
        }

    journey.status("r1", api=_fake_api(traceability=traceability))
    out = capsys.readouterr().out
    assert "authority" in out.lower()
    assert "/review/units/u1" in out


def test_evidence_markdown_uses_the_markdown_route(capsys):
    called = {}

    def evidence_pack_markdown(unit_id):
        called["unit"] = unit_id
        return "# pack"

    journey.evidence(
        "r1",
        unit_key="bump-fastapi",
        markdown=True,
        api=_fake_api(evidence_pack_markdown=evidence_pack_markdown),
    )
    assert called["unit"] == "u1"
    assert "# pack" in capsys.readouterr().out


def test_evidence_without_unit_key_uses_the_revision_pack(capsys):
    called = {}

    def revision_evidence_pack(revision_id):
        called["revision"] = revision_id
        return {"revision": revision_id}

    journey.evidence("r1", api=_fake_api(revision_evidence_pack=revision_evidence_pack))
    assert called["revision"] == "r1"


def test_unknown_unit_key_lists_the_real_ones(capsys):
    rc = journey.evidence("r1", unit_key="nope", api=_fake_api())
    assert rc == 1
    assert "bump-fastapi" in capsys.readouterr().err


def test_status_requires_a_revision_when_none_given(capsys, monkeypatch):
    monkeypatch.delenv("FACTORY_REVISION", raising=False)
    rc = journey.status("", api=_fake_api())
    assert rc == 2
    err = capsys.readouterr().err
    assert "--revision" in err
    assert "FACTORY_REVISION" in err


def test_status_falls_back_to_the_env_revision(capsys, monkeypatch):
    monkeypatch.setenv("FACTORY_REVISION", "r-env")
    rc = journey.status("", api=_fake_api())
    assert rc == 0
    assert "r-env" in capsys.readouterr().out


def test_evidence_requires_a_revision_when_none_given(capsys, monkeypatch):
    monkeypatch.delenv("FACTORY_REVISION", raising=False)
    rc = journey.evidence("", api=_fake_api())
    assert rc == 2
    err = capsys.readouterr().err
    assert "--revision" in err
    assert "FACTORY_REVISION" in err


def test_evidence_markdown_without_unit_key_is_rejected(capsys):
    rc = journey.evidence("r1", markdown=True, api=_fake_api())
    assert rc == 1
    assert "--unit-key" in capsys.readouterr().err


def test_status_wait_times_out_when_nothing_changes(capsys, monkeypatch):
    counter = {"t": 0.0}

    def fake_monotonic():
        counter["t"] += 1
        return counter["t"]

    monkeypatch.setattr(journey.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(journey.time, "sleep", lambda seconds: None)
    rc = journey.status("r1", wait=True, poll_seconds=0, timeout_seconds=2, api=_fake_api())
    assert rc == 0
    assert "no state change" in capsys.readouterr().out


def test_status_wait_stops_when_a_unit_changes(capsys, monkeypatch):
    calls = {"n": 0}

    def traceability(*, revision_id=None, work_unit_id=None):
        calls["n"] += 1
        state = "draft" if calls["n"] == 1 else "ready"
        return {
            "anchor": {"kind": "revision"},
            "chains": [
                {
                    "unit": {
                        "id": "u1",
                        "unit_key": "bump-fastapi",
                        "state": state,
                        "authority_fingerprint": "fp1",
                        "authority_approved_by": "devon",
                        "authority_decision": "approved",
                    },
                    "pr": None,
                }
            ],
        }

    counter = {"t": 0.0}

    def fake_monotonic():
        counter["t"] += 1
        return counter["t"]

    monkeypatch.setattr(journey.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(journey.time, "sleep", lambda seconds: None)
    rc = journey.status(
        "r1",
        wait=True,
        poll_seconds=0,
        timeout_seconds=100,
        api=_fake_api(traceability=traceability),
    )
    assert rc == 0
    assert "state changed" in capsys.readouterr().out


def test_status_wait_handles_keyboard_interrupt(capsys, monkeypatch):
    def raising_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(journey.time, "sleep", raising_sleep)
    rc = journey.status("r1", wait=True, poll_seconds=0, timeout_seconds=100, api=_fake_api())
    assert rc == 130
    assert "interrupted" in capsys.readouterr().err


def test_units_for_derives_flat_unit_dicts_with_pr_when_present():
    def traceability(*, revision_id=None, work_unit_id=None):
        return {
            "anchor": {"kind": "revision"},
            "chains": [
                {
                    "unit": {
                        "id": "u1",
                        "unit_key": "k1",
                        "state": "draft",
                        "authority_fingerprint": "fp1",
                        "authority_approved_by": None,
                        "authority_decision": None,
                    },
                    "pr": None,
                },
                {
                    "unit": {
                        "id": "u2",
                        "unit_key": "k2",
                        "state": "ready",
                        "authority_fingerprint": "fp2",
                        "authority_approved_by": "devon",
                        "authority_decision": "approved",
                    },
                    "pr": {"number": 7, "state": "open"},
                },
            ],
        }

    units = journey.units_for(_fake_api(traceability=traceability), "r1")
    assert [u["unit_key"] for u in units] == ["k1", "k2"]
    assert "pr" not in units[0]
    assert units[1]["pr"] == {"number": 7, "state": "open"}
