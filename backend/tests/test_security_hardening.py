import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.types import Message, Receive, Scope, Send

from app.core.errors import AppError
from app.core.middleware import RequestContextMiddleware, RequestLimitsMiddleware
from app.modules.identity.throttle import AuthLimiter
from tests.test_authentication import AuthLab, login, register
from tests.test_authentication import auth_lab as auth_lab
from tests.test_configuration import settings


def exchange(
    chunks: list[bytes],
    headers: list[tuple[bytes, bytes]] | None = None,
    *,
    method: str = "POST",
    scheme: str = "http",
    production: bool = False,
    slow: bool = False,
    query: bytes = b"",
) -> tuple[int, dict[str, str], dict[str, Any]]:
    async def run() -> tuple[int, dict[str, str], dict[str, Any]]:
        events: list[Message] = []
        requests: list[Message] = [
            {"type": "http.request", "body": part, "more_body": i < len(chunks) - 1}
            for i, part in enumerate(chunks)
        ]

        async def receive() -> Message:
            if slow:
                await asyncio.sleep(0.1)
            return requests.pop(0) if requests else {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            events.append(message)

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            message = await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send(
                {
                    "type": "http.response.body",
                    "body": json.dumps({"bytes": len(message["body"])}).encode(),
                }
            )

        scope: Scope = {
            "type": "http",
            "method": method,
            "scheme": scheme,
            "path": "/api/v1/test",
            "headers": headers or [],
            "query_string": query,
        }
        wrapped = RequestContextMiddleware(
            RequestLimitsMiddleware(app, production=production, body_seconds=0.01 if slow else 1),
            production=production,
        )
        await wrapped(scope, receive, send)
        return (
            events[0]["status"],
            {k.decode(): v.decode() for k, v in events[0]["headers"]},
            json.loads(events[1]["body"]),
        )

    return asyncio.run(run())


@pytest.mark.parametrize(
    "method,length", [("POST", None), ("POST", b"1"), ("GET", None), ("DELETE", None)]
)
def test_actual_body_limit_including_chunked_and_forged_lengths(
    method: str, length: bytes | None
) -> None:
    headers = [(b"content-type", b"application/json")]
    if length:
        headers.append((b"content-length", length))
    status, response, body = exchange([b"x" * 40000, b"x" * 30000], headers, method=method)
    assert status == 413 and body["error"]["code"] == "payload_too_large"
    assert body["error"]["request_id"] == response["x-request-id"]
    assert response["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "headers,status",
    [
        ([(b"content-length", b"65537")], 413),
        ([(b"content-length", b"-1")], 400),
        ([(b"content-length", b"1"), (b"content-length", b"2")], 400),
        ([(b"content-encoding", b"gzip")], 415),
        ([(b"content-type", b"multipart/form-data; boundary=secret")], 415),
        ([(b"content-type", b"text/plain")], 415),
    ],
)
def test_invalid_envelopes_and_unsupported_uploads(
    headers: list[tuple[bytes, bytes]], status: int
) -> None:
    assert exchange([b"{}"], headers)[0] == status


def test_exact_boundary_chunk_replay_and_slow_body_timeout() -> None:
    status, _, body = exchange(
        [b"x" * 32768, b"x" * 32768], [(b"content-type", b"application/json")]
    )
    assert status == 200 and body == {"bytes": 65536}
    assert exchange([b""], slow=True)[0] == 408
    assert exchange([b""], query=b"q=" + b"a" * 8192)[0] == 414


def test_production_transport_and_headers_apply_to_rejections() -> None:
    assert exchange([b""], production=True)[0] == 400
    status, headers, _ = exchange([b"x" * 65537], production=True, scheme="https")
    assert status == 413
    assert headers["strict-transport-security"] == "max-age=31536000"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "camera=()" in headers["permissions-policy"]


def test_production_cannot_enable_mock_gateway() -> None:
    with pytest.raises(ValidationError):
        settings(
            environment="production", allowed_hosts=("salon.example",), mock_payments_enabled=True
        )


@pytest.mark.postgres
def test_public_api_budget_is_shared_across_paths_and_ignores_forwarded_ip(
    auth_lab: AuthLab,
) -> None:
    lab = auth_lab
    config = lab.runtime.settings.model_copy(update={"api_ip_limit": 10})
    lab.auth.limiter.settings = config
    for i in range(10):
        response = lab.client.get(
            "/api/v1/auth/csrf" if i % 2 else "/api/v1/catalog/booking-settings",
            headers={"X-Forwarded-For": f"192.0.2.{i}"},
        )
        assert response.status_code == 200, response.text
    response = lab.client.get("/api/v1/catalog/services")
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert lab.client.get("/api/v1/health/live").status_code == 200


@pytest.mark.postgres
def test_api_budget_is_atomic_across_instances(auth_lab: AuthLab) -> None:
    lab = auth_lab
    config = lab.runtime.settings.model_copy(update={"api_ip_limit": 10})
    limiters = [AuthLimiter(lab.runtime.database, config, lab.auth.security) for _ in range(2)]

    def attempt(index: int) -> int:
        try:
            limiters[index % 2].check_api(lab.context)
            return 200
        except AppError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(attempt, range(20)))
    assert outcomes.count(200) == outcomes.count(429) == 10


@pytest.mark.postgres
def test_middleware_protects_real_api_and_never_echoes_body(auth_lab: AuthLab) -> None:
    lab = auth_lab
    secret = "PRIVATE-OVERSIZE-REQUEST"
    response = lab.client.post(
        "/api/v1/auth/register", content=secret * 4000, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413 and secret not in response.text
    assert register(lab).status_code == 202
    assert login(lab).status_code == 200
    with TestClient(lab.app, base_url=lab.origin) as stranger:
        response = stranger.get(
            "/api/v1/finance/report?start=2026-01-01&end=2026-01-01",
            headers={
                "X-Tenant-ID": str(lab.tenant),
                "X-User-ID": "admin",
                "X-Role": "salon_manager",
            },
        )
        assert response.status_code == 401
