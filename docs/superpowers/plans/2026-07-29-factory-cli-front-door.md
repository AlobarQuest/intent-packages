# WS-P2.9 factory CLI front door — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grow `factory` into the single paved-road front door — `create validate submit status evidence ready dispatch verify` alongside the existing `decompose` and `route` — driving the orchestrator as an HTTP API client and stopping at every human gate with a `/review` deep link.

**Architecture:** A thin `httpx` client (`factory/api.py`) with two M2M credential roles resolved env-first and BWS-fallback (`factory/credentials.py`); pure `/review` URL builders (`factory/links.py`); a registry-driven package scaffold (`factory/scaffolds.py`); the flow verbs (`factory/journey.py`) and the verifier flow (`factory/verify.py`). `factory_cli.py` stays argparse with lazy per-subcommand imports. No orchestrator repo changes of any kind.

**Tech Stack:** Python 3.12, argparse, httpx, pyyaml, pytest. Existing: `intent_packages.profiles` (DeliveryProfile registry), `intent_packages.routing`, `intent_packages.validate`.

**Spec:** `docs/superpowers/specs/2026-07-29-factory-cli-front-door-design.md`

## Global Constraints

- Python 3.12+. Line length 100 (`ruff`). Ruff lint selects `E,F,I,UP,B,C90`; `max-complexity = 10`.
- Full gate is `make check` → `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/pyright` (0 errors), `.venv/bin/pytest`. **Read the collected count.** Baseline before this plan: **295 passed**.
- Run tests with `.venv/bin/pytest`, never a global `pytest`.
- **ADR-0006:** the CLI never impersonates a human. No `--as-human`, no `--force`, no config key that could satisfy `_require_human`. Human gates get a deep link and a refusal, never a transition.
- **Never echo a secret.** A bearer token is never logged, never in an exception message, never written to disk, never a subprocess argument. `--verbose` prints method, path and status only.
- **No orchestrator repo changes**, including CLI-only additions.
- **No `evidence_type: automated_test`** in any scaffold output. It resolves to `judgment_required` in the verifier and two profiles reject it outright.
- A **401 is never retried.** It means the route is M2M-only at the proxy or the credential role is wrong. There is no first-POST-retry branch anywhere in this tool.
- `sds.alobar.net` is **not** Cloudflare-proxied; httpx's default User-Agent is fine. Do not add a UA workaround.
- Existing guards must stay green: `tests/test_profiles_registry.py` (registry↔routing bidirectional consistency; no registered profile is a silent no-op) and `tests/test_packages_regression.py` (19 packages validate, locked hash snapshot).
- Commit after every task. Branch is `wsp29-factory-cli`.

## File Structure

| file | responsibility |
|---|---|
| `src/intent_packages/factory/credentials.py` | **Create.** `Role` enum, `resolve_token(role, *, runner=None) -> str`, `CredentialError`. |
| `src/intent_packages/factory/api.py` | **Create.** `ApiError`, `OrchestratorApi` — one method per route used, plus `resolve_version`. |
| `src/intent_packages/factory/links.py` | **Create.** Four pure `/review` URL builders. |
| `src/intent_packages/factory/scaffolds.py` | **Create.** `render_package`, `render_lineage`, `create` (remediation 6.3). |
| `src/intent_packages/factory/journey.py` | **Create.** `submit`, `status`, `evidence`, `ready`, `dispatch`. |
| `src/intent_packages/factory/verify.py` | **Create.** `verify` — named-check evidence then verifier evaluation (remediation 6.2). |
| `src/intent_packages/factory/orchestrator_cli.py` | **Modify.** Narrow to the two local commands (`emit-intake-payload`, `conformance-claim`); drop `show_package_intake` / `propose_decomposition`. |
| `src/intent_packages/factory/decompose.py` | **Modify.** Use `OrchestratorApi` for the two API calls. |
| `src/intent_packages/factory_cli.py` | **Modify.** Eight new subparsers, lazy imports. |
| `.bws-secrets.toml` | **Create.** UUID manifest for the two M2M credentials. |
| `pyproject.toml` | **Modify.** `httpx` joins `[project].dependencies`. |
| `tests/factory/test_credentials.py`, `test_api.py`, `test_links.py`, `test_scaffolds.py`, `test_journey.py`, `test_verify.py` | **Create.** |

---

### Task 1: Credentials — env-first, BWS fallback

**Files:**
- Create: `src/intent_packages/factory/credentials.py`
- Create: `.bws-secrets.toml`
- Test: `tests/factory/test_credentials.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Role` (str enum with `SYSTEM = "orchestrator-system"`, `VERIFIER = "orchestrator-verifier"`), `resolve_token(role: Role, *, runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None) -> str`, `CredentialError(Exception)`. Task 2 calls `resolve_token`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/factory/test_credentials.py
import subprocess

import pytest

from intent_packages.factory.credentials import CredentialError, Role, resolve_token


