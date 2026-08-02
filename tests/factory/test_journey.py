import httpx
import pytest
import yaml

from intent_packages.factory import journey, reads
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

    scaffolds.create("software-delivery", "probe", str(tmp_path), reach=("source_repository",))
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

    scaffolds.create("software-delivery", "probe", str(tmp_path), reach=("source_repository",))
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
            # Real `PackageIntakeResponse` field names -- there is no `state`.
            return {
                "id": revision_id,
                "package_id": "probe",
                "revision": 1,
                "source_repository": "AlobarQuest/probe",
                "status_at_intake": "approved",
                "intake_source": "review_form",
                "profile": "software-delivery",
                "acceptance_criteria": [],
            }

        def list_proposals(self, revision_id):
            return [{"id": "p1", "state": "approved"}]

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

        def history(self, unit_id):
            return []

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


def test_evidence_with_unit_key_uses_the_unit_pack_as_json(capsys):
    """The most common invocation: a known --unit-key, no --markdown. Must hit
    `evidence_pack` (not `evidence_pack_markdown` or `revision_evidence_pack`)
    and print it as JSON."""
    called = {}

    def evidence_pack(unit_id):
        called["unit"] = unit_id
        return {"unit_id": unit_id, "acceptance_criteria": []}

    rc = journey.evidence("r1", unit_key="bump-fastapi", api=_fake_api(evidence_pack=evidence_pack))
    assert rc == 0
    assert called["unit"] == "u1"
    out = capsys.readouterr().out
    assert '"unit_id": "u1"' in out


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
                    # The REAL `TraceabilityPrHop`: `{pr_number, head_sha}` and
                    # nothing else. This fixture used to say
                    # `{"number": 7, "state": "open"}` -- a shape production
                    # never sends, in the same repo where three defects had
                    # already come from fixtures calibrated to invented shapes.
                    "pr": {"pr_number": 7, "head_sha": "abc1234def"},
                },
            ],
        }

    units = reads.units_for(_fake_api(traceability=traceability), "r1")
    assert [u["unit_key"] for u in units] == ["k1", "k2"]
    assert "pr" not in units[0]
    assert units[1]["pr"] == {"pr_number": 7, "head_sha": "abc1234def"}


