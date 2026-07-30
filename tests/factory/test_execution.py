import httpx

from intent_packages.factory import execution, reads
from intent_packages.factory.api import OrchestratorApi


def _fake_api(**overrides):
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
            return []

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


def _dispatch_event(action, runner_attempt, dispatch_record_id):
    """One `dispatch.*` history event, in the real orchestrator wire shape:
    `action` (not `type`), `payload.runner_attempt`, `payload.dispatch_record_id`
    (not `dispatch_id`). `history()` itself returns a bare list (fix round
    1/5) -- callers wrap this in a `[...]` themselves."""
    return {
        "action": action,
        "payload": {"runner_attempt": runner_attempt, "dispatch_record_id": dispatch_record_id},
    }


def _history_with_dispatch(runner_attempt, dispatch_record_id):
    def history(unit_id):
        return [
            _dispatch_event("dispatch.dispatched", runner_attempt, dispatch_record_id),
            {"action": "unit.claimed", "payload": {}},
        ]

    return history


# -- next_runner_attempt (pure arithmetic, fix round 2/5) --------------------
#
# Fix round 2/5 changed the signature from `(api, unit_id, attempt_count)` to
# `(attempt_count, latest_runner_attempt)`: `dispatch()` used to call
# `next_runner_attempt` (one `history()` fetch) AND a second helper for the
# no-op guard's record-id set (a second `history()` fetch) -- two reads of
# the same data, and a real TOCTOU window between them. `next_runner_attempt`
# is now a pure function over facts `reads.scan_dispatch_events` already produced
# in ONE scan; `dispatch()` calls that scan once and feeds both outputs
# onward. It is still the actual function `dispatch()` calls for the
# ordinal (Important 2, fix round 1/5) -- it just no longer does its own I/O.


def test_next_runner_attempt_uses_the_max_of_both_counters():
    assert execution.next_runner_attempt(1, 2) == 3
    assert execution.next_runner_attempt(5, 2) == 6


def test_next_runner_attempt_is_one_when_never_dispatched():
    assert execution.next_runner_attempt(0, 0) == 1


# -- reads.scan_dispatch_events (the single history scan) -------------------------


def test_scan_dispatch_events_reads_the_action_field_not_type():
    """The real orchestrator event field is `action` (`EventResponse.action`),
    never `type`. An event carrying `type` instead of `action` must be
    invisible to the scan -- proving the matcher keys on the field that is
    actually on the wire, not a plausible-looking guess."""

    def history(unit_id):
        return [{"type": "dispatch.dispatched", "payload": {"runner_attempt": 9}}]

    latest, ids = reads.scan_dispatch_events(_fake_api(history=history), "u1")
    assert (latest, ids) == (0, frozenset())


def test_scan_dispatch_events_ignores_non_dispatch_events():
    def history(unit_id):
        return [
            {"action": "unit.claimed", "payload": {}},
            {"action": "work_unit.transitioned", "payload": {"version": 3}},
        ]

    latest, ids = reads.scan_dispatch_events(_fake_api(history=history), "u1")
    assert (latest, ids) == (0, frozenset())


def test_scan_dispatch_events_counts_a_skipped_decision_as_a_consumed_ordinal():
    """Fix round 1/5, Critical 2 regression. `DISPATCH_RECORD_STATUSES` is
    `(dispatched, skipped, blocked, failed)`; all four go through
    `_record_dispatch` with the SAME `runner_attempt` under
    `UniqueConstraint("work_unit_id", "runner_attempt")`, and the event
    action is `f"dispatch.{status}"`. A scan that only recognized
    `dispatch.dispatched` would recompute ordinal 1 forever after a skip --
    exactly the concrete failure the review named: a first dispatch with
    the window closed records ordinal 1 as `dispatch.skipped`; re-running
    after opening the window must not offer ordinal 1 again."""

    def history(unit_id):
        return [_dispatch_event("dispatch.skipped", 1, "d-1")]

    latest, ids = reads.scan_dispatch_events(_fake_api(history=history), "u1")
    assert (latest, ids) == (1, frozenset({"d-1"}))


def test_scan_dispatch_events_counts_blocked_and_failed_too():
    def history(unit_id):
        return [
            _dispatch_event("dispatch.blocked", 1, "d-1"),
            _dispatch_event("dispatch.failed", 2, "d-2"),
        ]

    latest, ids = reads.scan_dispatch_events(_fake_api(history=history), "u1")
    assert (latest, ids) == (2, frozenset({"d-1", "d-2"}))


