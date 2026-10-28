"""The confined read of the SDS member record (intent_packages.members).

CONTRACT PIN. `tests/fixtures/members_response.json` mirrors the orchestrator's
`GET /api/v1/members` response, built from `MemberView` in
`orchestrator/services/membership/members.py` (and read by its lane-side client,
`src/sds_members/client.py`). The two repositories share no code, so this fixture and the
test that parses it are the pin: this reader reads exactly `members[].repository`,
`members[].state` and `members[].grants[<service>].state`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from intent_packages.members import USER_AGENT, MembersUnreadable, granted_targets

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "members_response.json").read_text())
TOKEN = "observer-secret-value"


def _read(handler, **kwargs) -> frozenset[str]:
    return granted_targets(
        "dependency_updates", token=TOKEN, transport=httpx.MockTransport(handler), **kwargs
    )


def _serve(body, status: int = 200):
    return lambda request: httpx.Response(status, json=body)


def test_the_orchestrator_response_shape_parses() -> None:
    assert _read(_serve(FIXTURE)) == frozenset({"alobarquest/infraops-mcp-server"})


def test_a_retired_member_never_qualifies_and_only_granted_does() -> None:
    """The fixture holds a retired member whose grant is `granted` and an onboarding member
    whose grant is `remediating`; neither is a target."""
    assert _read(_serve(FIXTURE)).isdisjoint({"alobarquest/old-app", "alobarquest/brain"})


def test_the_request_is_the_confined_get_with_the_observer_identity() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=FIXTURE)

    _read(handler)
    (request,) = seen
    assert (request.method, request.url.path) == ("GET", "/api/v1/members")
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["x-credential-key-id"] == "orchestrator-observer"
    assert request.headers["user-agent"] == USER_AGENT
    assert "python" not in USER_AGENT.lower()


def test_a_transport_error_is_unreadable_and_names_no_secret() -> None:
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(MembersUnreadable, match="unreachable") as error:
        _read(boom)
    assert TOKEN not in str(error.value)


def test_a_malformed_base_url_is_unreadable() -> None:
    with pytest.raises(MembersUnreadable, match="unreachable"):
        _read(_serve(FIXTURE), base_url="not a url")


@pytest.mark.parametrize("status", [301, 401, 403, 500])
def test_a_non_2xx_is_unreadable(status) -> None:
    with pytest.raises(MembersUnreadable, match=str(status)):
        _read(_serve(FIXTURE, status))


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"members": "x"},
        {"members": [{"repository": "a/b", "state": "member"}]},
        {"members": [{"repository": "a/b", "state": "member", "grants": {}}]},
        {
            "members": [
                {
                    "repository": 1,
                    "state": "member",
                    "grants": {"dependency_updates": {"state": "granted"}},
                }
            ]
        },
        {"members": ["a/b"]},
    ],
)
def test_a_body_that_is_not_the_record_is_unreadable(body) -> None:
    with pytest.raises(MembersUnreadable):
        _read(_serve(body))


def test_a_body_that_is_not_json_is_unreadable() -> None:
    with pytest.raises(MembersUnreadable, match="not JSON"):
        _read(lambda request: httpx.Response(200, text="<html>"))


def test_no_token_is_unreadable_and_names_both_routes(monkeypatch) -> None:
    monkeypatch.delenv("SDS_MEMBERS_OBSERVER_TOKEN", raising=False)
    monkeypatch.delenv("BWS_ACCESS_TOKEN", raising=False)
    with pytest.raises(MembersUnreadable, match="SDS_MEMBERS_OBSERVER_TOKEN"):
        granted_targets("dependency_updates", transport=httpx.MockTransport(_serve(FIXTURE)))


def test_the_token_comes_from_the_environment_first(monkeypatch) -> None:
    monkeypatch.setenv("SDS_MEMBERS_OBSERVER_TOKEN", "from-env")
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json=FIXTURE)

    granted_targets("dependency_updates", transport=httpx.MockTransport(handler))
    assert seen == ["Bearer from-env"]
