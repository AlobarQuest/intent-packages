"""HTTP client for the orchestrator API -- the front door's only transport for
API calls.

The rule this module encodes: shell out to the `orchestrator` CLI only for local
computation it owns (`emit-intake-payload`, `conformance-claim`); speak HTTP for
everything that is an API call. One auth path, one error vocabulary.

The orchestrator's error envelope is already good, so `ApiError` carries its
`code`/`message`/`recovery` verbatim rather than paraphrasing. A 401 gets one
extra sentence and is NEVER retried: it means the route is M2M-only at the proxy
or the credential role is wrong, and retrying cannot fix either.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import httpx

from intent_packages.factory.credentials import Role, resolve_token

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 30.0
_UNAUTHORIZED_RECOVERY = (
    "a 401 on /api means the route is M2M-only at the proxy, or this command is using the "
    "wrong credential role -- it does not mean auth is down, and retrying will not help"
)


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        recovery: str | None = None,
        *,
        current_version: int | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}" + (f" -- {recovery}" if recovery else ""))
        self.code = code
        self.message = message
        self.recovery = recovery
        self.current_version = current_version
        self.status_code = status_code


def base_url_from_env() -> str:
    return os.environ.get("ORCHESTRATOR_API_URL", DEFAULT_BASE_URL)


class OrchestratorApi:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        token_resolver: Callable[[Role], str] = resolve_token,
        verbose: bool = False,
    ) -> None:
        self._base_url = base_url or base_url_from_env()
        self._transport = transport
        self._resolve = token_resolver
        self._verbose = verbose

    def _send(self, method: str, path: str, role: Role, payload: dict | None) -> httpx.Response:
        """Issue one request and return the raw response.

        Connection/timeout failures are mapped to `ApiError` here so both
        callers (`_request`, `_request_text`) share one error path; a token is
        never interpolated into any exception message. Never retried -- a 401
        is a routing/credential fact, not a transient failure.
        """
        headers = {
            "Authorization": f"Bearer {self._resolve(role)}",
            "X-Credential-Key-Id": role.value,
        }
        try:
            with httpx.Client(
                base_url=self._base_url,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
                transport=self._transport,
            ) as client:
                response = client.request(method, path, json=payload)
        except httpx.TimeoutException:
            raise ApiError("api_timeout", f"{method} {path} timed out") from None
        except httpx.RequestError:
            raise ApiError("api_unavailable", f"{method} {path} could not be completed") from None
        if self._verbose:
            print(f"{method} {path} -> {response.status_code}")
        if response.is_error:
            raise _error_from(response)
        return response

    def _request(self, method: str, path: str, role: Role, payload: dict | None = None) -> Any:
        return _body_of(self._send(method, path, role, payload))

    def _request_text(self, path: str, role: Role = Role.SYSTEM) -> str:
        return self._send("GET", path, role, None).text

    def _get(self, path: str, role: Role = Role.SYSTEM) -> Any:
        return self._request("GET", path, role)

    def _post(self, path: str, payload: dict, role: Role = Role.SYSTEM) -> Any:
        return self._request("POST", path, role, payload)

    # -- reads -------------------------------------------------------------
    def get_intake(self, revision_id: str) -> dict:
        return self._get(f"/api/v1/package-intakes/{revision_id}")

    def list_proposals(self, revision_id: str) -> dict:
        return self._get(f"/api/v1/package-intakes/{revision_id}/decomposition-proposals")

    def traceability(self, *, revision_id: str | None = None, work_unit_id: str | None = None):
        params = {
            k: v for k, v in (("revision_id", revision_id), ("work_unit_id", work_unit_id)) if v
        }
        return self._get(f"/api/v1/traceability?{urlencode(params)}")

    def readiness(self, unit_id: str) -> dict:
        return self._get(f"/api/v1/work-units/{unit_id}/readiness")

    def history(self, unit_id: str) -> dict:
        return self._get(f"/api/v1/work-units/{unit_id}/history")

    def evidence_pack(self, unit_id: str) -> dict:
        return self._get(f"/api/v1/work-units/{unit_id}/evidence-pack")

    def revision_evidence_pack(self, revision_id: str) -> dict:
        return self._get(f"/api/v1/revisions/{revision_id}/evidence-pack")

    def evidence_pack_markdown(self, unit_id: str) -> str:
        return self._request_text(f"/api/v1/work-units/{unit_id}/evidence-pack/markdown")

    # -- writes ------------------------------------------------------------
    def propose_decomposition(self, revision_id: str, proposal: dict) -> dict:
        return self._post(
            f"/api/v1/package-intakes/{revision_id}/decomposition-proposals", proposal
        )

    def command(self, unit_id: str, command: str, payload: dict) -> dict:
        return self._post(f"/api/v1/work-units/{unit_id}/commands/{command}", payload)

    def dispatch(self, unit_id: str, payload: dict) -> dict:
        return self._post(f"/api/v1/work-units/{unit_id}/dispatch", payload)

    def named_check(self, unit_id: str, payload: dict) -> dict:
        return self._post(
            f"/api/v1/work-units/{unit_id}/verifier-evidence/named-check",
            payload,
            Role.VERIFIER,
        )

    def verify(self, unit_id: str, payload: dict) -> dict:
        return self._post(f"/api/v1/work-units/{unit_id}/verify", payload, Role.VERIFIER)

    # -- version resolution ------------------------------------------------
    def resolve_version(self, unit_id: str, *, probe: dict, command: str = "ready") -> int:
        """Return the unit's current version.

        A DRAFT unit is absent from `in-flight-units`, the only read surface
        carrying `version`, so the documented client contract is to POST an
        otherwise-VALID body with `expected_version: 0` and read
        `current_version` off the `version_conflict` error. Otherwise-valid
        matters: FastAPI 422s on schema validation before the service ever
        raises `version_conflict`.
        """
        try:
            self.command(unit_id, command, {**probe, "expected_version": 0})
        except ApiError as error:
            if error.code == "version_conflict" and error.current_version is not None:
                return error.current_version
            raise
        return 0


def _error_from(response: httpx.Response) -> ApiError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("error") if isinstance(body, dict) else None
    if not isinstance(detail, dict):
        detail = {"code": "http_error", "message": f"HTTP {response.status_code}"}
    recovery = detail.get("recovery")
    if response.status_code == 401:
        recovery = _UNAUTHORIZED_RECOVERY
    return ApiError(
        str(detail.get("code", "http_error")),
        str(detail.get("message", f"HTTP {response.status_code}")),
        recovery,
        current_version=detail.get("current_version"),
        status_code=response.status_code,
    )


def _body_of(response: httpx.Response) -> Any:
    try:
        value = response.json()
    except ValueError:
        raise ApiError("invalid_response", "the API returned a non-JSON body") from None
    if isinstance(value, (dict, list)):
        return value
    raise ApiError("invalid_response", "the API returned a non-object body")
