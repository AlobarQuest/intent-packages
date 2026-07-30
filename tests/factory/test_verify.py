import httpx
import pytest

from intent_packages.factory import verify as verify_module
from intent_packages.factory.api import ApiError, OrchestratorApi


def _fake_api(**overrides):
    """A `VerifyApi`-conforming double. Implements every method the Protocol
    requires (mirrors `test_execution.py`'s `_fake_api`, for the same reason:
    pyright checks a passed argument against the full structural `Protocol`,
    not just the methods a given test happens to exercise) with defaults that
    represent a SUBMITTED unit that was genuinely dispatched once, has an
    armed PR binding with no divergence, and is ready to be verified.
    """

    class FakeApi:
        def get_intake(self, revision_id):
            return {"id": revision_id, "state": "intaken", "acceptance_criteria": []}

        def list_proposals(self, revision_id):
            return []

        def traceability(self, *, revision_id=None, work_unit_id=None):
            return {
                "anchor": {"kind": "revision"},
                "chains": [
                    {
                        "unit": {
                            "id": "u1",
                            "unit_key": "bump-fastapi",
                            "state": "submitted",
                            "authority_fingerprint": "fp1",
                            "authority_approved_by": "devon",
                            "authority_decision": "approved",
                        },
                        "pr": None,
                    }
                ],
            }

        def history(self, unit_id):
            return [
                {
                    "action": "dispatch.dispatched",
                    "payload": {
                        "runner_attempt": 1,
                        "dispatch_record_id": "d1",
                        "target_repository": "AlobarQuest/brain",
                    },
                },
                {"action": "unit.claimed", "payload": {}},
            ]

        def evidence_pack(self, unit_id):
            return {"unit_id": unit_id}

        def revision_evidence_pack(self, revision_id):
            return {"revision_id": revision_id}

        def evidence_pack_markdown(self, unit_id):
            return f"# evidence pack for {unit_id}"

        def resolve_version(self, unit_id, *, probe, command="ready"):
            return 0

        def command(self, unit_id, command_name, payload):
            return {"state": "ready", "version": payload["expected_version"] + 1}

        def in_flight_units(self):
            return {
                "units": [
                    {
                        "work_unit_id": "u1",
                        "unit_key": "bump-fastapi",
                        "state": "submitted",
                        "version": 5,
                        "attempt_count": 1,
                        "work_package_revision_id": "r1",
                        "pr_number": 12,
                        "head_sha": "abc1234def",
                        "verification_read_head_sha": "abc1234def",
                    }
                ],
                "release_bindings": [],
            }

        def dispatch(self, unit_id, payload):
            return {"id": "d-new", "status": "dispatched", "reason_code": None}

        def named_check(self, unit_id, payload):
            return {"id": "e1"}

        def verify(self, unit_id, payload):
            return {
                "unit_id": unit_id,
                "state": "awaiting_review",
                "version": 6,
                "result": "awaiting_review",
                "evaluations": [
                    {
                        "ac_id": "AC-001",
                        "evidence_type": "automated_check",
                        "status": "passed",
                        "outcome": "passed",
                        "evidence_id": "e1",
                        "finding_evidence_id": None,
                        "adjudication_id": "adj-1",
                        "reason": "named-check evidence matched",
                    }
                ],
            }

    api = FakeApi()
    for name, value in overrides.items():
        setattr(api, name, value)
    return api


# -- parse_assertion / build_assertions (pure functions) ---------------------


def test_parse_assertion():
    assert verify_module.parse_assertion("collected=295:295") == {
        "name": "collected",
        "expected": "295",
        "observed": "295",
    }


def test_parse_assertion_rejects_a_malformed_value():
    with pytest.raises(ValueError):
        verify_module.parse_assertion("collected")


def test_assertions_are_capped_at_32():
    with pytest.raises(ValueError):
        verify_module.build_assertions([f"n{i}=1:1" for i in range(33)])


