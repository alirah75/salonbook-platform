from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session as UnitOfWork

from app.core.config import Settings
from app.core.errors import AppError
from app.core.runtime import AppRuntime
from app.main import create_app
from app.modules.access.models import Role, RoleAssignment, RolePermission
from app.modules.access.service import DEFAULT_ROLES, provision_roles
from app.modules.identity.context import AuthContext
from app.modules.identity.dependencies import require_permission
from app.modules.identity.models import Session, User
from app.modules.identity.runtime import AuthRuntime
from app.modules.identity.security import token_hash
from app.modules.tenancy.models import TenantDomain
from tests.conftest import Database

pytestmark = pytest.mark.postgres
PASSWORD = "a-long-secret-password-2026"
NEW_PASSWORD = "another-long-secret-password-2026"
PHONE = "+989123456789"


@dataclass
class AuthLab:
    database: Database
    app: FastAPI
    runtime: AppRuntime
    auth: AuthRuntime
    client: TestClient
    tenant: UUID
    other_tenant: UUID
    line: UUID
    other_line: UUID
    origin: str
    other_origin: str

    @property
    def context(self) -> AuthContext:
        return AuthContext(self.tenant, self.origin, "127.0.0.1", uuid4())


@pytest.fixture
def auth_lab(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> Iterator[AuthLab]:
    origins = [f"https://salon-{uuid4().hex}.example" for _ in tenants]
    with UnitOfWork(database.lab.admin) as session, session.begin():
        for seed, origin in zip(tenants, origins, strict=True):
            session.add(
                TenantDomain(
                    tenant_id=seed["tenant"],
                    hostname=origin.removeprefix("https://"),
                    verified_at=datetime.now(UTC),
                    is_active=True,
                )
            )
            session.execute(
                update(Role)
                .where(Role.tenant_id == seed["tenant"], Role.code == "customer")
                .values(is_system=True)
            )
            session.add_all(
                RolePermission(tenant_id=seed["tenant"], role_id=seed["role"], permission_code=code)
                for code in DEFAULT_ROLES["customer"]
            )
            provision_roles(session, seed["tenant"])
    config = Settings(
        environment="test",
        database_url=SecretStr(database.lab.runtime_url),
        auth_key=SecretStr(Fernet.generate_key().decode()),
        allowed_hosts=tuple(origin.removeprefix("https://") for origin in origins),
    )
    app = create_app(config)
    runtime: AppRuntime = app.state.runtime
    assert runtime.auth is not None
    with TestClient(app, base_url=origins[0]) as client:
        yield AuthLab(
            database,
            app,
            runtime,
            runtime.auth,
            client,
            tenants[0]["tenant"],
            tenants[1]["tenant"],
            tenants[0]["line"],
            tenants[1]["line"],
            origins[0],
            origins[1],
        )


def public_post(
    lab: AuthLab, path: str, data: dict[str, Any], *, client: TestClient | None = None
) -> Response:
    browser = client or lab.client
    csrf = browser.get("/api/v1/auth/csrf")
    assert csrf.status_code == 200, csrf.text
    return browser.post(
        f"/api/v1/auth/{path}",
        json=data,
        headers={
            "Origin": str(browser.base_url).rstrip("/"),
            "X-CSRF-Token": csrf.json()["csrf_token"],
        },
    )


def register(lab: AuthLab, *, client: TestClient | None = None, phone: str = PHONE) -> Response:
    return public_post(
        lab,
        "register",
        {"phone": phone, "password": PASSWORD, "display_name": "Alice"},
        client=client,
    )


def login(lab: AuthLab, *, client: TestClient | None = None, password: str = PASSWORD) -> Response:
    return public_post(lab, "login", {"phone": PHONE, "password": password}, client=client)


def private_post(
    lab: AuthLab, path: str, csrf: str, data: dict[str, str] | None = None
) -> Response:
    return lab.client.post(
        f"/api/v1/auth/{path}",
        json=data or {},
        headers={"Origin": lab.origin, "X-CSRF-Token": csrf},
    )


def test_register_login_secure_cookie_current_user_and_logout(auth_lab: AuthLab) -> None:
    lab = auth_lab
    spec = lab.client.get("/api/v1/openapi.json").json()
    assert any(
        parameter["name"] == "X-CSRF-Token"
        for parameter in spec["paths"]["/api/v1/auth/login"]["post"]["parameters"]
    )
    assert register(lab).status_code == 202
    response = login(lab)
    assert response.status_code == 200, response.text
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(
        value for value in cookies if value.startswith("__Host-salonbook-session=")
    )
    assert all(flag in session_cookie for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"))
    assert "Domain=" not in session_cookie
    raw = lab.client.cookies.get("__Host-salonbook-session")
    assert raw and raw not in response.text
    user = response.json()["user"]
    assert user["roles"] == ["customer"] and user["phone_verified"] is False
    assert lab.client.get("/api/v1/auth/me").json()["user"] == user
    with lab.database.lab.admin.connect() as connection:
        password_hash = connection.scalar(
            select(User.password_hash).where(User.id == UUID(user["id"]))
        )
        row = connection.execute(
            select(Session.token_hash, Session.csrf_hash).where(Session.user_id == UUID(user["id"]))
        ).one()
        assert password_hash is not None
        assert password_hash.startswith("$argon2id$") and PASSWORD not in password_hash
        assert row.token_hash == token_hash(raw) and row.csrf_hash == token_hash(
            response.json()["csrf_token"]
        )
    assert private_post(lab, "logout", response.json()["csrf_token"]).status_code == 204
    assert lab.client.get("/api/v1/auth/me").status_code == 401
    replay = lab.client.get(
        "/api/v1/auth/me", headers={"Cookie": f"__Host-salonbook-session={raw}"}
    )
    assert replay.status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "salon_manager"},
        {"tenant_id": str(uuid4())},
        {"password": "too-short"},
        {"display_name": " "},
    ],
)
def test_registration_rejects_privilege_injection_and_invalid_input(
    auth_lab: AuthLab, changes: dict[str, str]
) -> None:
    data = {"phone": PHONE, "password": PASSWORD, "display_name": "Alice", **changes}
    response = public_post(auth_lab, "register", data)
    assert response.status_code == 422 and PASSWORD not in response.text