def test_scan_dispatch_events_collects_every_record_id_not_just_the_latest():
    """Fix round 1/5, Critical 1 regression: the record-id set must carry
    EVERY prior dispatch record, not only the one at the highest ordinal."""

    def history(unit_id):
        return [
            _dispatch_event("dispatch.dispatched", 1, "d-1"),
            _dispatch_event("dispatch.dispatched", 2, "d-2"),
        ]

    latest, ids = reads.scan_dispatch_events(_fake_api(history=history), "u1")
    assert (latest, ids) == (2, frozenset({"d-1", "d-2"}))


# -- latest_dispatched_payload (verify()'s canonical-dispatch lookup) -------


def test_latest_dispatched_payload_ignores_a_higher_ordinal_skipped_decision():
    """Fix round 1/5, Important 4. `reads.latest_dispatched_payload` differs from
    `reads.scan_dispatch_events` in exactly two ways: it filters to `dispatched`
    only, and it selects the highest-`runner_attempt` PAYLOAD among those. A
    fixture with only one dispatch event can't exercise either difference --
    this one has two `dispatched` events plus a higher-ordinal `skipped` one
    (the bounded window closing is the orchestrator's normal resting state),
    so deleting the status filter would make this fail."""

    def history(unit_id):
        return [
            _dispatch_event("dispatch.dispatched", 1, "d-1"),
            _dispatch_event("dispatch.dispatched", 2, "d-2"),
            _dispatch_event("dispatch.skipped", 3, "d-3"),
        ]

    payload = reads.latest_dispatched_payload(_fake_api(history=history), "u1")
    assert payload == {"runner_attempt": 2, "dispatch_record_id": "d-2"}


def test_latest_dispatched_payload_is_none_when_only_non_dispatched_outcomes_exist():
    def history(unit_id):
        return [_dispatch_event("dispatch.skipped", 1, "d-1")]

    assert reads.latest_dispatched_payload(_fake_api(history=history), "u1") is None


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
    regardless of the response: the SAME prior history, run through BOTH a
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


def test_dispatch_detects_reuse_of_a_non_latest_prior_id(capsys):
    """Fix round 1/5, Critical 1 regression. The old detector compared the
    response id against only the id at the HIGHEST ordinal. But the
    orchestrator hands back the record at the REQUESTED ordinal, and under
    `UniqueConstraint("work_unit_id", "runner_attempt")` a correctly-computed
    fresh ordinal is always a fresh row -- so the only way a reused id can
    come back is a client that (re-)requests an ordinal that was already
    used, and the record it gets back is THAT ordinal's record, not
    necessarily the most recent one. Membership in the FULL set is the only
    check that can ever fire; equality against "the latest one" is
    unsatisfiable by construction."""

    def history(unit_id):
        return [
            _dispatch_event("dispatch.dispatched", 1, "d-1"),
            _dispatch_event("dispatch.dispatched", 2, "d-2"),
        ]

    def dispatch(unit_id, payload):
        # Simulates a client bug that asked for ordinal 1 again -- the
        # orchestrator hands back d-1, the record for THAT ordinal, which is
        # not "the latest" (d-2) but is still a reuse.
        return {"id": "d-1", "status": "dispatched", "reason_code": None}

    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(history=history, dispatch=dispatch))
    assert rc == 1
    assert "no-op" in capsys.readouterr().err


def test_dispatch_calls_next_runner_attempt_not_a_parallel_implementation(monkeypatch):
    """Fix round 1/5, Important 2 regression. `dispatch()` must call the
    independently-tested `next_runner_attempt` for the ordinal -- not
    reimplement the same `max(...) + 1` arithmetic inline, which would leave
    `next_runner_attempt`'s own tests exercising a function production never
    calls. Proven by monkeypatching `next_runner_attempt` itself and
    asserting the POST payload carries exactly the value it returned."""
    seen = {}

    def fake_next_runner_attempt(attempt_count, latest_runner_attempt):
        seen["called_with"] = (attempt_count, latest_runner_attempt)
        return 99

    def dispatch(unit_id, payload):
        seen["payload"] = payload
        return {"id": "d-new", "status": "dispatched", "reason_code": None}

    monkeypatch.setattr(execution, "next_runner_attempt", fake_next_runner_attempt)
    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(dispatch=dispatch))
    assert rc == 0
    assert seen["called_with"] == (0, 0)
    assert seen["payload"]["runner_attempt"] == 99


