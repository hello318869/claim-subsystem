"""HTTP black-box client and response-contract helpers.

The provisional API note fixes paths and status families but not every response
envelope.  Accessors here accept the common list/entity envelopes in one place,
so a later ``api-contract.md`` only requires changing this file and the path
constants, not every test.

No helper imports application code.  All business interaction is over HTTP.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import httpx

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
AUTO_KEY = object()

# Paths from the provisional project contract.  The handover/dispute paths are
# claim-scoped by inference; confirm against api-contract.md (documented as a
# remaining integration point in evidence/testing-plan.md).
class Paths:
    DEMO_TOKEN = "/v1/demo/token"
    LISTINGS = "/v1/listings"
    CLAIMS = "/v1/claims"
    MATCHES = "/v1/matches"

    @staticmethod
    def listing(listing_id: object) -> str:
        return f"/v1/listings/{listing_id}"

    @staticmethod
    def claim(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}"

    @staticmethod
    def approve(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}/approve"

    @staticmethod
    def withdraw(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}/withdraw"

    @staticmethod
    def reject(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}/reject"

    @staticmethod
    def messages(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}/messages"

    @staticmethod
    def code(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}/code"

    @staticmethod
    def handover_confirm(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}/handover/confirm"

    @staticmethod
    def handover_reset(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}/handover/reset"

    @staticmethod
    def dispute(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}/dispute"

    @staticmethod
    def dispute_export(claim_id: object) -> str:
        return f"/v1/claims/{claim_id}/dispute-export"


class ApiContractError(AssertionError):
    """The server response does not satisfy the provisional API contract."""


def _snippet(response: httpx.Response, limit: int = 700) -> str:
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - diagnostics only
        text = "<unreadable body>"
    if len(text) > limit:
        text = text[:limit] + "...<truncated>"
    return text


def format_response(response: httpx.Response) -> str:
    request = response.request
    return (
        f"{request.method} {request.url.path} -> {response.status_code}; "
        f"body={_snippet(response)}"
    )


def expect_status(response: httpx.Response, expected: int | Iterable[int]) -> None:
    allowed = {expected} if isinstance(expected, int) else set(expected)
    if response.status_code not in allowed:
        raise ApiContractError(
            f"expected status {sorted(allowed)}, got {format_response(response)}"
        )


def expect_success(response: httpx.Response) -> None:
    expect_status(response, (200, 201, 204))


def json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise ApiContractError(
            f"expected a JSON object but body was not JSON: {format_response(response)}"
        ) from exc
    if not isinstance(payload, dict):
        raise ApiContractError(
            f"expected a JSON object, got {type(payload).__name__}: {format_response(response)}"
        )
    return payload


def unwrap_entity(response: httpx.Response) -> dict[str, Any]:
    """Return the entity, accepting a direct object or a one-key envelope."""

    payload = json_object(response)
    for key in ("data", "result", "item", "claim", "listing", "match", "message"):
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            if any(
                marker in candidate
                for marker in ("id", "status", "evidence_text", "claim_id")
            ):
                return candidate
            for inner in ("claim", "listing", "item", "message", "match"):
                nested = candidate.get(inner)
                if isinstance(nested, dict):
                    return nested
            return candidate
    return payload


def unwrap_items(payload: Any) -> list[Any]:
    """Return a page's item array, accepting common page envelopes."""

    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ApiContractError(f"expected a list or page object, got {type(payload).__name__}")
    for key in (
        "items",
        "data",
        "results",
        "records",
        "claims",
        "messages",
        "listings",
        "matches",
        "candidates",
        "recommendations",
    ):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, dict):
            for nested_key in (
                "items",
                "messages",
                "listings",
                "matches",
                "candidates",
                "recommendations",
            ):
                nested = candidate.get(nested_key)
                if isinstance(nested, list):
                    return nested
    raise ApiContractError(
        "cannot locate an item array in page envelope; keys="
        + ", ".join(sorted(str(key) for key in payload))
    )


def entity_id(entity: Mapping[str, Any]) -> object:
    for key in ("id", "claim_id", "listing_id", "message_id"):
        if key in entity and entity[key] is not None:
            return entity[key]
    raise ApiContractError(f"entity has no id field; keys={', '.join(sorted(entity))}")


