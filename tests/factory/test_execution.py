from intent_packages.factory import execution


def _fake_api(**overrides):
    class FakeApi:
        def get_intake(self, revision_id):
            return {"id": revision_id, "state": "intaken", "acceptance_criteria": []}

        def list_proposals(self, revision_id):
            return {"items": []}

        def traceability(self, *, revision_id=None, work_unit_id=None):
            return {
                "anchor": {"kind": "revision"},
                "chains": [
                    {
                        "unit": {
                            "id": "u1",
                            "unit_key": "bump-fastapi",
                            "state": "ready",
                            "authority_fingerprint": "fp1",
                            "authority_approved_by": "devon",
                            "authority_decision": "approved",
                        },
                        "pr": None,
                    }
                ],
            }

        def history(self, unit_id):
            return {"events": []}

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
                        "version": 1,
                        "attempt_count": 0,
                    }
                ],
                "release_bindings": [],
            }

        def dispatch(self, unit_id, payload):
            return {"id": "d-new", "status": "dispatched", "reason_code": None}

    api = FakeApi()
    for name, value in overrides.items():
        setattr(api, name, value)
    return api


def _history_with_dispatch(runner_attempt, dispatch_record_id):
    def history(unit_id):
        return {
            "events": [
                {
                    "action": "dispatch.dispatched",
                    "payload": {
                        "runner_attempt": runner_attempt,
                        "dispatch_record_id": dispatch_record_id,
                    },
                },
                {"action": "unit.claimed", "payload": {}},
            ]
        }

    return history


# -- next_runner_attempt -----------------------------------------------------


def test_next_runner_attempt_uses_the_max_of_both_counters():
    api = _fake_api(history=_history_with_dispatch(2, "d-2"))
    assert execution.next_runner_attempt(api, "u1", attempt_count=1) == 3
    assert execution.next_runner_attempt(api, "u1", attempt_count=5) == 6


def test_next_runner_attempt_is_one_when_never_dispatched():
    assert execution.next_runner_attempt(_fake_api(), "u1", attempt_count=0) == 1


def test_next_runner_attempt_reads_the_action_field_not_type():
    """The real orchestrator event field is `action` (`EventResponse.action`),
    never `type`. An event carrying `type` instead of `action` must be
    invisible to the scan -- proving the matcher keys on the field that is
    actually on the wire, not a plausible-looking guess."""

    def history(unit_id):
        return {"events": [{"type": "dispatch.dispatched", "payload": {"runner_attempt": 9}}]}

    assert execution.next_runner_attempt(_fake_api(history=history), "u1", attempt_count=0) == 1


def test_next_runner_attempt_ignores_non_dispatch_events():
    def history(unit_id):
        return {
            "events": [
                {"action": "unit.claimed", "payload": {}},
                {"action": "work_unit.transitioned", "payload": {"version": 3}},
            ]
        }

    assert execution.next_runner_attempt(_fake_api(history=history), "u1", attempt_count=2) == 3


# -- dispatch: the no-op detection -------------------------------------------


def test_dispatch_reports_a_reused_record_id_as_failure(capsys):
    """A reused ordinal returns the EXISTING record with HTTP 200 and
    status='dispatched', triggering no workflow_dispatch. Only a new record id
    proves a dispatch happened."""

    def dispatch(unit_id, payload):
        return {"id": "d-old", "status": "dispatched", "reason_code": None}

    api = _fake_api(history=_history_with_dispatch(2, "d-old"), dispatch=dispatch)
    rc = execution.dispatch("r1", "bump-fastapi", api=api)
    assert rc == 1
    assert "no-op" in capsys.readouterr().err


def test_dispatch_accepts_a_new_record_id(capsys):
    def dispatch(unit_id, payload):
        return {"id": "d-new", "status": "dispatched", "reason_code": None}

    api = _fake_api(history=_history_with_dispatch(2, "d-old"), dispatch=dispatch)
    rc = execution.dispatch("r1", "bump-fastapi", api=api)
    assert rc == 0
    out = capsys.readouterr().out
    assert "d-new" in out
    assert "runner_attempt 3" in out