def test_dispatch_reads_history_exactly_once_over_the_real_api():
    """Fix round 2/5 regression. `dispatch()` used to call `history()` TWICE
    -- once inside `next_runner_attempt`'s own fetch, once more inside a
    second helper for the no-op guard's record-id set -- a wasted round trip
    and a real TOCTOU window (a concurrent dispatch landing between the two
    reads could make them disagree). Counts the actual HTTP requests through
    a mock transport on a REAL `OrchestratorApi`, not the duck-typed fake, so
    a regression that reintroduces a second internal call site is caught
    even if it doesn't touch `reads.scan_dispatch_events` itself."""
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
        if path == "/api/v1/in-flight-units":
            return httpx.Response(
                200,
                json={
                    "units": [
                        {
                            "work_unit_id": "u1",
                            "unit_key": "bump-fastapi",
                            "version": 3,
                            "attempt_count": 1,
                        }
                    ],
                    "release_bindings": [],
                },
            )
        if path == "/api/v1/work-units/u1/history":
            return httpx.Response(
                200,
                json=[
                    {
                        "action": "dispatch.dispatched",
                        "payload": {"runner_attempt": 2, "dispatch_record_id": "d-2"},
                    }
                ],
            )
        if path == "/api/v1/work-units/u1/dispatch":
            return httpx.Response(
                200, json={"id": "d-new", "status": "dispatched", "reason_code": None}
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    api = OrchestratorApi(
        "https://sds.example",
        transport=httpx.MockTransport(handler),
        token_resolver=lambda role: "t",
    )
    rc = execution.dispatch("r1", "bump-fastapi", api=api)
    assert rc == 0
    history_calls = [p for m, p in seen if p == "/api/v1/work-units/u1/history"]
    assert len(history_calls) == 1


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


def test_dispatch_fails_when_status_is_not_dispatched(capsys):
    """Fix round 1/5, Critical 3 regression. A brand-new record whose status
    is anything other than 'dispatched' (e.g. the bounded window is closed
    -> status='skipped', reason_code='dispatch_disabled') means no
    workflow_dispatch fired, even though the record id is genuinely new and
    the no-op-by-reuse check has nothing to catch here."""

    def dispatch(unit_id, payload):
        return {"id": "d-new", "status": "skipped", "reason_code": "dispatch_disabled"}

    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(dispatch=dispatch))
    assert rc == 1
    err = capsys.readouterr().err
    assert "dispatch_disabled" in err
    assert "skipped" in err


def test_dispatch_reports_api_errors_cleanly(capsys):
    from intent_packages.factory.api import ApiError

    def dispatch(unit_id, payload):
        raise ApiError("work_unit_not_ready", "unit is not ready")

    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(dispatch=dispatch))
    assert rc == 1
    err = capsys.readouterr().err
    assert "dispatch failed: work_unit_not_ready" in err
    # A server verdict is conclusive: nothing landed, so the reconciliation
    # re-read must NOT run and no retry advice may be printed.
    assert "IT LANDED" not in err
    assert "did not land" not in err


# -- A1: an inconclusive POST is reconciled, never left to a retry ------------


def _timing_out_dispatch(code="api_timeout"):
    from intent_packages.factory.api import ApiError

    def dispatch(unit_id, payload):
        raise ApiError(code, "POST /api/v1/work-units/u1/dispatch timed out")

    return dispatch