def test_env_wins(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_SYSTEM_TOKEN", "env-token")
    assert resolve_token(Role.SYSTEM) == "env-token"


def test_verifier_uses_its_own_env_var(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_VERIFIER_TOKEN", "verifier-token")
    assert resolve_token(Role.VERIFIER) == "verifier-token"


def test_falls_back_to_bws(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")
    seen = {}

    def runner(argv):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="bws-token\n", stderr="")

    assert resolve_token(Role.SYSTEM, runner=runner) == "bws-token"
    assert seen["argv"][:3] == ["bws", "secret", "get"]
    assert seen["argv"][3] == "221a48d5-3f29-4898-b300-b4820140c880"


def test_missing_bws_access_token_names_both_routes(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.delenv("BWS_ACCESS_TOKEN", raising=False)
    with pytest.raises(CredentialError) as error:
        resolve_token(Role.SYSTEM)
    message = str(error.value)
    assert "ORCHESTRATOR_SYSTEM_TOKEN" in message
    assert "221a48d5-3f29-4898-b300-b4820140c880" in message


def test_bws_failure_does_not_leak_stdout(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_SYSTEM_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")

    def runner(argv):
        return subprocess.CompletedProcess(argv, 1, stdout="s3cret-leak", stderr="denied")

    with pytest.raises(CredentialError) as error:
        resolve_token(Role.SYSTEM, runner=runner)
    assert "s3cret-leak" not in str(error.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/factory/test_credentials.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'intent_packages.factory.credentials'`

- [ ] **Step 3: Write the manifest**

```toml
# .bws-secrets.toml — BWS secret UUIDs this repo consumes.
# UUIDs are identifiers, not secrets. Values are fetched at runtime and never
# persisted. BWS_ACCESS_TOKEN must already be in the environment; this repo
# never fetches or stores it.

[secrets]
orchestrator-system = "221a48d5-3f29-4898-b300-b4820140c880"
orchestrator-verifier = "660d5846-abcb-4751-be86-b483012899eb"
```

- [ ] **Step 4: Write the implementation**

```python
"""M2M bearer resolution for the `factory` front door.

Two roles, two credentials: SYSTEM drives reads, decomposition submit, `ready`
and dispatch; VERIFIER drives named-check evidence and verifier evaluation.
`orchestrator-drift-reporter` is deliberately absent -- its registry profile is
observe-and-propose and `agent_id` attribution is permanent.

Env first so CI and tests never touch BWS; `bws secret get` second so a human
session needs no wrapper script. A token returned from here is held in a local
and passed straight to the HTTP client: it is never logged, never placed in an
exception message, and never written to disk.
"""

from __future__ import annotations

import enum
import os
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
MANIFEST = Path(__file__).resolve().parents[3] / ".bws-secrets.toml"
BWS_TIMEOUT_SECONDS = 30


class CredentialError(Exception):
    """Raised when neither the environment nor BWS can supply a bearer token."""


class Role(enum.StrEnum):
    SYSTEM = "orchestrator-system"
    VERIFIER = "orchestrator-verifier"

    @property
    def env_var(self) -> str:
        return f"ORCHESTRATOR_{self.name}_TOKEN"


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=BWS_TIMEOUT_SECONDS)


def secret_uuid(role: Role) -> str:
    try:
        manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    except OSError as error:
        raise CredentialError(f"cannot read {MANIFEST}") from error
    uuid = (manifest.get("secrets") or {}).get(role.value)
    if not isinstance(uuid, str) or not uuid:
        raise CredentialError(f"{MANIFEST} has no [secrets].{role.value} entry")
    return uuid


def resolve_token(role: Role, *, runner: Runner | None = None) -> str:
    """Return the bearer for `role`, from the environment or BWS. Never logged."""
    from_env = os.environ.get(role.env_var, "")
    if from_env:
        return from_env
    uuid = secret_uuid(role)
    if not os.environ.get("BWS_ACCESS_TOKEN"):
        raise CredentialError(
            f"no credential for {role.value}: set {role.env_var}, or set BWS_ACCESS_TOKEN "
            f"so it can be fetched from BWS secret {uuid}"
        )
    result = (runner or _default_runner)(["bws", "secret", "get", uuid, "--output", "env"])
    if result.returncode != 0:
        raise CredentialError(
            f"bws secret get failed for {role.value} (secret {uuid}), exit {result.returncode}"
        )
    return _parse_bws_env_output(result.stdout, role, uuid)


def _parse_bws_env_output(stdout: str, role: Role, uuid: str) -> str:
    """Extract the value from `bws secret get --output env` (KEY="value" lines).

    Falls back to the whole trimmed stdout when the output is a bare value.
    Never echoes stdout on failure -- it is the secret.
    """
    for line in stdout.splitlines():
        _, separator, value = line.partition("=")
        if separator and value.strip():
            return value.strip().strip('"')
    bare = stdout.strip()
    if bare:
        return bare
    raise CredentialError(f"bws secret get returned no value for {role.value} (secret {uuid})")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_credentials.py -v`
Expected: 5 passed.

Note the `--output env` flag means `test_falls_back_to_bws`'s runner returns `"bws-token\n"`, which has no `=`, so the bare-value fallback returns it. That is intentional coverage of both branches; add a second case asserting `KEY="value"` parsing:

```python
def test_parses_bws_env_output(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_VERIFIER_TOKEN", raising=False)
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "present")

    def runner(argv):
        return subprocess.CompletedProcess(argv, 0, stdout='TOKEN="abc123"\n', stderr="")

    assert resolve_token(Role.VERIFIER, runner=runner) == "abc123"
```

- [ ] **Step 6: Commit**

```bash
git add src/intent_packages/factory/credentials.py tests/factory/test_credentials.py .bws-secrets.toml
git commit -m "feat(factory): env-first, BWS-fallback M2M credential resolution (WS-P2.9 task 1)"
```

---

### Task 2: The orchestrator API client

**Files:**
- Create: `src/intent_packages/factory/api.py`
- Modify: `pyproject.toml` (add `httpx` to `[project].dependencies`)
- Test: `tests/factory/test_api.py`

**Interfaces:**
- Consumes: `credentials.Role`, `credentials.resolve_token`.
- Produces:
  - `ApiError(Exception)` with `.code: str`, `.message: str`, `.recovery: str | None`, `.current_version: int | None`, `.status_code: int | None`.
  - `OrchestratorApi(base_url: str, *, transport: httpx.BaseTransport | None = None, token_resolver=resolve_token)` with:
    `get_intake(revision_id) -> dict`, `list_proposals(revision_id) -> dict`, `propose_decomposition(revision_id, proposal: dict) -> dict`,
    `traceability(*, revision_id=None, work_unit_id=None) -> dict`, `readiness(unit_id) -> dict`, `history(unit_id) -> dict`,
    `evidence_pack(unit_id) -> dict`, `revision_evidence_pack(revision_id) -> dict`, `evidence_pack_markdown(unit_id) -> str`,
    `command(unit_id, command, payload) -> dict`, `dispatch(unit_id, payload) -> dict`,
    `named_check(unit_id, payload) -> dict`, `verify(unit_id, payload) -> dict`,
    `resolve_version(unit_id, *, probe: dict) -> int`.
  - `base_url_from_env() -> str` reading `ORCHESTRATOR_API_URL` (default `http://127.0.0.1:8000`).

Every method takes its role internally: reads and `command`/`dispatch`/`propose_decomposition` use `Role.SYSTEM`; `named_check` and `verify` use `Role.VERIFIER`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, change `dependencies = ["pyyaml>=6.0.3"]` to:

```toml
dependencies = ["httpx>=0.28.1", "pyyaml>=6.0.3"]
```

Then run `.venv/bin/python -c "import httpx"` to confirm it is importable; if not, `uv pip install 'httpx>=0.28.1'` into `.venv`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/factory/test_api.py
import httpx
import pytest

from intent_packages.factory.api import ApiError, OrchestratorApi


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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/factory/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'intent_packages.factory.api'`

- [ ] **Step 4: Write the implementation**

```python
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
    import os

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

    def _request(self, method: str, path: str, role: Role, payload: dict | None = None) -> Any:
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
        return _body_of(response)

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
        params = {k: v for k, v in (("revision_id", revision_id), ("work_unit_id", work_unit_id)) if v}
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

    def _request_text(self, path: str) -> str:
        headers = {
            "Authorization": f"Bearer {self._resolve(Role.SYSTEM)}",
            "X-Credential-Key-Id": Role.SYSTEM.value,
        }
        try:
            with httpx.Client(
                base_url=self._base_url,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
                transport=self._transport,
            ) as client:
                response = client.get(path)
        except httpx.TimeoutException:
            raise ApiError("api_timeout", f"GET {path} timed out") from None
        except httpx.RequestError:
            raise ApiError("api_unavailable", f"GET {path} could not be completed") from None
        if response.is_error:
            raise _error_from(response)
        return response.text

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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_api.py -v`
Expected: 8 passed.

- [ ] **Step 6: Run the full gate**

Run: `make check`
Expected: green; collected count 295 + the new tests. Record the number.

- [ ] **Step 7: Commit**

```bash
git add src/intent_packages/factory/api.py tests/factory/test_api.py pyproject.toml
git commit -m "feat(factory): orchestrator HTTP client with two-role auth and verbatim error envelope (WS-P2.9 task 2)"
```

---

### Task 3: `/review` deep links

**Files:**
- Create: `src/intent_packages/factory/links.py`
- Test: `tests/factory/test_links.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces: `intake_new(base) -> str`, `intake(base, revision_id) -> str`, `decomposition_proposal(base, proposal_id) -> str`, `unit(base, unit_id) -> str`, `unit_evidence_pack(base, unit_id) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/factory/test_links.py
from intent_packages.factory import links

BASE = "https://sds.alobar.net"


def test_all_five_links():
    assert links.intake_new(BASE) == f"{BASE}/review/intakes/new"
    assert links.intake(BASE, "r1") == f"{BASE}/review/intakes/r1"
    assert links.decomposition_proposal(BASE, "p1") == f"{BASE}/review/decomposition-proposals/p1"
    assert links.unit(BASE, "u1") == f"{BASE}/review/units/u1"
    assert links.unit_evidence_pack(BASE, "u1") == f"{BASE}/review/units/u1/evidence-pack"


def test_trailing_slash_on_base_is_normalised():
    assert links.intake_new(f"{BASE}/") == f"{BASE}/review/intakes/new"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/factory/test_links.py -v`
Expected: FAIL — `ImportError: cannot import name 'links'`

- [ ] **Step 3: Write the implementation**

```python
"""`/review` URL builders -- the human surfaces the front door hands off to.

Pure string composition, no I/O. These four (plus the evidence-pack child) are
every human-reachable page the flow touches; there is no fifth. Human gates are
browser-only permanently (ADR-0006), so a deep link is the entire mechanism by
which this CLI crosses one.
"""

from __future__ import annotations


def _root(base_url: str) -> str:
    return base_url.rstrip("/")


def intake_new(base_url: str) -> str:
    return f"{_root(base_url)}/review/intakes/new"


def intake(base_url: str, revision_id: str) -> str:
    return f"{_root(base_url)}/review/intakes/{revision_id}"


def decomposition_proposal(base_url: str, proposal_id: str) -> str:
    return f"{_root(base_url)}/review/decomposition-proposals/{proposal_id}"


def unit(base_url: str, unit_id: str) -> str:
    return f"{_root(base_url)}/review/units/{unit_id}"


def unit_evidence_pack(base_url: str, unit_id: str) -> str:
    return f"{unit(base_url, unit_id)}/evidence-pack"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/factory/test_links.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/intent_packages/factory/links.py tests/factory/test_links.py
git commit -m "feat(factory): /review deep-link builders (WS-P2.9 task 3)"
```

---

### Task 4: Migrate `decompose` onto the API client

**Files:**
- Modify: `src/intent_packages/factory/orchestrator_cli.py`
- Modify: `src/intent_packages/factory/decompose.py`
- Modify: `tests/factory/test_orchestrator_cli.py`, `tests/factory/test_decompose.py`

**Interfaces:**
- Consumes: `OrchestratorApi` from task 2.
- Produces: `OrchestratorClient` narrowed to `conformance_claim(repo_path)` only. `decompose.run(...)` keeps its exact signature — `factory_cli.py` is unchanged by this task.

This is the transport rule made real: `show_package_intake` and `propose_decomposition` are API calls and move to HTTP; `conformance_claim` is local computation the orchestrator owns and stays a shell-out. `emit-intake-payload` is added to `OrchestratorClient` in task 6, not here.

- [ ] **Step 1: Read the current call sites**

Run: `.venv/bin/python -c "import pathlib,re; t=pathlib.Path('src/intent_packages/factory/decompose.py').read_text(); print('\n'.join(l for l in t.splitlines() if 'client' in l.lower() or 'Orchestrator' in l))"`

Note every line that constructs `OrchestratorClient` or calls `show_package_intake` / `propose_decomposition`.

- [ ] **Step 2: Update the tests first**

In `tests/factory/test_decompose.py`, replace the fake `OrchestratorClient` used for `show_package_intake` / `propose_decomposition` with an injected fake API object exposing `get_intake(revision_id)` and `propose_decomposition(revision_id, proposal)`. Keep the fake `OrchestratorClient` only for `conformance_claim`. In `tests/factory/test_orchestrator_cli.py`, delete the tests for the two removed methods and keep the `conformance_claim` and error-mapping tests.

Add this test asserting the transport split is real:

```python
def test_orchestrator_client_no_longer_exposes_api_calls():
    from intent_packages.factory.orchestrator_cli import OrchestratorClient

    assert not hasattr(OrchestratorClient, "show_package_intake")
    assert not hasattr(OrchestratorClient, "propose_decomposition")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/factory/ -v`
Expected: the new test FAILS (`assert not hasattr(...)`), and the rewritten decompose tests fail on the injected-api signature.

- [ ] **Step 4: Make the change**

In `orchestrator_cli.py`, delete the `show_package_intake` and `propose_decomposition` methods and narrow the module docstring to say it wraps **local** orchestrator computation only. In `decompose.py`, take an `api` parameter (defaulting to `OrchestratorApi()`) alongside the existing client, and replace:

- `client.show_package_intake(revision)` → `api.get_intake(revision)`
- `client.propose_decomposition(revision, proposal_path)` → `api.propose_decomposition(revision, proposal_dict)`

The second is not a mechanical swap: the CLI path wrote the proposal to a temp file and passed `@path`; the HTTP path posts the dict directly. Delete the `tempfile` write that existed only to feed `--data @file`, keeping the `--out` write, which is a user-facing feature. Catch `ApiError` wherever `OrchestratorCliError` was caught for these two calls.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/ -v`
Expected: all pass.

- [ ] **Step 6: Run the full gate**

Run: `make check`
Expected: green. This is the regression check for a production-proven command; if anything in `test_decompose.py` needed its *assertions* (not just its fakes) changed, stop and re-read — behaviour was supposed to be identical.

- [ ] **Step 7: Commit**

```bash
git add src/intent_packages/factory/orchestrator_cli.py src/intent_packages/factory/decompose.py tests/factory/
git commit -m "refactor(factory): decompose speaks HTTP for API calls, shells out only for local computation (WS-P2.9 task 4)"
```

---

### Task 5: `factory create` and `factory validate`

**Files:**
- Create: `src/intent_packages/factory/scaffolds.py`
- Modify: `src/intent_packages/factory_cli.py`
- Test: `tests/factory/test_scaffolds.py`

**Interfaces:**
- Consumes: `intent_packages.profiles.PROFILES`, `intent_packages.validate.validate_package`, `intent_packages.schema` spec types.
- Produces: `render_package(profile, package_id, title, owner, created_at) -> dict`, `render_lineage(package_id, created_at) -> dict`, `create(profile_name, package_id, out_dir, ...) -> int`, `validate(path) -> int`.

Remediation 6.3. The scaffold is **registry-driven**: one universal skeleton, parameterised by the profile, rather than five template files. The profile contributes its `name`, its `profile_fields_schema` keys, an evidence type drawn from `tag_to_evidence_type` minus `forbidden_evidence_types`, and `authority.budgets` from `default_authority`. That is what makes the "every registered profile scaffolds and validates" guard cheap and meaningful.

- [ ] **Step 1: Write the failing tests**

```python
# tests/factory/test_scaffolds.py
import pytest
import yaml

from intent_packages.factory import scaffolds
from intent_packages.profiles import PROFILES
from intent_packages.validate import validate_package


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_every_registered_profile_scaffolds_and_validates(profile_name, tmp_path):
    """The create-side analogue of WS-P2.10's no-silent-noop guard.

    A front door that emits an invalid package is worse than a blank page.
    """
    rc = scaffolds.create(profile_name, "scaffold-probe", str(tmp_path))
    assert rc == 0
    document = yaml.safe_load((tmp_path / "scaffold-probe" / "package.yaml").read_text())
    assert validate_package(document) == []


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_no_scaffold_declares_automated_test(profile_name, tmp_path):
    scaffolds.create(profile_name, "scaffold-probe", str(tmp_path))
    document = yaml.safe_load((tmp_path / "scaffold-probe" / "package.yaml").read_text())
    assert all(item["evidence_type"] != "automated_test" for item in document["acceptance"])


def test_unregistered_profile_lists_valid_choices(tmp_path, capsys):
    rc = scaffolds.create("python-service", "probe", str(tmp_path))
    assert rc == 1
    message = capsys.readouterr().err
    assert "python-service" in message
    for name in PROFILES:
        assert name in message


def test_refuses_to_overwrite(tmp_path):
    assert scaffolds.create("software-delivery", "probe", str(tmp_path)) == 0
    assert scaffolds.create("software-delivery", "probe", str(tmp_path)) == 1


def test_lineage_starts_in_draft(tmp_path):
    scaffolds.create("software-delivery", "probe", str(tmp_path))
    lineage = yaml.safe_load((tmp_path / "probe" / "lineage.yaml").read_text())
    assert lineage["current_state"] == "draft"
    assert lineage["approvals"] == []


def test_ac_id_semantics_are_documented_in_the_output(tmp_path):
    scaffolds.create("software-delivery", "probe", str(tmp_path))
    text = (tmp_path / "probe" / "package.yaml").read_text()
    assert "database UUID" in text and "AC-001" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/factory/test_scaffolds.py -v`
Expected: FAIL — `ImportError: cannot import name 'scaffolds'`

- [ ] **Step 3: Write the implementation**

Build `render_package` as a dict literal covering **every** key in `intent_packages.schema.TOP_SCHEMA` (the schema is closed — a missing key and an unknown key are both errors). **Start from the complete valid package already in the repo:** `tests/conftest.py`'s `_VALID_PACKAGE_YAML` constant is a full, valid, schema_version-1 document — copy its key structure verbatim and replace its values. `packages/conformance-claim-helper/package.yaml` is a second, richer reference. Prose values are real sentences a human then edits, not the string "TODO"; a scaffold must validate, and the semantic checks reject empty prose.

Profile-driven parts:

```python
def _evidence_type(profile) -> str:
    """Pick an evidence type this profile permits.

    `automated_test` resolves to `judgment_required` in the verifier for every
    automated AC however good the evidence, and two profiles reject it outright,
    so it is excluded here regardless of what a profile's tag map contains.
    """
    forbidden = set(profile.forbidden_evidence_types) | {"automated_test"}
    permitted = [v for v in sorted(set(profile.tag_to_evidence_type.values())) if v not in forbidden]
    return permitted[0] if permitted else "test"


def _profile_fields(profile) -> dict | None:
    """Emit one entry per key the profile's schema declares, with a typed stub."""
    spec = profile.profile_fields_schema
    if spec is None:
        return None
    return {key: _stub_for(field) for key, field in spec.fields.items()}
```

`_stub_for` maps a `ScalarSpec` to `""` / `0` / `None` by `py_type` and `nullable`, a `ListSpec` to `[]`, a `MapSpec` to a recursive dict, and an `OptionalKey` to the stub of its wrapped spec. Write it as an explicit `isinstance` chain over the four spec classes — a `TypeError` on an unknown spec class is correct, because a new spec kind must be considered here deliberately.

The `acceptance` list gets exactly two items, and the comment block above it in the emitted YAML carries the `ac_id` rule verbatim:

```
# ac_id means two different things and nothing checks the difference:
#   - a decomposition proposal's ac_mappings[].ac_id / retained_acs[].ac_id want
#     the criterion's database UUID
#   - evidence and adjudication want the human string below, e.g. AC-001
# Getting it wrong is a bare package_acceptance_criterion_not_found with no hint.
```

For `dependency-update`, additionally prepend the envelope-discipline comment:

```
# allowed_commands is an ORDERED list the worker re-executes at finalize, not a
# permission set: put mutators first and the verifier last, or the recorded
# evidence attests to a tree that is not the one pushed. `make check` must never
# appear in this repo's envelope. Use `uv venv --clear`, never bare `uv venv`.
```

Emit with `yaml.safe_dump(..., sort_keys=False, default_flow_style=False, allow_unicode=True)` and splice the comment blocks in as text before the sections they annotate. `create` writes `package.yaml` and `lineage.yaml`, refuses if the target directory exists (returns 1), then calls `validate_package` on what it wrote and returns 1 with the errors printed to stderr if it does not pass.

`validate(path)` loads the YAML and delegates to `intent_packages.validate.validate_package` — the same code path as `intent_packages validate`, not a reimplementation.

- [ ] **Step 4: Wire the subparsers**

In `factory_cli.py`, add to `_build_parser`:

```python
    c = sub.add_parser("create", help="scaffold an intent package from a registered profile")
    c.add_argument("--profile", required=True, help="registered delivery profile name")
    c.add_argument("--name", required=True, dest="package_id", help="package_id slug")
    c.add_argument("--out", default="packages", help="parent directory (default: packages)")
    c.add_argument("--owner", default="devon")
    c.add_argument("--title", default="", help="package title (default: derived from --name)")

    v = sub.add_parser("validate", help="validate an intent package")
    v.add_argument("path", help="path to a package directory or package.yaml")
```

and in `main`:

```python
    if args.cmd == "create":
        from intent_packages.factory import scaffolds

        return scaffolds.create(
            args.profile, args.package_id, args.out, owner=args.owner, title=args.title
        )
    if args.cmd == "validate":
        from intent_packages.factory import scaffolds

        return scaffolds.validate(args.path)
```

- [ ] **Step 5: Add entrypoint tests**

```python
# append to tests/factory/test_factory_cli.py
def test_create_through_the_entrypoint(tmp_path):
    from intent_packages.factory_cli import main

    rc = main(["create", "--profile", "software-delivery", "--name", "probe", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "probe" / "package.yaml").exists()


def test_validate_through_the_entrypoint(tmp_path):
    from intent_packages.factory_cli import main

    main(["create", "--profile", "software-delivery", "--name", "probe", "--out", str(tmp_path)])
    assert main(["validate", str(tmp_path / "probe")]) == 0
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/ -v`
Expected: all pass, including the parametrised guard over all five registered profiles.

- [ ] **Step 7: Commit**

```bash
git add src/intent_packages/factory/scaffolds.py src/intent_packages/factory_cli.py tests/factory/
git commit -m "feat(factory): create scaffolds a package from a registered profile; validate delegates (remediation 6.3, WS-P2.9 task 5)"
```

---

### Task 6: `factory submit` — stage the intake, hand off, stop

**Files:**
- Create: `src/intent_packages/factory/journey.py`
- Modify: `src/intent_packages/factory/orchestrator_cli.py` (add `emit_intake_payload`)
- Modify: `src/intent_packages/factory_cli.py`
- Test: `tests/factory/test_journey.py`

**Interfaces:**
- Consumes: `links`, `api.OrchestratorApi`, `orchestrator_cli.OrchestratorClient`.
- Produces: `submit(package_path, source_repository, *, open_browser=False, api=None, client=None, clipboard=None) -> int`. Tasks 7–9 add `status`, `evidence`, `ready`, `dispatch` to the same module.

- [ ] **Step 1: Write the failing tests**

```python
# tests/factory/test_journey.py
import subprocess

import pytest
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/factory/test_journey.py -v`
Expected: FAIL — `ImportError: cannot import name 'journey'`

- [ ] **Step 3: Add `emit_intake_payload` to `OrchestratorClient`**

```python
    def emit_intake_payload(
        self, package_path: str, source_repository: str, idempotency_key: str
    ) -> dict:
        return self._call(
            [
                "emit-intake-payload",
                package_path,
                "--source-repository",
                source_repository,
                "--idempotency-key",
                idempotency_key,
            ]
        )
```

- [ ] **Step 4: Write `submit`**

```python
"""The flow verbs: submit, status, evidence, ready, dispatch.

Every human gate here is a stop, not a step. `submit` prepares the intake
payload, copies it, prints the /review link and exits -- it can never complete
an intake, because the route requires a HUMAN actor and no HUMAN credential
exists or ever will (ADR-0006).
"""
```

`submit`:

1. Load `package.yaml` (accept a directory or the file). Refuse with exit 1 unless `status == "approved"` and the sibling `lineage.yaml` has `current_state == "approved"`, printing the exact next command: `intent_packages transition <path> --to ready_for_review` then `intent_packages approve <path> --approver devon`.
2. Mint an idempotency key (`f"factory-submit-{uuid.uuid4()}"`) and call `client.emit_intake_payload(...)`.
3. `clipboard(json.dumps(payload, sort_keys=True, separators=(",", ":")))`; default clipboard is `subprocess.run(["pbcopy"], input=text, text=True)`, and a failure there is a warning, not an error.
4. Print the link (`links.intake_new(base_url_from_env())`), open it with `webbrowser.open` when `open_browser`, and print the stop message including the two facts a user otherwise rediscovers:
   - the form takes its idempotency key from the **form field**, not the pasted payload, so re-submitting a rendered page is a *replay* — a genuinely new registration needs a page reload;
   - resume with `factory status --revision <id from the URL the form redirects to>`.
5. Return 0. It must not touch `api` at all.

- [ ] **Step 5: Wire the subparser**

```python
    s = sub.add_parser("submit", help="stage an intake payload and hand off to /review")
    s.add_argument("--package", required=True, help="package directory or package.yaml")
    s.add_argument("--source-repository", required=True, dest="source_repository")
    s.add_argument("--open", action="store_true", dest="open_browser", help="open /review")
```

```python
    if args.cmd == "submit":
        from intent_packages.factory import journey

        return journey.submit(
            args.package, args.source_repository, open_browser=args.open_browser
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_journey.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/intent_packages/factory/journey.py src/intent_packages/factory/orchestrator_cli.py src/intent_packages/factory_cli.py tests/factory/test_journey.py
git commit -m "feat(factory): submit stages the intake payload and stops at the human gate (WS-P2.9 task 6)"
```

---

### Task 7: `factory status` and `factory evidence`

**Files:**
- Modify: `src/intent_packages/factory/journey.py`, `src/intent_packages/factory_cli.py`
- Test: `tests/factory/test_journey.py`

**Interfaces:**
- Consumes: `api.OrchestratorApi.get_intake / list_proposals / traceability / readiness / history / evidence_pack / revision_evidence_pack / evidence_pack_markdown`.
- Produces: `status(revision_id, *, wait=False, poll_seconds=15, timeout_seconds=1800, api=None) -> int`, `evidence(revision_id, *, unit_key=None, markdown=False, api=None) -> int`, and the shared helper `units_for(api, revision_id) -> list[dict]` used by tasks 8 and 9.

`units_for` derives units from `traceability?revision_id=`, returning each chain's `unit` hop (`id`, `unit_key`, `state`, `authority_fingerprint`, `authority_approved_by`, `authority_decision`) plus its `pr` hop when present. This is the single derivation point; tasks 8 and 9 must call it rather than re-deriving.

- [ ] **Step 1: Write the failing tests**

```python
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

    journey.evidence("r1", unit_key="bump-fastapi", markdown=True,
                     api=_fake_api(evidence_pack_markdown=evidence_pack_markdown))
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/factory/test_journey.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'status'`

- [ ] **Step 3: Write the implementation**

`status` prints, in order: the intake state; each proposal id and state with its `/review` link when not yet decided; then per unit a line with `unit_key`, state, and whether an authority approval is recorded; then **the next action**. The next-action logic must distinguish the two expensive cases:

```python
def _next_action(base_url: str, unit: dict, readiness: dict) -> str:
    if unit["state"] == "draft" and unit.get("authority_decision") == "approved":
        return (
            f"authority approved but the unit is still DRAFT -- authority approval does not move "
            f"state. Run: factory ready --revision <rev> --unit-key {unit['unit_key']}"
        )
    if unit["state"] == "draft":
        return (
            f"needs a HUMAN authority approval bound to fingerprint "
            f"{unit['authority_fingerprint']}. Use the 'Approve this authority envelope' form "
            f"(NOT the generic approve button, which records subject_type=action and does not "
            f"satisfy readiness): {links.unit(base_url, unit['id'])}"
        )
    if unit["state"] == "ready":
        return f"ready to dispatch: factory dispatch --revision <rev> --unit-key {unit['unit_key']}"
    return f"state {unit['state']}: {links.unit(base_url, unit['id'])}"
```

`--wait` loops with `time.sleep(poll_seconds)` until any unit's state changes or `timeout_seconds` elapses, catching `KeyboardInterrupt` to exit 130 cleanly. Poll `traceability` only; do not re-fetch the intake each tick.

`evidence` resolves `--unit-key` through `units_for`, exits 1 listing the real keys when unknown, and prints `json.dumps(..., indent=2, sort_keys=True)` or the markdown verbatim.

- [ ] **Step 4: Wire the subparsers**

```python
    st = sub.add_parser("status", help="one screen for a revision, with the next action")
    st.add_argument("--revision", default="", help="revision id (default: $FACTORY_REVISION)")
    st.add_argument("--wait", action="store_true", help="poll until a unit's state changes")

    ev = sub.add_parser("evidence", help="fetch the evidence pack")
    ev.add_argument("--revision", default="")
    ev.add_argument("--unit-key", dest="unit_key", default="")
    ev.add_argument("--markdown", action="store_true", help="the redacted PR-comment form")
```

Both resolve `--revision` via a shared helper that falls back to `$FACTORY_REVISION` and errors with exit 2 when neither is set.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_journey.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/intent_packages/factory/journey.py src/intent_packages/factory_cli.py tests/factory/test_journey.py
git commit -m "feat(factory): status with next-action guidance, and evidence-pack fetch (WS-P2.9 task 7)"
```

---

### Task 8: `factory ready` and `factory dispatch`

**Files:**
- Modify: `src/intent_packages/factory/journey.py`, `src/intent_packages/factory_cli.py`
- Test: `tests/factory/test_journey.py`

**Interfaces:**
- Consumes: `units_for` (task 7), `api.resolve_version`, `api.command`, `api.dispatch`, `api.history`.
- Produces: `ready(revision_id, unit_key, *, api=None) -> int`, `dispatch(revision_id, unit_key, *, api=None) -> int`, `next_runner_attempt(api, unit_id, attempt_count) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_next_runner_attempt_uses_the_max_of_both_counters():
    def history(unit_id):
        return {
            "events": [
                {"type": "dispatch.dispatched", "payload": {"runner_attempt": 2}},
                {"type": "unit.claimed", "payload": {}},
            ]
        }

    api = _fake_api(history=history)
    assert journey.next_runner_attempt(api, "u1", attempt_count=1) == 3
    assert journey.next_runner_attempt(api, "u1", attempt_count=5) == 6


def test_next_runner_attempt_is_one_when_never_dispatched():
    assert journey.next_runner_attempt(_fake_api(), "u1", attempt_count=0) == 1


def test_dispatch_reports_a_reused_record_id_as_failure(capsys):
    """A reused ordinal returns the EXISTING record with HTTP 200 and
    status='dispatched', triggering no workflow_dispatch. Only a new record id
    proves a dispatch happened."""

    def history(unit_id):
        return {
            "events": [
                {"type": "dispatch.dispatched",
                 "payload": {"runner_attempt": 2, "dispatch_id": "d-old"}}
            ]
        }

    def dispatch(unit_id, payload):
        return {"id": "d-old", "status": "dispatched", "reason_code": None}

    rc = journey.dispatch("r1", "bump-fastapi", api=_fake_api(history=history, dispatch=dispatch))
    assert rc == 1
    assert "no-op" in capsys.readouterr().err


def test_dispatch_accepts_a_new_record_id(capsys):
    def dispatch(unit_id, payload):
        return {"id": "d-new", "status": "dispatched", "reason_code": None}

    rc = journey.dispatch("r1", "bump-fastapi", api=_fake_api(dispatch=dispatch))
    assert rc == 0


def test_ready_uses_the_version_probe():
    seen = {}

    def resolve_version(unit_id, *, probe, command="ready"):
        seen["probe"] = (probe, command)
        return 3

    def command(unit_id, command_name, payload):
        seen["command"] = (command_name, payload["expected_version"])
        return {"state": "ready"}

    api = _fake_api(resolve_version=resolve_version, command=command)
    assert journey.ready("r1", "bump-fastapi", api=api) == 0
    assert seen["command"] == ("ready", 3)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/factory/test_journey.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'next_runner_attempt'`

- [ ] **Step 3: Write the implementation**

```python
def next_runner_attempt(api, unit_id: str, attempt_count: int) -> int:
    """The next dispatch ordinal.

    Dispatch and claim ordinals are INDEPENDENT: DispatchRecord.runner_attempt
    counts dispatch decisions including skipped ones, while attempt_count counts
    worker claims. They drift apart the moment a dispatch is skipped or a claim
    is reclaimed, so `attempt_count + 1` is not a safe substitute for either.
    """
    latest = 0
    for event in api.history(unit_id).get("events", []):
        if event.get("type") == "dispatch.dispatched":
            latest = max(latest, int(event.get("payload", {}).get("runner_attempt", 0)))
    return max(attempt_count, latest) + 1
```

`dispatch` records the prior dispatch record id from the same history scan, posts with the computed `runner_attempt`, and then compares:

```python
    if response.get("id") and response.get("id") == prior_dispatch_id:
        print(
            "dispatch was a silent no-op: the orchestrator returned the EXISTING record "
            f"({prior_dispatch_id}) because this runner_attempt was already used. No "
            "workflow_dispatch fired. The response's status field says 'dispatched' either way.",
            file=sys.stderr,
        )
        return 1
```

On success it prints the new record id and the window reminder: closing the bounded dispatch window restarts the orchestrator, and terminal means all three of — the Actions run concluded, the unit left `executing`, and cost-actuals exist.

`ready` resolves the version via `api.resolve_version(unit_id, probe={"idempotency_key": key}, command="ready")`, then posts `commands/ready` with that version. Both verbs mint `f"factory-{verb}-{uuid.uuid4()}"` idempotency keys.

- [ ] **Step 4: Wire the subparsers**

```python
    rd = sub.add_parser("ready", help="SYSTEM: move a unit DRAFT -> READY")
    rd.add_argument("--revision", default="")
    rd.add_argument("--unit-key", dest="unit_key", required=True)

    dp = sub.add_parser("dispatch", help="SYSTEM: dispatch a READY unit to the runner")
    dp.add_argument("--revision", default="")
    dp.add_argument("--unit-key", dest="unit_key", required=True)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_journey.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/intent_packages/factory/journey.py src/intent_packages/factory_cli.py tests/factory/test_journey.py
git commit -m "feat(factory): ready and dispatch, with ordinal derivation and no-op detection (WS-P2.9 task 8)"
```

---

### Task 9: `factory verify` — the verifier flow

**Files:**
- Create: `src/intent_packages/factory/verify.py`
- Modify: `src/intent_packages/factory_cli.py`
- Test: `tests/factory/test_verify.py`

**Interfaces:**
- Consumes: `journey.units_for`, `api.history`, `api.traceability`, `api.evidence_pack`, `api.named_check`, `api.verify`, `api.resolve_version`.
- Produces: `verify(revision_id, unit_key, *, ac_id, check_name, conclusion, run_id, run_url, assertions, repository=None, api=None) -> int`, `parse_assertion(text) -> dict`.

Remediation 6.2. Two calls: named-check evidence, then verifier evaluation.

- [ ] **Step 1: Write the failing tests**

```python
# tests/factory/test_verify.py
import pytest

from intent_packages.factory import verify as verify_module


def test_parse_assertion():
    assert verify_module.parse_assertion("collected=295:295") == {
        "name": "collected",
        "expected": "295",
        "observed": "295",
    }


def test_parse_assertion_rejects_a_malformed_value():
    with pytest.raises(ValueError):
        verify_module.parse_assertion("collected")


def test_named_check_body_is_fully_derived():
    seen = {}

    class FakeApi:
        def traceability(self, *, revision_id=None, work_unit_id=None):
            return {
                "anchor": {},
                "chains": [
                    {
                        "unit": {
                            "id": "u1",
                            "unit_key": "k",
                            "state": "submitted",
                            "authority_fingerprint": "fp",
                        },
                        "pr": {"pr_number": 12, "head_sha": "abc1234"},
                    }
                ],
            }

        def history(self, unit_id):
            return {
                "events": [
                    {"type": "dispatch.dispatched",
                     "payload": {"runner_attempt": 1, "dispatch_id": "d1"}}
                ]
            }

        def evidence_pack(self, unit_id):
            return {"authority": {"constraints": {"target_repository": "AlobarQuest/brain"}}}

        def resolve_version(self, unit_id, *, probe):
            return 5

        def named_check(self, unit_id, payload):
            seen["named_check"] = payload
            return {"id": "e1"}

        def verify(self, unit_id, payload):
            seen["verify"] = payload
            return {"outcomes": [{"ac_id": "AC-001", "outcome": "passed"}]}

    rc = verify_module.verify(
        "r1", "k", ac_id="AC-001", check_name="Quality", conclusion="success",
        run_id="99", run_url="https://github.com/x/y/actions/runs/99",
        assertions=["collected=295:295"], api=FakeApi(),
    )
    assert rc == 0
    body = seen["named_check"]
    assert body["dispatch_id"] == "d1"
    assert body["pr_number"] == 12
    assert body["head_sha"] == "abc1234"
    assert body["repository"] == "AlobarQuest/brain"
    assert body["pr_url"] == "https://github.com/AlobarQuest/brain/pull/12"
    assert body["ac_id"] == "AC-001"
    assert body["work_package_revision_id"] == "r1"


def test_missing_pr_binding_is_an_actionable_refusal(capsys):
    class FakeApi:
        def traceability(self, *, revision_id=None, work_unit_id=None):
            return {"anchor": {}, "chains": [{"unit": {"id": "u1", "unit_key": "k",
                                                       "state": "submitted",
                                                       "authority_fingerprint": "fp"}, "pr": None}]}

    rc = verify_module.verify(
        "r1", "k", ac_id="AC-001", check_name="Quality", conclusion="success",
        run_id="99", run_url="u", assertions=[], api=FakeApi(),
    )
    assert rc == 1
    assert "pr" in capsys.readouterr().err.lower()


def test_assertions_are_capped_at_32():
    with pytest.raises(ValueError):
        verify_module.build_assertions([f"n{i}=1:1" for i in range(33)])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/factory/test_verify.py -v`
Expected: FAIL — `ImportError: cannot import name 'verify'`

- [ ] **Step 3: Write the implementation**

Derivation, in this order, refusing with exit 1 and a named reason whenever a source is absent rather than guessing:

| field | source |
|---|---|
| `work_package_revision_id` | the `--revision` argument |
| `dispatch_id` | the last `dispatch.dispatched` event in `history` |
| `pr_number`, `head_sha` | the unit's chain `pr` hop from `traceability(work_unit_id=...)` |
| `repository` | `evidence_pack(unit_id)["authority"]["constraints"]["target_repository"]`, overridable with `--repository` |
| `pr_url` | `f"https://github.com/{repository}/pull/{pr_number}"` |
| `ac_id` | `--ac` — the **human string** (`AC-001`), never the criterion UUID |
| `check_name`, `conclusion`, `run_id`, `run_url`, `assertions` | flags |

```python
MAX_ASSERTIONS = 32


def parse_assertion(text: str) -> dict:
    """Parse `name=expected:observed` into a NamedCheckAssertionModel body."""
    name, separator, rest = text.partition("=")
    expected, colon, observed = rest.partition(":")
    if not (separator and colon and name and expected and observed):
        raise ValueError(f"assertion must be name=expected:observed, got {text!r}")
    return {"name": name, "expected": expected, "observed": observed}


def build_assertions(values: list[str]) -> list[dict]:
    if len(values) > MAX_ASSERTIONS:
        raise ValueError(f"at most {MAX_ASSERTIONS} assertions, got {len(values)}")
    return [parse_assertion(value) for value in values]
```

`verify` posts the named check, then `api.verify(unit_id, {"idempotency_key": ..., "expected_version": version})`, then prints one line per AC outcome. `evidence_pack`'s exact path to `target_repository` **must be confirmed against a live response during the production drive** — if `authority.constraints.target_repository` is not where it lives, make `--repository` required rather than guessing a different path.

- [ ] **Step 4: Wire the subparser**

```python
    vf = sub.add_parser("verify", help="VERIFIER: post named-check evidence, then evaluate")
    vf.add_argument("--revision", default="")
    vf.add_argument("--unit-key", dest="unit_key", required=True)
    vf.add_argument("--ac", dest="ac_id", required=True, help="human AC id, e.g. AC-001")
    vf.add_argument("--check-name", dest="check_name", required=True)
    vf.add_argument(
        "--conclusion",
        required=True,
        choices=("success", "failure", "cancelled", "timed_out", "action_required",
                 "neutral", "skipped", "stale"),
    )
    vf.add_argument("--run-id", dest="run_id", required=True)
    vf.add_argument("--run-url", dest="run_url", required=True)
    vf.add_argument("--repository", default="", help="override the derived target repository")
    vf.add_argument("--assert", dest="assertions", action="append", default=[],
                    metavar="NAME=EXPECTED:OBSERVED")
```

Confirm the `--conclusion` choices against `/openapi.json` before hard-coding them:
`curl -s https://sds.alobar.net/openapi.json | python3 -c "import sys,json; print(json.load(sys.stdin)['components']['schemas']['VerifierNamedCheckEvidenceCommandModel']['properties']['conclusion']['enum'])"`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/factory/test_verify.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/intent_packages/factory/verify.py src/intent_packages/factory_cli.py tests/factory/test_verify.py
git commit -m "feat(factory): verify posts named-check evidence then evaluates (remediation 6.2, WS-P2.9 task 9)"
```

---

### Task 10: Entrypoint coverage, README, and the full gate

**Files:**
- Modify: `tests/factory/test_factory_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing new.

- [ ] **Step 1: Write the entrypoint tests**

Every subcommand must be driven through `main(argv)` — the real parser wiring, not the module function. A lone-command CLI has shipped a broken launcher before.

```python
import pytest

from intent_packages.factory_cli import main

ALL_COMMANDS = ["create", "validate", "submit", "status", "evidence",
                "ready", "dispatch", "verify", "decompose", "route"]


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_every_command_is_reachable_and_has_help(command, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([command, "--help"])
    assert exit_info.value.code == 0
    assert command in capsys.readouterr().out


@pytest.mark.parametrize("command", ["status", "evidence", "ready", "dispatch", "verify"])
def test_revision_falls_back_to_the_environment(command, monkeypatch):
    """--revision defaults to $FACTORY_REVISION; neither set is exit 2."""
    monkeypatch.delenv("FACTORY_REVISION", raising=False)
    argv = [command]
    if command in {"ready", "dispatch", "verify"}:
        argv += ["--unit-key", "k"]
    if command == "verify":
        argv += ["--ac", "AC-001", "--check-name", "Q", "--conclusion", "success",
                 "--run-id", "1", "--run-url", "u"]
    assert main(argv) == 2


def test_no_command_can_impersonate_a_human():
    """ADR-0006: no flag may exist that could satisfy _require_human."""
    import intent_packages.factory_cli as cli

    text = __import__("pathlib").Path(cli.__file__).read_text()
    for forbidden in ("--as-human", "--human", "--force", "--impersonate"):
        assert forbidden not in text
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/pytest tests/factory/test_factory_cli.py -v`
Expected: all pass. Fix any parser wiring the parametrised test exposes.

- [ ] **Step 3: Wire the `--verbose` flag**

`OrchestratorApi` takes a `verbose` parameter (task 2) that nothing sets yet. Add a top-level
`parser.add_argument("--verbose", action="store_true")` in `_build_parser`, thread it into every
`OrchestratorApi(...)` construction, and assert it prints method/path/status **and no token**:

```python
def test_verbose_prints_the_request_line_and_no_token(capsys):
    import httpx

    from intent_packages.factory.api import OrchestratorApi
    from intent_packages.factory.credentials import Role

    api = OrchestratorApi(
        "https://sds.example",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        token_resolver=lambda role: "supersecret",
        verbose=True,
    )
    api.readiness("u1")
    out = capsys.readouterr().out
    assert "GET /api/v1/work-units/u1/readiness -> 200" in out
    assert "supersecret" not in out
```

(`Role` is imported only to keep the token-leak assertion honest against a real role value; drop
the import if the final implementation does not need it.)

- [ ] **Step 4: Update the README**

Add a `factory` section documenting the eight new verbs, the two env vars for credentials, `$FACTORY_REVISION`, and — stated plainly — that human gates are browser-only and the CLI deep-links rather than crossing them.

- [ ] **Step 5: Run the full gate and read the count**

Run: `make check`
Expected: green. **Read the collected count** — it must exceed the 295 baseline by the number of tests added. Exit 0 is not evidence the tests ran.

- [ ] **Step 6: Confirm the working tree is clean before trusting the gate**

Run: `git status --short`
Expected: empty. A full-gate green with uncommitted edits is a false green.

- [ ] **Step 7: Commit**

```bash
git add tests/factory/test_factory_cli.py README.md
git commit -m "test+docs: entrypoint coverage for every factory verb; README front-door section (WS-P2.9 task 10)"
```

---

### Task 11: Local end-to-end drive

**Files:** none — this is a verification task.

- [ ] **Step 1: Start a local orchestrator**

Follow the orchestrator repo's local setup (Postgres on 127.0.0.1:5432, `SECURITY_STANDARDS_DIR`, `alembic upgrade head`). Use a runtime database **separate from `orchestrator_test`** — the test fixtures drop and recreate that database and would erase the drive's state.

- [ ] **Step 2: Drive every verb**

`create` → edit → `validate` → approve locally → `submit` (confirm it stops) → intake via the local `/review` form → `status` → `decompose` → approve the proposal in `/review` → authority approval in `/review` → `ready` → `status` → `dispatch` → `evidence` → `verify`.

- [ ] **Step 3: Record what each verb printed**

Capture the output for the closeout. Note in particular whether `evidence_pack`'s `authority.constraints.target_repository` path held — task 9 depends on it.

- [ ] **Step 4: Adversarial whole-branch review**

Run `/code-review` over the full branch diff, not per-task. Per the repo's history, the whole-branch review catches what per-task reviews miss.

- [ ] **Step 5: Commit any fixes and re-run `make check`**

---

### Task 12: Production drive

**Files:** none — this is the definition-of-done demonstration.

**Do not start this task until task 11 is complete, `make check` is green, and the branch is in a mergeable state.** Phase boundary: if budget is tight, stopping here leaves a mergeable branch rather than a strand inside an open dispatch window.

- [ ] **Step 1: Ask production what it is running**

Run: `curl -s https://sds.alobar.net/openapi.json | python3 -c "import sys,json; print(sorted(json.load(sys.stdin)['paths']))"`
Confirm every route the CLI calls is present. Merged is not deployed.

- [ ] **Step 2: Export credentials**

Either export `ORCHESTRATOR_SYSTEM_TOKEN` / `ORCHESTRATOR_VERIFIER_TOKEN`, or export `BWS_ACCESS_TOKEN` and let the fallback fetch them. Never echo a token, never pass one as a command argument.

Set `ORCHESTRATOR_API_URL=https://sds.alobar.net`.

- [ ] **Step 3: Drive intake through the browser gates**

`factory create` → `validate` → approve → commit → `factory submit --open`. Devon pastes into `/review/intakes/new` and hands back the revision id from the redirect URL.

- [ ] **Step 4: Decomposition and authority**

`factory decompose` (dry first, then `--submit`) → Devon approves the proposal in `/review` → Devon approves the authority envelope with the **"Approve this authority envelope"** form, not the generic approve button → `factory ready`.

- [ ] **Step 5: The dispatch window**

Open the bounded window (`ORCHESTRATOR_DISPATCH_ENABLED`, `..._ALLOWED_TARGET_REPOSITORIES`), which restarts the orchestrator. Then `factory dispatch`. **Confirm a NEW record id and a new Actions run** — never the `status` field alone.

Hold the window open until the run is terminal in all three senses: the Actions run concluded, the unit left `executing`, and cost-actuals exist. Closing it early restarts the orchestrator into the runner's `finalize-run` and strands the unit, spending the attempt. The window is bounded by construction — dispatch admission requires a READY unit with its authority approval — so there is nothing else an open window can dispatch.

- [ ] **Step 6: Evidence and verification**

`factory evidence` → `factory verify` with the real check name, run id and run url from the Actions run.

- [ ] **Step 7: Close the window and write the closeout**

Close the dispatch gates (second restart). Write closeout evidence to `~/docs/software-delivery-system/2026-07-29-wsp29-closeout-evidence.md`: what shipped, the collected count, the production drive transcript, and — plainly — what remains felt-gap versus closed for deliverable C#1.

---

## Notes carried from the spec

- `ApiError` uses the orchestrator's field name **`recovery`**, not `hint`. The spec's §5 says "hint"; the wire format is `{"error": {"code", "message", "recovery", "current_state", "current_version"}}`. Follow the wire format.
- `retry` and `cancel` are increment 2 and appear nowhere in this plan.
- No task touches the orchestrator repo. If one appears to need to, stop and escalate.