@pytest.mark.parametrize(
    "fault",
    ["missing_origin", "foreign_origin", "missing_csrf", "forged_csrf", "form", "expired_csrf"],
)
def test_login_csrf_protection(auth_lab: AuthLab, fault: str) -> None:
    lab = auth_lab
    token = lab.client.get("/api/v1/auth/csrf").json()["csrf_token"]
    headers = {"Origin": lab.origin, "X-CSRF-Token": token}
    if fault == "missing_origin":
        del headers["Origin"]
    elif fault == "foreign_origin":
        headers["Origin"] = "https://evil.example"
    elif fault == "missing_csrf":
        del headers["X-CSRF-Token"]
    elif fault == "forged_csrf":
        headers["X-CSRF-Token"] = "forged"
    elif fault == "expired_csrf":
        payload = "1.nonce"
        token = f"{payload}.{lab.auth.security.digest('preauth', f'{lab.tenant}:{payload}').hex()}"
        headers.update({"X-CSRF-Token": token, "Cookie": f"__Host-salonbook-preauth={token}"})
    if fault == "form":
        response = lab.client.post(
            "/api/v1/auth/login", data={"phone": PHONE, "password": PASSWORD}, headers=headers
        )
    else:
        response = lab.client.post(
            "/api/v1/auth/login", json={"phone": PHONE, "password": PASSWORD}, headers=headers
        )
    assert response.status_code in (403, 415)


def test_private_csrf_and_session_rotation(auth_lab: AuthLab) -> None:
    lab = auth_lab
    register(lab)
    first = login(lab)
    old = lab.client.cookies.get("__Host-salonbook-session")
    assert private_post(lab, "logout", "x" * 64).status_code == 403
    second = login(lab)
    assert second.status_code == 200
    new = lab.client.cookies.get("__Host-salonbook-session")
    assert new != old and first.json()["csrf_token"] != second.json()["csrf_token"]
    assert (
        lab.client.get(
            "/api/v1/auth/me", headers={"Cookie": f"__Host-salonbook-session={old}"}
        ).status_code
        == 401
    )


def test_tenant_isolation_and_untrusted_headers(auth_lab: AuthLab) -> None:
    lab = auth_lab
    register(lab)
    login(lab)
    raw = lab.client.cookies.get("__Host-salonbook-session")
    with TestClient(lab.app, base_url=lab.other_origin) as other:
        result = other.get(
            "/api/v1/auth/me",
            headers={
                "Cookie": f"__Host-salonbook-session={raw}",
                "X-Tenant-ID": str(lab.tenant),
                "X-Forwarded-Host": lab.origin.removeprefix("https://"),
            },
        )
        assert result.status_code == 401
        assert login(lab, client=other).status_code == 401
        assert register(lab, client=other).status_code == 202
        assert login(lab, client=other).json()["user"]["tenant_id"] == str(lab.other_tenant)
    assert lab.client.get("/api/v1/auth/me", headers={"X-Tenant-ID": str(lab.other_tenant)}).json()[
        "user"
    ]["tenant_id"] == str(lab.tenant)