def test_a_timed_out_dispatch_that_landed_says_do_not_retry(capsys):
    """A1. The orchestrator commits the `DispatchRecord` and fires the
    `workflow_dispatch` before the response reaches the client, and the window in
    which the response is slow IS the Actions queue delay -- exactly when an
    operator retries a 30s timeout. A retry mints a fresh
    `factory-dispatch-{uuid4()}`, so it can never reach the orchestrator's
    idempotency-key replay path; it computes the next ordinal and fires a SECOND
    real run instead. So a timeout must be reconciled against the record-id set
    captured BEFORE the POST, not handed to the operator as an open question.
    """
    calls = {"n": 0}

    def history(unit_id):
        calls["n"] += 1
        events = [_dispatch_event("dispatch.dispatched", 1, "d-1")]
        if calls["n"] > 1:
            # The re-read sees the record the timed-out POST actually created.
            events.append(_dispatch_event("dispatch.dispatched", 2, "d-2"))
        return events

    rc = execution.dispatch(
        "r1", "bump-fastapi", api=_fake_api(history=history, dispatch=_timing_out_dispatch())
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "dispatch failed: api_timeout" in err
    assert "IT LANDED" in err
    assert "d-2" in err
    assert "DO NOT RETRY" in err
    assert calls["n"] == 2  # one scan before the POST, one re-read after


def test_a_timed_out_dispatch_that_did_not_land_says_retrying_is_safe(capsys):
    """The other verdict, and the reason the diff is against a SET captured
    before the POST rather than a count: the prior record must not be reported as
    newly landed."""

    def history(unit_id):
        return [_dispatch_event("dispatch.dispatched", 1, "d-1")]

    rc = execution.dispatch(
        "r1", "bump-fastapi", api=_fake_api(history=history, dispatch=_timing_out_dispatch())
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "did not land" in err
    assert "safe" in err
    assert "IT LANDED" not in err


def test_a_never_dispatched_unit_that_times_out_does_not_claim_a_landing(capsys):
    """The empty-set case. `prior_dispatch_ids` is empty AND the re-read is
    empty, so nothing landed -- proving the guard distinguishes "the scan found
    nothing" from "the scan never ran". A flag, not set emptiness, is what
    carries that distinction in `dispatch()`."""
    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(dispatch=_timing_out_dispatch()))
    assert rc == 1
    err = capsys.readouterr().err
    assert "did not land" in err
    assert "IT LANDED" not in err


def test_a_connection_failure_is_reconciled_too(capsys):
    """`api_unavailable` is the same hazard as `api_timeout`: the request may
    have been received and acted on before the connection dropped."""

    calls = {"n": 0}

    def history(unit_id):
        calls["n"] += 1
        return [] if calls["n"] == 1 else [_dispatch_event("dispatch.dispatched", 1, "d-1")]

    rc = execution.dispatch(
        "r1",
        "bump-fastapi",
        api=_fake_api(history=history, dispatch=_timing_out_dispatch("api_unavailable")),
    )
    assert rc == 1
    assert "IT LANDED" in capsys.readouterr().err


def test_a_failed_reread_says_so_instead_of_guessing(capsys):
    """If the re-read ALSO fails, the honest answer is "cannot tell" plus the
    command that would tell -- never a guess in either direction."""
    from intent_packages.factory.api import ApiError

    calls = {"n": 0}

    def history(unit_id):
        calls["n"] += 1
        if calls["n"] > 1:
            raise ApiError("api_timeout", "GET history timed out")
        return []

    rc = execution.dispatch(
        "r1", "bump-fastapi", api=_fake_api(history=history, dispatch=_timing_out_dispatch())
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "could NOT determine whether it landed" in err
    assert "factory status --revision r1" in err
    assert "IT LANDED" not in err


def test_a_timeout_before_the_scan_is_not_reconciled(capsys):
    """The reconciliation needs a pre-POST record-id set. A timeout on an
    EARLIER read (here `traceability`, via `resolve_unit_id`) has no such set, so
    the verb must report the failure and stop -- not diff against nothing."""
    from intent_packages.factory.api import ApiError

    def traceability(*, revision_id=None, work_unit_id=None):
        raise ApiError("api_timeout", "GET /api/v1/traceability timed out")

    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(traceability=traceability))
    assert rc == 1
    err = capsys.readouterr().err
    assert "dispatch failed: api_timeout" in err
    assert "IT LANDED" not in err
    assert "did not land" not in err


def test_dispatch_never_retries_the_post(capsys):
    """ADR-independent but load-bearing: reconciliation must be a READ, never a
    second POST. Counts dispatch calls."""
    from intent_packages.factory.api import ApiError

    calls = {"dispatch": 0}

    def dispatch(unit_id, payload):
        calls["dispatch"] += 1
        raise ApiError("api_timeout", "timed out")

    execution.dispatch("r1", "bump-fastapi", api=_fake_api(dispatch=dispatch))
    assert calls["dispatch"] == 1


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


def test_dispatch_prints_the_actions_run_url_on_success(capsys):
    def dispatch(unit_id, payload):
        return {
            "id": "d-new",
            "status": "dispatched",
            "reason_code": None,
            "github_run_url": "https://github.com/AlobarQuest/brain/actions/runs/123",
        }

    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(dispatch=dispatch))
    assert rc == 0
    assert "https://github.com/AlobarQuest/brain/actions/runs/123" in capsys.readouterr().out


def test_dispatch_success_without_a_run_url_prints_no_stray_line(capsys):
    def dispatch(unit_id, payload):
        return {"id": "d-new", "status": "dispatched", "reason_code": None}

    rc = execution.dispatch("r1", "bump-fastapi", api=_fake_api(dispatch=dispatch))
    assert rc == 0
    assert "Actions run:" not in capsys.readouterr().out


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
