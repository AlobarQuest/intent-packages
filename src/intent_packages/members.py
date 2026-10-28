"""A confined read of the SDS member record: which repositories hold a service's grant.

The dependency-update policy grant takes its target repositories from the member record
rather than from a hand-kept list (approval-policy.toml, schema 2). This module is the one
place that reads it: a single ``GET /api/v1/members`` with the observer bearer.

**It mirrors the orchestrator's ``MemberView``** (``orchestrator.services.membership.members``)
and reads only ``members[].repository``, ``members[].state`` and
``members[].grants[<service>].state``. This repository imports nothing from the orchestrator,
so ``tests/fixtures/members_response.json`` and ``tests/test_members.py`` pin those three
fields.

**Unreadable is one exception.** No token, a transport error, a non-2xx (a redirect included),
a body that is not JSON, or one that is not the record's shape: all :class:`MembersUnreadable`,
naming the cause and never the token. A caller must never read a partial answer as a shorter
target list, and the policy turns this exception into a refusal.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from intent_packages.factory.credentials import CredentialError, resolve_observer_token

DEFAULT_BASE_URL: Final = "https://sds.alobar.net"
# Cloudflare 403s default Python User-Agents (error 1010) on this host.
USER_AGENT: Final = "intent-packages-approval-policy/1 (+AlobarQuest/intent-packages)"
OBSERVER_KEY_ID: Final = "orchestrator-observer"
TIMEOUT_SECONDS: Final = 30.0
_ROUTE: Final = "/api/v1/members"
GRANTED: Final = "granted"
RETIRED: Final = "retired"


class MembersUnreadable(Exception):
    """The member record could not be read. The message names the cause, never a secret."""


def granted_targets(
    service: str,
    *,
    token: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    transport: httpx.BaseTransport | None = None,
) -> frozenset[str]:
    """Case-folded repositories whose non-retired member holds a ``granted`` grant for `service`."""
    bearer = token if token is not None else _token()
    return _targets(_fetch(bearer, base_url, transport), service)


def _token() -> str:
    try:
        return resolve_observer_token()
    except CredentialError as error:
        raise MembersUnreadable(f"no observer credential: {error}") from None


def _fetch(token: str, base_url: str, transport: httpx.BaseTransport | None) -> Any:
    try:
        with httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Credential-Key-Id": OBSERVER_KEY_ID,
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        ) as client:
            response = client.get(_ROUTE)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as error:
        raise MembersUnreadable(
            f"the member record was unreachable ({type(error).__name__})"
        ) from None
    if not response.is_success:
        raise MembersUnreadable(f"the member record answered HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise MembersUnreadable("the member record was not JSON") from None


def _targets(body: Any, service: str) -> frozenset[str]:
    members = body.get("members") if isinstance(body, dict) else None
    if not isinstance(members, list):
        raise MembersUnreadable("the member record had no members list")
    granted: set[str] = set()
    for member in members:
        try:
            repository = member["repository"]
            state = member["state"]
            grant_state = member["grants"][service]["state"]
        except KeyError, TypeError:
            raise MembersUnreadable(
                f"a member lacked repository, state or a {service} grant"
            ) from None
        if not all(isinstance(value, str) for value in (repository, state, grant_state)):
            raise MembersUnreadable("a member held a non-string repository or state")
        if state != RETIRED and grant_state == GRANTED:
            granted.add(repository.casefold())
    return frozenset(granted)