def test_status_drives_a_real_api_with_the_expected_methods_and_paths(capsys):
    """Wire-fidelity canary: a REAL `OrchestratorApi` over a mock transport --
    not a duck-typed fake (same reasoning as `test_decompose.py`'s
    `_api_returning_intake`). The eighteen behavioural tests above stay on the
    duck-typed `_fake_api()` fixture on purpose -- converting all of them to
    stateful `MockTransport` routing would burden output-formatting tests with
    HTTP plumbing for no additional protection. This one test buys back the
    guarantee that `RevisionApi`'s method names, `traceability`'s query
    params, AND the response SHAPES are what the real API actually returns.

    Fix round 1/5, Critical 4/Important 1: this test used to mock BOTH the
    decomposition-proposals route and the history route as JSON OBJECTS
    (`{"items": [...]}` / `{"events": [...]}`) -- calibrated to a fiction,
    since both routes are bare JSON arrays on the real orchestrator
    (`response_model=list[...]`). A test built specifically to prove wire
    fidelity was proving the opposite of what it claimed. Both routes below
    now return bare arrays, non-empty, so `_print_proposals`/`_print_units`
    actually render real content sourced from the real shape -- not just
    avoid crashing on an empty list either way.

    A2: that fix was applied to the two ARRAY routes and the intake route was
    left fictional -- `{"id": "r1", "state": "intaken"}`, where
    `PackageIntakeResponse` has no `state` field at all. The canary therefore
    kept vouching for the one line that printed `None` on every production run.
    The intake body below is the real schema's required-field set, taken from
    the live openapi.json, and the assertions read the fields that exist."""
    seen = []

    def handler(request):
        path = request.url.path
        seen.append((request.method, path))
        if path == "/api/v1/package-intakes/r1":
            # Every REQUIRED property of `PackageIntakeResponse`, in the real
            # spelling. `state` is deliberately absent because the schema has
            # no such field -- adding it back would restore the fiction.
            return httpx.Response(
                200,
                json={
                    "id": "r1",
                    "package_id": "wsp29-probe",
                    "source_repository": "AlobarQuest/intent-packages",
                    "revision": 1,
                    "content_hash": "sha256:abc",
                    "source_path": "packages/wsp29-probe",
                    "source_commit": "deadbeef",
                    "approved_by": "devon",
                    "approved_at": "2026-07-29T00:00:00Z",
                    "approval_event_id": "ev-1",
                    "approval_ledger_commit": None,
                    "profile": "software-delivery",
                    "status_at_intake": "approved",
                    "intake_source": "review_form",
                    "verification_mode": None,
                    "verification_limitations": None,
                    "enforcement_snapshot": {},
                    "authority_fingerprint": "fp-rev",
                    "authority": None,
                    "follow_up": None,
                    "registry_version": 1,
                    "registered_by": "devon",
                    "registered_at": "2026-07-29T00:00:00Z",
                    "acceptance_criteria": [
                        {
                            "id": "11111111-1111-1111-1111-111111111111",
                            "ac_id": "AC-001",
                            "condition": "the named check passes",
                            "evidence_type": "automated_check",
                            "evidence": "a GitHub named check on the PR head",
                            "approver": "policy",
                        }
                    ],
                },
            )
        if path == "/api/v1/package-intakes/r1/decomposition-proposals":
            return httpx.Response(200, json=[{"id": "p1", "state": "pending"}])
        if path == "/api/v1/traceability":
            assert dict(request.url.params) == {"revision_id": "r1"}
            return httpx.Response(
                200,
                json={
                    "anchor": {"kind": "revision"},
                    "chains": [
                        {
                            "unit": {
                                "id": "u1",
                                "unit_key": "bump-fastapi",
                                "title": "Update fastapi",
                                "state": "ready",
                                "authority_fingerprint": "fp1",
                                "authority_approved_by": "devon",
                                "authority_decision": "approved",
                            },
                            "pr": None,
                        }
                    ],
                },
            )
        if path == "/api/v1/work-units/u1/history":
            return httpx.Response(
                200,
                json=[
                    {"action": "unit.claimed", "payload": {}, "id": "e1"},
                    {
                        "action": "dispatch.dispatched",
                        "payload": {"runner_attempt": 2, "dispatch_record_id": "d-2"},
                        "id": "e2",
                    },
                ],
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    api = OrchestratorApi(
        "https://sds.example",
        transport=httpx.MockTransport(handler),
        token_resolver=lambda role: "t",
    )
    rc = journey.status("r1", api=api)
    assert rc == 0
    assert ("GET", "/api/v1/package-intakes/r1") in seen
    assert ("GET", "/api/v1/package-intakes/r1/decomposition-proposals") in seen
    assert ("GET", "/api/v1/traceability") in seen
    assert ("GET", "/api/v1/work-units/u1/history") in seen
    out = capsys.readouterr().out
    assert "p1: pending" in out
    # A2: real intake fields, rendered. `None` anywhere on this line would mean
    # the client is reading a field the schema does not have.
    assert "intake r1: package 'wsp29-probe' revision 1" in out
    assert "status_at_intake='approved'" in out
    assert "intake_source='review_form'" in out
    assert "None" not in out
    # C2: spec §3's latest dispatch ordinal, from the same single history read.
    assert "dispatch: latest ordinal 2" in out


def test_status_names_the_real_revision_not_a_placeholder(capsys, monkeypatch):
    """C3. The two next-action lines that name a command used to emit a literal
    `<rev>` -- so the "front door" printed a command the operator had to
    hand-edit, using an id `status` was already holding. Asserted for BOTH of
    them (draft-with-authority -> `factory ready`, ready -> `factory dispatch`)."""
    monkeypatch.delenv("FACTORY_REVISION", raising=False)

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
                        "authority_approved_by": "devon",
                        "authority_decision": "approved",
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
                    "pr": None,
                },
            ],
        }

    rc = journey.status("rev-abc-123", api=_fake_api(traceability=traceability))
    assert rc == 0
    out = capsys.readouterr().out
    assert "<rev>" not in out
    assert "factory ready --revision rev-abc-123 --unit-key k1" in out
    assert "factory dispatch --revision rev-abc-123 --unit-key k2" in out