def test_dispatch_no_op_check_actually_inspects_the_response_id():
    """Guards against a no-op detector that always returns 1 (or always 0)
    regardless of the response: the SAME prior_dispatch_id, run through BOTH a
    colliding and a non-colliding response, must produce different return
    codes. A stub that ignores `response["id"]` cannot pass both halves."""
    history = _history_with_dispatch(2, "d-old")

    def dispatch_reused(unit_id, payload):
        return {"id": "d-old", "status": "dispatched", "reason_code": None}

    def dispatch_fresh(unit_id, payload):
        return {"id": "d-new", "status": "dispatched", "reason_code": None}

    reused_rc = execution.dispatch(
        "r1", "bump-fastapi", api=_fake_api(history=history, dispatch=dispatch_reused)
    )
    fresh_rc = execution.dispatch(
        "r1", "bump-fastapi", api=_fake_api(history=history, dispatch=dispatch_fresh)
    )
    assert (reused_rc, fresh_rc) == (1, 0)


def test_dispatch_posts_the_computed_runner_attempt_and_in_flight_version():
    seen = {}

    def dispatch(unit_id, payload):
        seen["payload"] = payload
        return {"id": "d-new", "status": "dispatched", "reason_code": None}

    def in_flight_units():
        return {
            "units": [
                {"work_unit_id": "u1", "unit_key": "bump-fastapi", "version": 7, "attempt_count": 4}
            ],
            "release_bindings": [],
        }

    api = _fake_api(
        history=_history_with_dispatch(5, "d-5"),
        in_flight_units=in_flight_units,
        dispatch=dispatch,
    )
    rc = execution.dispatch("r1", "bump-fastapi", api=api)
    assert rc == 0
    assert seen["payload"]["expected_version"] == 7
    assert seen["payload"]["runner_attempt"] == 6  # max(4, 5) + 1


def test_dispatch_refuses_a_unit_that_is_not_in_flight(capsys):
    def in_flight_units():
        return {"units": [], "release_bindings": []}

    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(in_flight_units=in_flight_units))
    assert rc == 1
    err = capsys.readouterr().err
    assert "not in flight" in err


def test_dispatch_reports_api_errors_cleanly(capsys):
    from intent_packages.factory.api import ApiError

    def dispatch(unit_id, payload):
        raise ApiError("work_unit_not_ready", "unit is not ready")

    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(dispatch=dispatch))
    assert rc == 1
    assert "dispatch failed: work_unit_not_ready" in capsys.readouterr().err


def test_dispatch_unknown_unit_key_lists_the_real_ones(capsys):
    rc = execution.dispatch("r1", "nope", api=_fake_api())
    assert rc == 1
    err = capsys.readouterr().err
    assert "bump-fastapi" in err
    assert "nope" in err


def test_dispatch_requires_a_revision_when_none_given(monkeypatch, capsys):
    monkeypatch.delenv("FACTORY_REVISION", raising=False)
    rc = execution.dispatch("", "bump-fastapi", api=_fake_api())
    assert rc == 2
    err = capsys.readouterr().err
    assert "--revision" in err
    assert "FACTORY_REVISION" in err


# -- ready --------------------------------------------------------------


def test_ready_uses_the_version_probe():
    seen = {}

    def resolve_version(unit_id, *, probe, command="ready"):
        seen["probe"] = (probe, command)
        return 3

    def command(unit_id, command_name, payload):
        seen["command"] = (command_name, payload["expected_version"])
        return {"state": "ready"}

    api = _fake_api(resolve_version=resolve_version, command=command)
    assert execution.ready("r1", "bump-fastapi", api=api) == 0
    assert seen["command"] == ("ready", 3)
    assert seen["probe"][1] == "ready"


def test_ready_reports_api_errors_cleanly(capsys):
    from intent_packages.factory.api import ApiError

    def resolve_version(unit_id, *, probe, command="ready"):
        raise ApiError("work_unit_not_found", "no such unit")

    rc = execution.ready("r1", "bump-fastapi", api=_fake_api(resolve_version=resolve_version))
    assert rc == 1
    assert "ready failed: work_unit_not_found" in capsys.readouterr().err


def test_ready_unknown_unit_key_lists_the_real_ones(capsys):
    rc = execution.ready("r1", "nope", api=_fake_api())
    assert rc == 1
    err = capsys.readouterr().err
    assert "bump-fastapi" in err
    assert "nope" in err


def test_ready_requires_a_revision_when_none_given(monkeypatch, capsys):
    monkeypatch.delenv("FACTORY_REVISION", raising=False)
    rc = execution.ready("", "bump-fastapi", api=_fake_api())
    assert rc == 2
    err = capsys.readouterr().err
    assert "--revision" in err
    assert "FACTORY_REVISION" in err


def test_ready_falls_back_to_the_env_revision(monkeypatch):
    monkeypatch.setenv("FACTORY_REVISION", "r-env")
    assert execution.ready("", "bump-fastapi", api=_fake_api()) == 0
