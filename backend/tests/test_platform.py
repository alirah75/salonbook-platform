from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr, ValidationError
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.db.database import Database as ApiDatabase
from app.db.database import DatabaseNotReady
from app.modules.access.models import PlatformRoleAssignment, PlatformUser
from app.modules.identity.schemas import RegisterInput
from app.modules.operations.models import PlatformAuditLog
from app.platform.config import PlatformSettings
from app.platform.main import create_platform_app
from app.platform.service import PlatformService
from scripts.demo_dashboard import platform_login
from scripts.platform_admin import bootstrap
from tests.conftest import Database

pytestmark = pytest.mark.postgres
PASSWORD = "platform test password 12345"
PREFIX = "/platform/api/v1"


@pytest.fixture(scope="module")
def platform_service(database: Database) -> Iterator[PlatformService]:
    settings = PlatformSettings(
        environment="development",
        database_url=SecretStr(platform_login(database.lab)),
        auth_key=SecretStr(Fernet.generate_key().decode()),
        public_origin="http://127.0.0.1:3000",
    )
    service = PlatformService(settings)
    service.validate_ready()
    yield service
    service.engine.dispose()


@dataclass
class Console:
    client: TestClient
    csrf: str
    identifier: str
    phone: str

    def write(self, path: str, body: dict[str, object], method: str = "POST") -> Response:
        return self.client.request(
            method,
            PREFIX + path,
            json=body,
            headers={"Origin": "http://127.0.0.1:3000", "X-CSRF-Token": self.csrf},
        )


@pytest.fixture
def console(database: Database, platform_service: PlatformService) -> Iterator[Console]:
    phone = "091" + str(uuid4().int % 10**8).zfill(8)
    identifier = bootstrap(
        database.lab.owner,
        RegisterInput(phone=phone, display_name="Operator", password=SecretStr(PASSWORD)),
        "Test operator",
    )
    with TestClient(
        create_platform_app(platform_service.settings, platform_service),
        base_url="http://127.0.0.1:3000",
    ) as client:
        response = client.post(
            PREFIX + "/auth/login",
            json={"phone": phone, "password": PASSWORD},
            headers={"Origin": "http://127.0.0.1:3000"},
        )
        assert response.status_code == 200, response.text
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/platform" in cookie
        yield Console(client, response.json()["csrf_token"], str(identifier), phone)


def test_platform_mobile_session_origin_csrf_revocation(
    console: Console, database: Database
) -> None:
    c = console
    assert c.client.get(PREFIX + "/auth/me").json()["user"]["id"] == c.identifier
    assert (
        c.client.post(
            PREFIX + "/auth/logout",
            json={},
            headers={"Origin": "https://evil.test", "X-CSRF-Token": c.csrf},
        ).status_code
        == 403
    )
    assert (
        c.client.post(
            PREFIX + "/auth/logout", json={}, headers={"Origin": "http://127.0.0.1:3000"}
        ).status_code
        == 403
    )
    with database.lab.admin.begin() as conn:
        conn.execute(
            delete(PlatformRoleAssignment).where(PlatformRoleAssignment.user_id == c.identifier)
        )
    assert c.client.get(PREFIX + "/salons").status_code == 401


def test_platform_create_suspend_domain_and_actor_audit(
    console: Console, database: Database
) -> None:
    c = console
    hostname = f"console-{uuid4().hex}.test"
    response = c.write(
        "/salons",
        {
            "name": "New salon",
            "hostname": hostname,
            "manager": {"phone": "09123334444", "password": PASSWORD, "display_name": "Manager"},
            "reason": "New contract",
        },
    )
    assert response.status_code == 201, response.text
    tenant = response.json()["id"]
    directory = c.client.get(PREFIX + "/salons").json()
    row = next(r for r in directory["items"] if r["id"] == tenant)
    assert row["domains"][0]["is_active"] is False
    assert (
        c.write(
            f"/salons/{tenant}/domains",
            {"hostname": hostname, "operation": "activate", "reason": "DNS checked"},
        ).status_code
        == 422
    )
    assert (
        c.write(
            f"/salons/{tenant}/domains",
            {
                "hostname": hostname,
                "operation": "activate",
                "reason": "DNS checked",
                "ownership_verified": True,
            },
        ).status_code
        == 204
    )
    response = c.write(
        f"/salons/{tenant}/status", {"status": "SUSPENDED", "reason": "Operator review"}, "PATCH"
    )
    assert response.status_code == 204, response.text
    assert (
        c.write(
            f"/salons/{tenant}/status", {"status": "ACTIVE", "reason": "Review complete"}, "PATCH"
        ).status_code
        == 204
    )
    assert (
        c.write(
            f"/salons/{tenant}/status",
            {"status": "CLOSED", "reason": "Not a web operation"},
            "PATCH",
        ).status_code
        == 422
    )
    with database.lab.admin.connect() as conn:
        actor = conn.scalar(
            select(PlatformAuditLog.actor_id).where(
                PlatformAuditLog.entity_id == tenant, PlatformAuditLog.action == "tenant.suspended"
            )
        )
    assert str(actor) == c.identifier
    assert c.client.get(PREFIX + "/audit?limit=1").json()["has_more"]
    assert c.write("/auth/logout", {}).status_code == 204
    assert c.client.get(PREFIX + "/auth/me").status_code == 401


def test_platform_role_is_separate_and_restricted(
    database: Database, platform_service: PlatformService
) -> None:
    for table in ("appointments", "financial_entries", "payment_transactions", "calendars"):
        with platform_service.engine.connect() as conn, pytest.raises(DBAPIError):
            conn.execute(text(f"SELECT * FROM {table}"))
    with platform_service.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM users")) == 0  # mandatory tenant RLS
    settings = Settings(
        environment="development", database_url=platform_service.settings.database_url
    )
    runtime = ApiDatabase(settings)
    try:
        with pytest.raises(DatabaseNotReady, match="unsafe_database_role"):
            runtime.validate_ready()
    finally:
        runtime.dispose()
    for engine in (database.lab.owner, database.runtime):
        with pytest.raises(RuntimeError, match="Unsafe platform database role"):
            PlatformService(platform_service.settings, engine).validate_ready()
    with TestClient(
        create_platform_app(platform_service.settings, platform_service),
        base_url="http://127.0.0.1:3000",
    ) as guest:
        guest.cookies.set("sb_session", "fake-tenant-session")
        assert guest.get(PREFIX + "/salons").status_code == 401
        assert guest.get("/api/v1/users").status_code == 404


def test_platform_disabled_account_and_shared_throttle(
    console: Console, database: Database
) -> None:
    with database.lab.admin.begin() as conn:
        conn.execute(
            update(PlatformUser)
            .where(PlatformUser.id == console.identifier)
            .values(is_active=False)
        )
    assert console.client.get(PREFIX + "/auth/me").status_code == 401
    for _ in range(7):
        response = console.client.post(
            PREFIX + "/auth/login",
            json={"phone": console.phone, "password": "wrong"},
            headers={"Origin": "http://127.0.0.1:3000"},
        )
        assert response.status_code == 401
    response = console.client.post(
        PREFIX + "/auth/login",
        json={"phone": console.phone, "password": PASSWORD},
        headers={"Origin": "http://127.0.0.1:3000"},
    )
    assert response.status_code == 429


def test_platform_config_requires_https(platform_service: PlatformService) -> None:
    with pytest.raises(ValidationError):
        PlatformSettings(
            environment="production",
            database_url=platform_service.settings.database_url,
            auth_key=platform_service.settings.auth_key,
            public_origin="http://console.example.test",
        )