def test_build_assertions_rejects_an_empty_list():
    """Fix round 1/5, Important 1. `assertions` has `minItems: 1` on
    `VerifierNamedCheckEvidenceCommandModel` -- the documented minimum
    invocation (no `--assert` at all) must refuse locally, not sail through
    to a 422 after three wasted reads."""
    with pytest.raises(ValueError, match="at least 1"):
        verify_module.build_assertions([])


def test_build_assertions_rejects_a_duplicate_name():
    """Fix round 1/5, Minor 9. The server's own evaluator rejects a repeated
    assertion name (`services/verifier_evaluators.py::_named_check_result`);
    refusing it locally saves the same round trip."""
    with pytest.raises(ValueError, match="duplicate"):
        verify_module.build_assertions(["a=1:1", "a=2:2"])


def test_build_assertions_parses_every_value():
    assert verify_module.build_assertions(["a=1:1", "b=x:y"]) == [
        {"name": "a", "expected": "1", "observed": "1"},
        {"name": "b", "expected": "x", "observed": "y"},
    ]


# -- verify: the named-check body is fully derived ---------------------------


def test_named_check_body_is_fully_derived():
    """`dispatch_id`/`repository` come from the latest `dispatch.dispatched`
    event, NOT from `evidence_pack` (the brief's now-corrected table); `pr_number`
    and `head_sha` come from `in-flight-units`, NOT from `traceability`'s `pr`
    hop."""
    seen = {}

    def named_check(unit_id, payload):
        seen["named_check"] = payload
        return {"id": "e1"}

    def verify_call(unit_id, payload):
        seen["verify"] = payload
        return {
            "unit_id": unit_id,
            "state": "awaiting_review",
            "version": 6,
            "result": "awaiting_review",
            "evaluations": [],
        }

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="https://github.com/AlobarQuest/brain/actions/runs/99",
        assertions=["collected=295:295"],
        api=_fake_api(named_check=named_check, verify=verify_call),
    )
    assert rc == 0
    body = seen["named_check"]
    assert body["dispatch_id"] == "d1"
    assert body["repository"] == "AlobarQuest/brain"
    assert body["pr_number"] == 12
    assert body["head_sha"] == "abc1234def"
    assert body["pr_url"] == "https://github.com/AlobarQuest/brain/pull/12"
    assert body["ac_id"] == "AC-001"
    assert body["work_package_revision_id"] == "r1"
    assert body["expected_version"] == 5
    assert body["check_name"] == "Quality"
    assert body["conclusion"] == "success"
    assert body["run_id"] == "99"
    assert body["assertions"] == [{"name": "collected", "expected": "295", "observed": "295"}]
    assert seen["verify"]["expected_version"] == 5


def test_named_check_uses_the_armed_head_sha_when_it_agrees_with_the_current_one():
    """`InFlightUnitModel` carries BOTH `head_sha` (mutable, worker-written)
    and `verification_read_head_sha` (the alarm-arming field, frozen at
    SUBMIT). When the two agree (the common case), the armed one is what
    flows into the payload."""
    seen = {}

    def named_check(unit_id, payload):
        seen["named_check"] = payload
        return {"id": "e1"}

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(named_check=named_check),
    )
    assert rc == 0
    assert seen["named_check"]["head_sha"] == "abc1234def"


def test_refuses_when_head_has_diverged_since_submit(capsys):
    """Fix round 1/5, Important 2. When `head_sha` (mutable) and
    `verification_read_head_sha` (armed) disagree -- a push landed after
    submit -- no single payload value can satisfy
    `validate_named_check_bindings`'s check against BOTH fields. Refusing
    locally, by name, replaces a guaranteed round trip to
    `named_check_binding_mismatch`."""

    def in_flight_units():
        return {
            "units": [
                {
                    "work_unit_id": "u1",
                    "unit_key": "bump-fastapi",
                    "state": "submitted",
                    "version": 5,
                    "attempt_count": 1,
                    "work_package_revision_id": "r1",
                    "pr_number": 12,
                    "head_sha": "post-rebase-sha-value",
                    "verification_read_head_sha": "armed-sha-value-7",
                }
            ],
            "release_bindings": [],
        }

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(in_flight_units=in_flight_units),
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "head moved after submit" in err
    assert "armed-sha-value-7" in err
    assert "post-rebase-sha-value" in err