def field(entity: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in entity:
            return entity[name]
    return None


def status_of(entity: Mapping[str, Any]) -> str:
    value = field(entity, "status", "claim_status", "state")
    if value is None:
        raise ApiContractError(
            f"entity has no status field; keys={', '.join(sorted(entity))}"
        )
    return str(value).upper()


def role_of(entity: Mapping[str, Any]) -> str:
    value = field(entity, "role", "my_role", "viewer_role")
    if value is None:
        raise ApiContractError(
            f"entity has no viewer role field; keys={', '.join(sorted(entity))}"
        )
    return str(value)


def message_id(entity: Mapping[str, Any]) -> object:
    for key in ("id", "message_id"):
        if key in entity and entity[key] is not None:
            return entity[key]
    raise ApiContractError(f"message has no id; keys={', '.join(sorted(entity))}")


def message_text(entity: Mapping[str, Any]) -> str:
    value = field(entity, "text", "content", "body")
    if value is None:
        raise ApiContractError(
            f"message has no text field; keys={', '.join(sorted(entity))}"
        )
    return str(value)


def assert_error(
    response: httpx.Response, expected: int | Iterable[int], *, context: str = ""
) -> dict[str, Any]:
    """Assert status plus the unified ``{code,message,field?}`` error shape."""

    expect_status(response, expected)
    payload = json_object(response)
    error: Any = payload
    if isinstance(payload.get("error"), dict):
        error = payload["error"]
    if not isinstance(error, dict):
        raise ApiContractError(f"error body is not an object: {format_response(response)}")
    code = error.get("code")
    message = error.get("message")
    if not isinstance(code, str) or not code:
        raise ApiContractError(f"error body lacks non-empty code: {format_response(response)}")
    if not isinstance(message, str) or not message:
        raise ApiContractError(
            f"error body lacks non-empty message: {format_response(response)}"
        )
    if "field" in error and error["field"] is not None and not isinstance(error["field"], str):
        raise ApiContractError(
            f"error field must be a string when present: {format_response(response)}"
        )
    if context:
        error["_context"] = context
    return error


def data_of(response: httpx.Response) -> Any:
    return json_object(response)


@dataclass
class Api:
    base_url: str
    timeout: float = 20.0
    _client: httpx.Client | None = None
    _tokens: dict[str, str] | None = None

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=50, max_keepalive_connections=20
            ),
        )
        self._tokens = {}

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            raise RuntimeError("Api client already closed")
        return self._client

    # -- identity ---------------------------------------------------------
    def login(self, actor: str) -> str:
        # The demo-token POST is a write; include a key in case the idempotency
        # middleware is global.  Business-write key enforcement is tested separately.
        response = self.raw(
            "POST",
            Paths.DEMO_TOKEN,
            json={"actor": actor},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        expect_status(response, 200)
        payload = json_object(response)
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise ApiContractError(
                f"demo token response lacks token: {format_response(response)}"
            )
        actor_echo = payload.get("actor")
        if actor_echo is not None and actor_echo != actor:
            raise ApiContractError(
                f"demo token actor echo mismatch: {format_response(response)}"
            )
        expires_at = payload.get("expires_at")
        if not isinstance(expires_at, str) or not expires_at:
            raise ApiContractError(
                f"demo token response lacks expires_at: {format_response(response)}"
            )
        self._tokens[actor] = token
        return token

    def token(self, actor: str) -> str:
        assert self._tokens is not None
        if actor not in self._tokens:
            return self.login(actor)
        return self._tokens[actor]

    def forget_token(self, actor: str) -> None:
        assert self._tokens is not None
        self._tokens.pop(actor, None)

    # -- low-level --------------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return self.client.request(
            method,
            path,
            headers=dict(headers or {}),
            json=json,
            params=params,
            content=content,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        actor: str | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        idempotency_key: object = AUTO_KEY,
    ) -> httpx.Response:
        method_upper = method.upper()
        request_headers = dict(headers or {})
        if actor is not None:
            request_headers["Authorization"] = f"Bearer {self.token(actor)}"
        if method_upper in WRITE_METHODS and idempotency_key is not None:
            key = (
                uuid.uuid4().hex
                if idempotency_key is AUTO_KEY
                else str(idempotency_key)
            )
            request_headers["Idempotency-Key"] = key
        return self.raw(
            method_upper,
            path,
            headers=request_headers,
            json=json,
            params=params,
        )

    def get(
        self,
        path: str,
        *,
        actor: str | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        return self.request("GET", path, actor=actor, params=params, headers=headers)

    def post(
        self,
        path: str,
        *,
        actor: str | None = None,
        json: Any = None,
        idempotency_key: object = AUTO_KEY,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        return self.request(
            "POST",
            path,
            actor=actor,
            json=json,
            idempotency_key=idempotency_key,
            headers=headers,
        )

    # -- domain helpers ---------------------------------------------------
    def create_claim(
        self,
        scenario: Any,
        actor: str,
        *,
        evidence_text: str = "物品细节仅双方可见：底部有蓝色贴纸和一道划痕。",
        item_number: str | None = None,
        idempotency_key: object = AUTO_KEY,
        expect: int | Iterable[int] = 201,
    ) -> httpx.Response:
        spec = scenario.claimant(actor)
        body = spec.create_payload(evidence_text)
        if item_number is not None:
            body["item_number"] = item_number
        response = self.post(
            Paths.CLAIMS,
            actor=actor,
            json=body,
            idempotency_key=idempotency_key,
        )
        expect_status(response, expect)
        return response

    def get_claim(self, claim_id: object, actor: str) -> httpx.Response:
        return self.get(Paths.claim(claim_id), actor=actor)

    def approve(self, claim_id: object, actor: str) -> httpx.Response:
        return self.post(Paths.approve(claim_id), actor=actor, json=None)

    def reject(self, claim_id: object, actor: str, reason: str | None) -> httpx.Response:
        return self.post(
            Paths.reject(claim_id),
            actor=actor,
            json=None if reason is None else {"reason": reason},
        )

    def withdraw(self, claim_id: object, actor: str) -> httpx.Response:
        return self.post(Paths.withdraw(claim_id), actor=actor, json=None)

    def messages(
        self,
        claim_id: object,
        actor: str,
        *,
        after: object = 0,
        limit: int | None = None,
    ) -> httpx.Response:
        params: dict[str, Any] = {}
        # V1.0.1 cursor must belong to the conversation; "0" is not a valid
        # message id.  Tests use 0/None to mean "first page", i.e. omit after.
        if after not in (None, 0, "0", ""):
            params["after"] = after
        if limit is not None:
            params["limit"] = limit
        return self.get(Paths.messages(claim_id), actor=actor, params=params)

    def send_message(
        self,
        claim_id: object,
        actor: str,
        text: str,
        *,
        idempotency_key: object = AUTO_KEY,
        expect: int | Iterable[int] = 201,
    ) -> httpx.Response:
        response = self.post(
            Paths.messages(claim_id),
            actor=actor,
            json={"text": text},
            idempotency_key=idempotency_key,
        )
        expect_status(response, expect)
        return response

    def get_code(self, claim_id: object, actor: str) -> httpx.Response:
        return self.get(Paths.code(claim_id), actor=actor)

    def confirm_handover(
        self, claim_id: object, actor: str, code: str
    ) -> httpx.Response:
        return self.post(
            Paths.handover_confirm(claim_id), actor=actor, json={"code": code}
        )

    def reset_handover(
        self, claim_id: object, actor: str, reason: str
    ) -> httpx.Response:
        return self.post(
            Paths.handover_reset(claim_id), actor=actor, json={"reason": reason}
        )

    def dispute(self, claim_id: object, actor: str, reason: str) -> httpx.Response:
        return self.post(Paths.dispute(claim_id), actor=actor, json={"reason": reason})

    def dispute_export(self, claim_id: object, actor: str) -> httpx.Response:
        return self.get(Paths.dispute_export(claim_id), actor=actor)

    def matches(self, lost_item_id: object, actor: str) -> httpx.Response:
        return self.get(
            Paths.MATCHES, actor=actor, params={"item_id": lost_item_id}
        )


def claim_status(api: Api, claim_id: object, actor: str = "alice") -> str:
    response = api.get_claim(claim_id, actor)
    expect_status(response, 200)
    return status_of(unwrap_entity(response))


def message_items(response: httpx.Response) -> list[dict[str, Any]]:
    expect_status(response, 200)
    payload = json_object(response)
    items = unwrap_items(payload)
    return [item for item in items if isinstance(item, dict)]


def message_page(
    response: httpx.Response,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return (items, next_after) using the frozen message-page envelope."""

    expect_status(response, 200)
    payload = json_object(response)
    items = unwrap_items(payload)
    next_after = field(payload, "next_after")
    if isinstance(payload.get("data"), dict):
        next_after = field(payload["data"], "next_after")
    if next_after is not None:
        next_after = str(next_after)
    return [item for item in items if isinstance(item, dict)], next_after


def approve_claim(api: Api, claim_id: object) -> str:
    response = api.approve(claim_id, "finder")
    expect_success(response)
    return claim_status(api, claim_id, "finder")