# `orchestrator/kernel/states.py::WorkUnitState`, read from the orchestrator's
# own tree. This test's whole job is to fail when that enum grows a member the
# CLI's table does not name, so it is spelled out rather than derived.
ALL_WORK_UNIT_STATES = (
    "draft",
    "ready",
    "claimed",
    "executing",
    "blocked",
    "awaiting_approval",
    "submitted",
    "verifying",
    "awaiting_review",
    "revision_required",
    "completed",
    "failed",
    "cancelled",
)


def test_the_next_action_table_names_every_work_unit_state():
    """C3. The table used to cover 2 of 13 states -- and `submitted`, the state
    `factory verify` exists for, was not one of them; everything else fell into
    a bare `state <x>: <link>`."""
    assert set(journey._STATE_NEXT_ACTIONS) | {"draft"} == set(ALL_WORK_UNIT_STATES)


@pytest.mark.parametrize("state", ALL_WORK_UNIT_STATES)
def test_every_state_gets_an_actionable_or_honestly_empty_line(state, capsys):
    """Every state must produce a line that either names a runnable command, a
    browser link, or says plainly that there is nothing to do -- and none may
    leak a `{...}` placeholder from the template."""

    def traceability(*, revision_id=None, work_unit_id=None):
        return {
            "anchor": {"kind": "revision"},
            "chains": [
                {
                    "unit": {
                        "id": "u1",
                        "unit_key": "k1",
                        "state": state,
                        "authority_fingerprint": "fp1",
                        "authority_approved_by": None,
                        "authority_decision": None,
                    },
                    "pr": None,
                }
            ],
        }

    assert journey.status("rev-1", api=_fake_api(traceability=traceability)) == 0
    line = next(
        raw.strip()
        for raw in capsys.readouterr().out.splitlines()
        if raw.strip().startswith("next:")
    )
    assert "{" not in line and "}" not in line
    assert "<rev>" not in line
    assert any(
        marker in line
        for marker in ("factory ", "/review/units/u1", "nothing to do", "in progress")
    ), line


def test_an_unknown_state_says_the_client_is_behind(capsys):
    """A state the orchestrator adds later must not silently render as an empty
    next action -- the line has to say the table is stale and still give a link."""

    def traceability(*, revision_id=None, work_unit_id=None):
        return {
            "anchor": {"kind": "revision"},
            "chains": [
                {
                    "unit": {
                        "id": "u1",
                        "unit_key": "k1",
                        "state": "quiesced",
                        "authority_fingerprint": "fp1",
                        "authority_approved_by": None,
                        "authority_decision": None,
                    },
                    "pr": None,
                }
            ],
        }

    assert journey.status("rev-1", api=_fake_api(traceability=traceability)) == 0
    out = capsys.readouterr().out
    assert "not a known WorkUnitState" in out
    assert "/review/units/u1" in out


# -- the authority-approval line: both branches ------------------------------


def test_status_reports_who_recorded_the_authority_approval(capsys):
    """B3. This line is the ONLY output distinguishing a real authority approval
    from the generic `/review` action button -- the exact failure mode the
    next-action logic exists for -- and it could be inverted with no test
    failing: both branches contain the word "authority", which was all the two
    existing tests asserted."""
    rc = journey.status("r1", api=_fake_api())
    assert rc == 0
    out = capsys.readouterr().out
    assert "authority approved by devon (fp1)" in out
    assert "no authority approval recorded" not in out


def test_status_reports_a_missing_authority_approval_as_missing(capsys):
    """The other half of B3: with `authority_decision` absent, the line must say
    so and must NOT claim an approver."""

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
                }
            ],
        }

    rc = journey.status("r1", api=_fake_api(traceability=traceability))
    assert rc == 0
    out = capsys.readouterr().out
    assert "no authority approval recorded" in out
    assert "authority approved by" not in out
