import httpx
import pytest

from intent_packages.factory.api import ApiError, OrchestratorApi
from intent_packages.factory.credentials import CredentialError


def _api(handler, **kw):
    return OrchestratorApi(
        "https://sds.example",
        transport=httpx.MockTransport(handler),
        token_resolver=lambda role: f"token-for-{role.value}",
        **kw,
    )


def test_get_sends_bearer_and_key_id():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["key_id"] = request.headers["x-credential-key-id"]
        return httpx.Response(200, json={"id": "r1"})

    assert _api(handler).get_intake("r1") == {"id": "r1"}
    assert seen["auth"] == "Bearer token-for-orchestrator-system"
    assert seen["key_id"] == "orchestrator-system"


def test_verifier_routes_use_the_verifier_credential():
    seen = {}

    def handler(request):
        seen["key_id"] = request.headers["x-credential-key-id"]
        return httpx.Response(200, json={"ok": True})

    _api(handler).verify("u1", {"idempotency_key": "k", "expected_version": 1})
    assert seen["key_id"] == "orchestrator-verifier"


def test_error_envelope_is_surfaced_verbatim():
    def handler(request):
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "version_conflict",
                    "message": "stale version",
                    "recovery": "re-read the unit",
                    "current_version": 7,
                }
            },
        )

    with pytest.raises(ApiError) as error:
        _api(handler).readiness("u1")
    assert error.value.code == "version_conflict"
    assert error.value.recovery == "re-read the unit"
    assert error.value.current_version == 7


def test_401_is_annotated_and_not_retried():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "no"}})

    with pytest.raises(ApiError) as error:
        _api(handler).readiness("u1")
    assert len(calls) == 1
    assert "M2M-only" in (error.value.recovery or "")


def test_resolve_version_reads_current_version_off_the_conflict():
    def handler(request):
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "version_conflict",
                    "message": "stale",
                    "recovery": None,
                    "current_version": 4,
                }
            },
        )

    api = _api(handler)
    assert api.resolve_version("u1", probe={"idempotency_key": "probe", "expected_version": 0}) == 4


def test_resolve_version_returns_zero_when_the_probe_succeeds():
    def handler(request):
        return httpx.Response(200, json={"state": "ready"})

    api = _api(handler)
    assert api.resolve_version("u1", probe={"idempotency_key": "p", "expected_version": 0}) == 0


def test_timeout_is_a_distinct_code():
    def handler(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ApiError) as error:
        _api(handler).readiness("u1")
    assert error.value.code == "api_timeout"


def test_token_never_appears_in_an_error_string():
    def handler(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(ApiError) as error:
        _api(handler).readiness("u1")
    assert "token-for-" not in str(error.value)


def test_string_current_version_is_discarded_not_coerced():
    def handler(request):
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "version_conflict",
                    "message": "stale version",
                    "recovery": None,
                    "current_version": "4",
                }
            },
        )

    with pytest.raises(ApiError) as error:
        _api(handler).readiness("u1")
    assert error.value.current_version is None


def test_integer_current_version_still_passes_through():
    def handler(request):
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "version_conflict",
                    "message": "stale version",
                    "recovery": None,
                    "current_version": 4,
                }
            },
        )

    with pytest.raises(ApiError) as error:
        _api(handler).readiness("u1")
    assert error.value.current_version == 4


def test_traceability_requires_an_anchor_and_makes_no_request():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={})

    with pytest.raises(ApiError) as error:
        _api(handler).traceability()
    assert error.value.code == "traceability_anchor_required"
    assert calls == []


def test_credential_error_surfaces_as_a_clean_api_error():
    """A `CredentialError` from the token resolver must not escape as a raw

    traceback -- it is mapped to `ApiError(code="credential_unavailable")`
    inside `_send`, once, so every caller (not just `decompose.run`) gets a
    clean error instead of an unhandled exception.
    """
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={})

    def failing_resolver(role):
        raise CredentialError(
            f"no credential for {role.value}: set {role.env_var}, or set BWS_ACCESS_TOKEN "
            "so it can be fetched from BWS secret 660d5846-abcb-4751-be86-b483012899eb"
        )

    api = OrchestratorApi(
        "https://sds.example",
        transport=httpx.MockTransport(handler),
        token_resolver=failing_resolver,
    )
    with pytest.raises(ApiError) as error:
        api.readiness("u1")
    assert error.value.code == "credential_unavailable"
    assert "ORCHESTRATOR_SYSTEM_TOKEN" in error.value.message
    assert "660d5846-abcb-4751-be86-b483012899eb" in error.value.message
    assert calls == []  # never reached the transport


def test_non_object_body_on_a_dict_endpoint_raises_cleanly():
    """A JSON array from a `-> dict` endpoint must raise `ApiError`, not reach

    the caller untyped and blow up on the first `.get(...)`/`[...]` access.
    """

    def handler(request):
        return httpx.Response(200, json=[1, 2, 3])

    with pytest.raises(ApiError) as error:
        _api(handler).get_intake("r1")
    assert error.value.code == "invalid_response"