# -- refusals: named reasons, never a guess ----------------------------------


def test_refuses_when_never_dispatched(capsys):
    def history(unit_id):
        return [{"action": "unit.claimed", "payload": {}}]

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(history=history),
    )
    assert rc == 1
    assert "no dispatch.dispatched event" in capsys.readouterr().err


def test_refuses_a_unit_that_is_not_in_flight(capsys):
    def in_flight_units():
        return {"units": [], "release_bindings": []}

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(in_flight_units=in_flight_units),
    )
    assert rc == 1
    assert "not in flight" in capsys.readouterr().err


def test_missing_pr_binding_is_an_actionable_refusal(capsys):
    """The unit is in flight but has no PR binding armed -- `pr_number` and
    `verification_read_head_sha` are absent -- e.g. the worker never opened a
    PR or has not yet submitted."""

    def in_flight_units():
        return {
            "units": [
                {
                    "work_unit_id": "u1",
                    "unit_key": "bump-fastapi",
                    "state": "submitted",
                    "version": 5,
                    "attempt_count": 1,
                    "work_package_revision_id": "r1",
                    "pr_number": None,
                    "head_sha": None,
                    "verification_read_head_sha": None,
                }
            ],
            "release_bindings": [],
        }

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(in_flight_units=in_flight_units),
    )
    assert rc == 1
    assert "pr" in capsys.readouterr().err.lower()


def test_refuses_a_unit_in_a_non_verifiable_state(capsys):
    """Fix round 1/5, Important 5. On the REVISION_REQUIRED -> READY ->
    EXECUTING loop, a stale `pr_number` and armed head both survive from the
    prior cycle -- so their mere presence cannot prove the unit is
    verifiable. Only SUBMITTED/VERIFYING accept named-check evidence
    (`services/verifier_named_check.py::validate_named_check_bindings`)."""

    def in_flight_units():
        return {
            "units": [
                {
                    "work_unit_id": "u1",
                    "unit_key": "bump-fastapi",
                    "state": "executing",
                    "version": 5,
                    "attempt_count": 2,
                    "work_package_revision_id": "r1",
                    "pr_number": 12,
                    "head_sha": "abc1234def",
                    "verification_read_head_sha": "abc1234def",
                }
            ],
            "release_bindings": [],
        }

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(in_flight_units=in_flight_units),
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "executing" in err
    assert "SUBMITTED" in err
    assert "VERIFYING" in err


def test_unknown_unit_key_lists_the_real_ones(capsys):
    rc = verify_module.verify(
        "r1",
        "nope",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(),
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "bump-fastapi" in err
    assert "nope" in err


def test_requires_a_revision_when_none_given(monkeypatch, capsys):
    """`assertions=[]` here is fine even though `build_assertions` now refuses
    an empty list: revision resolution is checked FIRST and returns before
    `build_assertions` is ever called."""
    monkeypatch.delenv("FACTORY_REVISION", raising=False)
    rc = verify_module.verify(
        "",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=[],
        api=_fake_api(),
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "--revision" in err
    assert "FACTORY_REVISION" in err


def test_reports_api_errors_cleanly(capsys):
    def named_check(unit_id, payload):
        raise ApiError("named_check_binding_mismatch", "named check does not match")

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(named_check=named_check),
    )
    assert rc == 1
    assert "verify failed: named_check_binding_mismatch" in capsys.readouterr().err


def test_rejects_too_many_assertions_before_any_network_call():
    seen = {}

    def named_check(unit_id, payload):
        seen["called"] = True
        return {"id": "e1"}

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=[f"n{i}=1:1" for i in range(33)],
        api=_fake_api(named_check=named_check),
    )
    assert rc == 1
    assert "called" not in seen


