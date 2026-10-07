import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import JsonFormatter, logger, request_id_context
from app.core.runtime import AppRuntime
from app.db.database import DatabaseNotReady
from app.main import create_app
from app.modules.health.schemas import ReadinessResponse
from tests.conftest import Database

pytestmark = pytest.mark.postgres


@pytest.fixture
def api_app(database: Database) -> FastAPI:
    return create_app(
        Settings(
            environment="test",
            database_url=SecretStr(database.lab.runtime_url),
            allowed_hosts=("testserver",),
            cors_origins=("https://salon.example",),
        )
    )


@contextmanager
def captured_logs() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_live_ready_and_openapi_contract(api_app: FastAPI) -> None:
    with TestClient(api_app) as client:
        assert client.get("/api/v1/health/live").json() == {
            "status": "ok",
            "service": "salonbook-api",
        }
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        spec = client.get("/api/v1/openapi.json").json()
        assert {"/api/v1/health/live", "/api/v1/health/ready"} <= set(spec["paths"])
        assert all(path.startswith("/api/v1/") for path in spec["paths"])
        assert "ErrorResponse" in spec["components"]["schemas"]
        assert client.get("/api/v1/docs").status_code == 200


def test_readiness_failure_does_not_break_liveness(
    api_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime: AppRuntime = api_app.state.runtime
    with TestClient(api_app) as client:

        def unavailable() -> None:
            raise DatabaseNotReady("database_unavailable")

        monkeypatch.setattr(runtime.database, "validate_ready", unavailable)
        assert client.get("/api/v1/health/live").status_code == 200
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "not_ready"
        assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
        assert "database_unavailable" not in response.text


def test_request_ids_are_generated_and_responses_not_cached(api_app: FastAPI) -> None:
    with TestClient(api_app) as client:
        one = client.get("/api/v1/health/live", headers={"X-Request-ID": "untrusted-id"})
        two = client.get("/api/v1/health/live")
        assert UUID(one.headers["x-request-id"]) != UUID(two.headers["x-request-id"])
        assert one.headers["cache-control"] == "no-store"
        assert one.headers["x-content-type-options"] == "nosniff"
        assert one.headers["x-frame-options"] == "DENY"
    assert request_id_context.get() is None


def test_invalid_host_is_rejected_and_forwarded_header_is_not_trusted(api_app: FastAPI) -> None:
    with TestClient(api_app) as client:
        response = client.get(
            "/api/v1/health/live",
            headers={"Host": "evil.example", "X-Forwarded-Host": "testserver"},
        )
        assert response.status_code == 400
        assert "x-request-id" in response.headers


def test_cors_allows_only_configured_origin(api_app: FastAPI) -> None:
    with TestClient(api_app) as client:
        allowed = client.get("/api/v1/health/live", headers={"Origin": "https://salon.example"})
        assert allowed.headers["access-control-allow-origin"] == "https://salon.example"
        assert allowed.headers["access-control-allow-credentials"] == "true"
        denied = client.options(
            "/api/v1/health/live",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert denied.status_code == 400
        assert "access-control-allow-origin" not in denied.headers


def test_unexpected_error_and_logs_do_not_expose_secrets(api_app: FastAPI) -> None:
    secret = "NEVER-LOG-THIS-password-token"

    @api_app.get("/__test__/failure")
    def fail() -> None:
        raise RuntimeError(secret)

    with captured_logs() as logs, TestClient(api_app) as client:
        response = client.get(
            f"/__test__/failure?reset_token={secret}",
            headers={
                "Authorization": f"Bearer {secret}",
                "Cookie": f"session={secret}",
                "Origin": "https://salon.example",
            },
        )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert response.headers["access-control-allow-origin"] == "https://salon.example"
        assert secret not in response.text
    output = logs.getvalue()
    assert secret not in output
    entries = [json.loads(line) for line in output.splitlines()]
    assert any(
        entry.get("error_type") == "RuntimeError" and entry.get("stack") for entry in entries
    )
    completed = next(entry for entry in entries if entry["event"] == "request.completed")
    assert completed["request_id"] == response.headers["x-request-id"]
    assert completed["route"] == "/__test__/failure"


def test_validation_errors_do_not_echo_body(api_app: FastAPI) -> None:
    class Payload(BaseModel):
        password: str
        amount: int = Field(gt=0)

    @api_app.post("/__test__/validate")
    def validate(payload: Payload) -> dict[str, bool]:
        return {"ok": True}

    with TestClient(api_app) as client:
        response = client.post(
            "/__test__/validate", json={"password": "PRIVATE", "amount": "NOT-A-NUMBER-SECRET"}
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["details"][0]["field"] == "body.amount"
        assert "SECRET" not in response.text and "PRIVATE" not in response.text
        assert "input" not in body["error"]["details"][0]


def test_response_validation_is_a_server_error(api_app: FastAPI) -> None:
    @api_app.get("/__test__/bad-response", response_model=ReadinessResponse)
    def wrong_response() -> dict[str, str]:
        return {"status": "internal-invalid-secret"}

    with TestClient(api_app) as client:
        response = client.get("/__test__/bad-response")
        assert response.status_code == 500
        assert "internal-invalid-secret" not in response.text


def test_database_conflicts_are_sanitized(api_app: FastAPI) -> None:
    @api_app.get("/__test__/conflict")
    def conflict() -> None:
        raise IntegrityError(
            "private SQL", {"password": "private-password"}, Exception("private-driver-message")
        )

    with TestClient(api_app) as client:
        response = client.get("/__test__/conflict")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "data_conflict"
        assert "private" not in response.text


def test_expected_service_errors_and_http_errors_have_same_shape(api_app: FastAPI) -> None:
    @api_app.get("/__test__/expected")
    def expected() -> None:
        raise AppError("example_conflict", "Please choose another option.", 409)

    with TestClient(api_app) as client:
        assert client.get("/__test__/expected").json()["error"]["code"] == "example_conflict"
        assert client.get("/missing").json()["error"]["code"] == "http_404"
        response = client.post("/api/v1/health/live")
        assert response.status_code == 405 and response.json()["error"]["code"] == "http_405"


def test_production_docs_are_absent(database: Database) -> None:
    app = create_app(
        Settings(
            environment="production",
            auth_key=SecretStr(Fernet.generate_key().decode()),
            database_url=SecretStr(database.lab.runtime_url),
            allowed_hosts=("salon.example",),
        )
    )
    with TestClient(app, base_url="https://salon.example") as client:
        assert client.get("/api/v1/health/ready").status_code == 200
        for path in ("/api/v1/docs", "/api/v1/openapi.json", "/docs/oauth2-redirect"):
            assert client.get(path).status_code == 404