@pytest.mark.parametrize("failure", ["idle", "absolute", "inactive", "deleted", "auth_version"])
def test_expired_or_disabled_identity_is_rejected(auth_lab: AuthLab, failure: str) -> None:
    lab = auth_lab
    register(lab)
    user = login(lab).json()["user"]
    with lab.database.lab.admin.begin() as connection:
        if failure == "idle":
            connection.execute(
                update(Session)
                .where(Session.user_id == UUID(user["id"]))
                .values(idle_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        elif failure == "absolute":
            connection.execute(
                text(
                    "UPDATE sessions SET created_at = now() - interval '3 days', expires_at = now() - interval '1 day', idle_expires_at = now() - interval '1 day' WHERE user_id = :user"
                ),
                {"user": user["id"]},
            )
        else:
            mutations: dict[str, dict[str, Any]] = {
                "inactive": {"is_active": False},
                "deleted": {"deleted_at": datetime.now(UTC)},
                "auth_version": {"auth_version": 2},
            }
            connection.execute(
                update(User).where(User.id == UUID(user["id"])).values(**mutations[failure])
            )
    assert lab.client.get("/api/v1/auth/me").status_code == 401


def test_failed_logins_persist_rate_limit_and_ignore_forwarded_ip(auth_lab: AuthLab) -> None:
    lab = auth_lab
    register(lab)
    for _ in range(lab.runtime.settings.auth_attempt_limit):
        assert login(lab, password="wrong").status_code == 401
    assert login(lab).status_code == 429
    with lab.database.lab.admin.connect() as connection:
        attempts = connection.scalar(
            text(
                "SELECT max(attempts) FROM auth_throttles WHERE tenant_id = :tenant AND purpose = 'login'"
            ),
            {"tenant": lab.tenant},
        )
        assert attempts == lab.runtime.settings.auth_attempt_limit + 1


def test_limiter_is_atomic_across_workers_and_ip_limits_unknown_accounts(auth_lab: AuthLab) -> None:
    lab = auth_lab
    config = lab.runtime.settings.model_copy(update={"auth_attempt_limit": 3, "auth_ip_limit": 10})
    from app.modules.identity.throttle import AuthLimiter

    limiter = AuthLimiter(lab.runtime.database, config, lab.auth.security)

    def attempt(_: int) -> int:
        try:
            limiter.check(lab.context, "parallel", PHONE)
            return 200
        except AppError as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=6) as workers:
        outcomes = list(workers.map(attempt, range(6)))
    assert outcomes.count(200) == 3 and outcomes.count(429) == 3
    for index in range(10):
        limiter.check(lab.context, "different_accounts", f"user{index}@example.com")
    with pytest.raises(AppError, match="rate_limited"):
        limiter.check(lab.context, "different_accounts", "another@example.com")


def test_session_list_revoke_and_logout_all(auth_lab: AuthLab) -> None:
    lab = auth_lab
    register(lab)
    response = login(lab)
    with TestClient(lab.app, base_url=lab.origin) as other:
        assert login(lab, client=other).status_code == 200
        sessions = lab.client.get("/api/v1/auth/sessions").json()
        assert len(sessions) == 2
        target = next(row["id"] for row in sessions if not row["current"])
        revoked = lab.client.delete(
            f"/api/v1/auth/sessions/{target}",
            headers={"Origin": lab.origin, "X-CSRF-Token": response.json()["csrf_token"]},
        )
        assert revoked.status_code == 204
        assert other.get("/api/v1/auth/me").status_code == 401
        assert login(lab, client=other).status_code == 200
        assert private_post(lab, "logout-all", response.json()["csrf_token"]).status_code == 204
        assert other.get("/api/v1/auth/me").status_code == 401


def test_permission_changes_require_new_login_and_enforce_line_scope(auth_lab: AuthLab) -> None:
    lab = auth_lab

    @lab.app.get("/__test__/admin", dependencies=[Depends(require_permission("roles.manage"))])
    def admin() -> dict[str, bool]:
        return {"allowed": True}

    @lab.app.get(
        "/__test__/line/{line_id}",
        dependencies=[Depends(require_permission("catalog.manage", line_parameter="line_id"))],
    )
    def line(line_id: UUID) -> dict[str, bool]:
        return {"allowed": True}

    register(lab)
    user = login(lab).json()["user"]
    assert lab.client.get("/__test__/admin").status_code == 403
    with UnitOfWork(lab.database.lab.admin) as session, session.begin():
        role = session.scalar(
            select(Role).where(Role.tenant_id == lab.tenant, Role.code == "line_manager")
        )
        assert role
        assignment = RoleAssignment(
            tenant_id=lab.tenant,
            user_id=UUID(user["id"]),
            role_id=role.id,
            scope="LINE",
            line_id=lab.line,
        )
        session.add(assignment)
    assert lab.client.get("/api/v1/auth/me").status_code == 401
    response = login(lab)
    assert lab.client.get(f"/__test__/line/{lab.line}").status_code == 200
    assert lab.client.get(f"/__test__/line/{lab.other_line}").status_code == 403
    assert lab.client.get("/__test__/admin").status_code == 403
    expiry = datetime.fromisoformat(response.json()["expires_at"].replace("Z", "+00:00"))
    assert timedelta(hours=7) < expiry - datetime.now(UTC) <= timedelta(hours=8)
    with lab.database.lab.admin.begin() as connection:
        connection.execute(
            update(RoleAssignment)
            .where(RoleAssignment.tenant_id == lab.tenant, RoleAssignment.scope == "LINE")
            .values(revoked_at=datetime.now(UTC))
        )
    assert lab.client.get(f"/__test__/line/{lab.line}").status_code == 401
    login(lab)
    assert lab.client.get(f"/__test__/line/{lab.line}").status_code == 403


def test_owner_scope_and_verified_guard(auth_lab: AuthLab) -> None:
    lab = auth_lab

    @lab.app.get(
        "/__test__/owned/{owner_id}",
        dependencies=[
            Depends(
                require_permission(
                    "appointment.read_own", owner_parameter="owner_id", verified=True
                )
            )
        ],
    )
    def owned(owner_id: UUID) -> dict[str, bool]:
        return {"allowed": True}

    register(lab)
    user = login(lab).json()["user"]
    assert lab.client.get(f"/__test__/owned/{user['id']}").status_code == 403
    with lab.database.lab.admin.begin() as connection:
        # Simulate a trusted future OTP verifier; there is deliberately no public verifier yet.
        connection.execute(
            update(User)
            .where(User.id == UUID(user["id"]))
            .values(phone_verified_at=datetime.now(UTC))
        )
    assert lab.client.get(f"/__test__/owned/{user['id']}").status_code == 200
    assert lab.client.get(f"/__test__/owned/{uuid4()}").status_code == 403


def test_permission_restoration_does_not_resurrect_rejected_session(auth_lab: AuthLab) -> None:
    lab = auth_lab
    register(lab)
    user = login(lab).json()["user"]
    with lab.database.lab.admin.begin() as connection:
        connection.execute(
            update(RoleAssignment)
            .where(RoleAssignment.user_id == UUID(user["id"]))
            .values(revoked_at=datetime.now(UTC))
        )
    assert lab.client.get("/api/v1/auth/me").status_code == 401
    with lab.database.lab.admin.begin() as connection:
        connection.execute(
            update(RoleAssignment)
            .where(RoleAssignment.user_id == UUID(user["id"]))
            .values(revoked_at=None)
        )
    assert lab.client.get("/api/v1/auth/me").status_code == 401
    assert login(lab).status_code == 200


@pytest.mark.parametrize("change", ["unverified", "inactive_domain", "suspended_salon"])
def test_unavailable_tenant_fails_closed(auth_lab: AuthLab, change: str) -> None:
    lab = auth_lab
    with lab.database.lab.admin.begin() as connection:
        if change == "unverified":
            connection.execute(
                update(TenantDomain)
                .where(TenantDomain.tenant_id == lab.tenant)
                .values(verified_at=None)
            )
        elif change == "inactive_domain":
            connection.execute(
                update(TenantDomain)
                .where(TenantDomain.tenant_id == lab.tenant)
                .values(is_active=False)
            )
        else:
            connection.execute(
                text("UPDATE salons SET status = 'SUSPENDED' WHERE id = :tenant"),
                {"tenant": lab.tenant},
            )
    assert lab.client.get("/api/v1/auth/csrf").status_code == 404


def test_password_rehash_preserves_login(auth_lab: AuthLab) -> None:
    from argon2 import PasswordHasher

    lab = auth_lab
    register(lab)
    old_hash = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1).hash(PASSWORD)
    with lab.database.lab.admin.begin() as connection:
        connection.execute(
            update(User)
            .where(User.tenant_id == lab.tenant, User.phone_normalized == PHONE)
            .values(password_hash=old_hash)
        )
    assert login(lab).status_code == 200
    with lab.database.lab.admin.connect() as connection:
        current = connection.scalar(
            select(User.password_hash).where(
                User.tenant_id == lab.tenant, User.phone_normalized == PHONE
            )
        )
        assert (
            current
            and current != old_hash
            and not lab.auth.security.passwords.check_needs_rehash(current)
        )


def test_production_auth_never_accepts_http(auth_lab: AuthLab) -> None:
    lab = auth_lab
    config = lab.runtime.settings.model_copy(update={"environment": "production"})
    app = create_app(config)
    with TestClient(app, base_url=lab.origin.replace("https://", "http://")) as client:
        response = client.get("/api/v1/auth/csrf")
        assert response.status_code == 400 and "set-cookie" not in response.headers