def test_rejects_empty_assertions_before_any_network_call(capsys):
    seen = {}

    def named_check(unit_id, payload):
        seen["called"] = True
        return {"id": "e1"}

    def history(unit_id):
        seen["history_called"] = True
        return []

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=[],
        api=_fake_api(named_check=named_check, history=history),
    )
    assert rc == 1
    assert "called" not in seen
    assert "history_called" not in seen
    assert "at least 1" in capsys.readouterr().err


def test_rejects_duplicate_assertion_names_before_any_network_call():
    seen = {}

    def named_check(unit_id, payload):
        seen["called"] = True
        return {"id": "e1"}

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["a=1:1", "a=2:2"],
        api=_fake_api(named_check=named_check),
    )
    assert rc == 1
    assert "called" not in seen


# -- verify: prints the outcomes ---------------------------------------------


def test_verify_prints_one_line_per_evaluation(capsys):
    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "awaiting_review" in out
    assert "AC-001: passed (passed)" in out


def test_named_check_is_posted_before_verify():
    order = []

    def named_check(unit_id, payload):
        order.append("named_check")
        return {"id": "e1"}

    def verify_call(unit_id, payload):
        order.append("verify")
        return {
            "unit_id": unit_id,
            "state": "awaiting_review",
            "version": 6,
            "result": "x",
            "evaluations": [],
        }

    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="u",
        assertions=["ok=true:true"],
        api=_fake_api(named_check=named_check, verify=verify_call),
    )
    assert rc == 0
    assert order == ["named_check", "verify"]


# -- against a real OrchestratorApi over a mock transport --------------------


def test_verify_over_the_real_api_with_production_wire_shapes():
    """`history` is a bare JSON array and `in-flight-units` is a JSON object --
    the real wire shapes, not a fixture calibrated to a shape the API never
    sends. Drives a REAL `OrchestratorApi` through `httpx.MockTransport`."""
    seen = []

    def handler(request):
        path = request.url.path
        seen.append((request.method, path))
        if path == "/api/v1/traceability":
            return httpx.Response(
                200,
                json={
                    "anchor": {"kind": "revision"},
                    "chains": [
                        {
                            "unit": {
                                "id": "u1",
                                "unit_key": "bump-fastapi",
                                "state": "submitted",
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
                    {
                        "action": "dispatch.dispatched",
                        "payload": {
                            "runner_attempt": 1,
                            "dispatch_record_id": "d1",
                            "target_repository": "AlobarQuest/brain",
                        },
                    }
                ],
            )
        if path == "/api/v1/in-flight-units":
            return httpx.Response(
                200,
                json={
                    "units": [
                        {
                            "work_unit_id": "u1",
                            "unit_key": "bump-fastapi",
                            "state": "submitted",
                            "version": 5,
                            "attempt_count": 1,
                            "work_package_revision_id": "r1",
                            "pr_number": 12,
                            "head_sha": "abc1234def",
                            "verification_read_head_sha": "abc1234def",
                        }
                    ],
                    "release_bindings": [],
                },
            )
        if path == "/api/v1/work-units/u1/verifier-evidence/named-check":
            return httpx.Response(200, json={"id": "e1"})
        if path == "/api/v1/work-units/u1/verify":
            return httpx.Response(
                200,
                json={
                    "unit_id": "u1",
                    "state": "awaiting_review",
                    "version": 6,
                    "result": "awaiting_review",
                    "evaluations": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    api = OrchestratorApi(
        "https://sds.example",
        transport=httpx.MockTransport(handler),
        token_resolver=lambda role: "t",
    )
    rc = verify_module.verify(
        "r1",
        "bump-fastapi",
        ac_id="AC-001",
        check_name="Quality",
        conclusion="success",
        run_id="99",
        run_url="https://github.com/AlobarQuest/brain/actions/runs/99",
        assertions=["collected=295:295"],
        api=api,
    )
    assert rc == 0
    history_calls = [p for _m, p in seen if p == "/api/v1/work-units/u1/history"]
    assert len(history_calls) == 1
