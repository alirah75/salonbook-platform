import secrets
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import Settings
from app.core.errors import AppError
from app.db.database import Database as ApplicationDatabase
from app.db.database import DatabaseNotReady
from app.main import create_app
from app.modules.access.models import Role, RoleAssignment
from app.modules.identity.models import CustomerProfile, User
from app.modules.identity.schemas import RegisterInput
from app.modules.identity.security import Security
from app.modules.operations.models import PlatformAuditLog
from app.modules.tenancy.administration import (
    TenantAdministration,
    TenantCreate,
    canonical_hostname,
)
from app.modules.tenancy.locks import require_active_tenant
from app.modules.tenancy.models import CalendarControl, Salon, SalonSettings, TenantDomain
from scripts.postgres_lab import execute_sql
from tests.conftest import Database
from tests.test_authentication import PASSWORD, AuthLab, login, register
from tests.test_authentication import auth_lab as auth_lab_fixture

auth_lab = auth_lab_fixture

pytestmark = pytest.mark.postgres


@pytest.fixture
def control(database: Database) -> Iterator[TenantAdministration]:
    name = f"control_{uuid4().hex}"
    password = secrets.token_urlsafe(32)
    with database.lab.admin.begin() as connection:
        execute_sql(connection, Path("sql/control_grants.sql").read_text(encoding="utf-8"))
        connection.exec_driver_sql(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}"
            )
            .format(sql.Identifier(name), sql.Literal(password))
            .as_string()
        )
        connection.exec_driver_sql(
            sql.SQL("GRANT salonbook_control TO {}").format(sql.Identifier(name)).as_string()
        )
    engine = create_engine(
        database.lab.owner.url.set(username=name, password=password), hide_parameters=True
    )
    try:
        yield TenantAdministration(engine, Security(Fernet.generate_key().decode()))
    finally:
        engine.dispose()
        with database.lab.admin.begin() as connection:
            connection.exec_driver_sql(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(name)).as_string()
            )


def payload() -> TenantCreate:
    return TenantCreate(
        name="سالن جدید",
        hostname=f"salon-{uuid4().hex}.example",
        manager=RegisterInput(
            phone="۰۹۱۲۱۲۳۴۵۶۷", display_name="Manager", password=SecretStr(PASSWORD)
        ),
    )


def test_atomic_provisioning_with_a_dedicated_control_role(
    database: Database, control: TenantAdministration
) -> None:
    data = payload()
    tenant = control.create(data, "New salon onboarding")
    assert control.show(tenant).name == data.name
    with database.lab.admin.connect() as connection:
        assert connection.scalar(select(SalonSettings.id).where(SalonSettings.tenant_id == tenant))
        assert connection.scalar(
            select(CalendarControl.id).where(CalendarControl.tenant_id == tenant)
        )
        user = connection.execute(select(User).where(User.tenant_id == tenant)).one()
        assert user.phone_normalized == "+989121234567" and user.email_normalized is None
        assert user.phone_verified_at is None and user.password_hash != PASSWORD
        assert (
            connection.scalar(
                select(CustomerProfile.contact_preference).where(CustomerProfile.user_id == user.id)
            )
            == "NONE"
        )
        roles = set(
            connection.scalars(
                select(Role.code)
                .join(
                    RoleAssignment,
                    (RoleAssignment.role_id == Role.id)
                    & (RoleAssignment.tenant_id == Role.tenant_id),
                )
                .where(RoleAssignment.user_id == user.id)
            )
        )
        assert roles == {"customer", "salon_manager"}
        before = connection.scalar(select(func.count()).select_from(Salon))
        domain = connection.execute(
            select(TenantDomain).where(TenantDomain.tenant_id == tenant)
        ).one()
        assert not domain.is_active and domain.verified_at is None
    with pytest.raises(IntegrityError):
        control.create(data, "Duplicate domain must roll back everything")
    with database.lab.admin.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Salon)) == before
        audit = connection.execute(
            select(PlatformAuditLog.event_data).where(PlatformAuditLog.entity_id == tenant)
        ).scalar_one()
        assert audit["reason"] == "New salon onboarding" and audit["source"] == "trusted_operator"
        assert audit["database_actor"] == control.engine.url.username
        assert PASSWORD not in str(audit) and data.manager.phone not in str(audit)
    control.domain(
        tenant, data.hostname, "activate", "Operator verified domain ownership and routing"
    )
    config = Settings(
        environment="test",
        database_url=SecretStr(database.lab.runtime_url),
        auth_key=SecretStr(Fernet.generate_key().decode()),
        allowed_hosts=(data.hostname,),
    )
    with TestClient(create_app(config), base_url=f"https://{data.hostname}") as client:
        csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        result = client.post(
            "/api/v1/auth/login",
            json={"phone": data.manager.phone, "password": PASSWORD},
            headers={"Origin": f"https://{data.hostname}", "X-CSRF-Token": csrf},
        )
        assert result.status_code == 200
        assert client.get("/api/v1/users").status_code == 200
        assert client.get("/api/v1/roles").status_code == 200


def test_control_credentials_cannot_run_the_api_and_runtime_cannot_provision(
    database: Database, control: TenantAdministration
) -> None:
    app_db = ApplicationDatabase(
        Settings(database_url=SecretStr(control.engine.url.render_as_string(hide_password=False)))
    )
    try:
        with pytest.raises(DatabaseNotReady, match="unsafe_database_role"):
            app_db.validate_ready()
    finally:
        app_db.dispose()
    service = TenantAdministration(database.runtime, control.security)
    with pytest.raises(AppError, match="control_plane_required"):
        service.create(payload(), "Unauthorized creation")
    with control.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM salons")) == 0
    for statement in (
        "SELECT * FROM payment_transactions",
        "ALTER TABLE salons ADD COLUMN forbidden text",
    ):
        with pytest.raises(DBAPIError), control.engine.begin() as connection:
            connection.execute(text(statement))


def test_suspend_resume_and_close_block_stale_context_and_old_sessions(
    auth_lab: AuthLab, control: TenantAdministration
) -> None:
    lab = auth_lab
    register(lab)
    response = login(lab)
    assert response.status_code == 200
    raw = lab.client.cookies.get("__Host-salonbook-session")
    assert raw is not None
    control.status(lab.tenant, "SUSPENDED", "Operator suspension")
    assert lab.client.get("/api/v1/auth/me").status_code == 404
    with pytest.raises(AppError, match="unknown_salon"):
        lab.auth.sessions.current(lab.context, raw)
    with pytest.raises(AppError, match="unknown_salon"):
        lab.auth.accounts.login(lab.context, "+989123456789", PASSWORD)
    with pytest.raises(AppError, match="unknown_salon"):
        lab.auth.accounts.register(
            lab.context,
            RegisterInput(phone="09121234567", display_name="New", password=SecretStr(PASSWORD)),
        )
    control.status(lab.tenant, "ACTIVE", "Operator reactivation")
    assert lab.client.get("/api/v1/auth/me").status_code == 401
    assert login(lab).status_code == 200
    control.status(lab.tenant, "CLOSED", "Salon permanently closed")
    with pytest.raises(AppError, match="salon_closed"):
        control.status(lab.tenant, "ACTIVE", "Invalid reopening")


def test_suspension_waits_for_an_inflight_authorized_transaction(
    auth_lab: AuthLab, control: TenantAdministration
) -> None:
    lab = auth_lab
    register(lab)
    assert login(lab).status_code == 200
    # A held shared lifecycle lock gives deterministic ordering without sleeps.
    with ThreadPoolExecutor(max_workers=1) as pool:
        with lab.runtime.database.transaction(lab.tenant) as session:
            require_active_tenant(session, lab.tenant)
            future = pool.submit(
                control.status, lab.tenant, "SUSPENDED", "Concurrent operator suspension"
            )
            assert session.scalar(select(Salon.status).where(Salon.id == lab.tenant)) == "ACTIVE"
        future.result(timeout=10)
    assert control.show(lab.tenant).status == "SUSPENDED"
    assert lab.client.get("/api/v1/auth/me").status_code == 404


def test_domain_registry_is_explicit_and_cannot_move_between_tenants(
    database: Database, control: TenantAdministration
) -> None:
    first, second = payload(), payload()
    one = control.create(first, "First tenant")
    two = control.create(second, "Second tenant")
    with database.runtime.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT tenant_id FROM tenant_hostnames WHERE hostname = :host"),
                {"host": first.hostname},
            )
            is None
        )
    control.domain(one, first.hostname, "activate", "Ownership verified")
    with pytest.raises(IntegrityError):
        control.domain(two, first.hostname, "add", "Cannot reassign another tenant's domain")
    with pytest.raises(AppError, match="not_found"):
        control.domain(two, first.hostname, "activate", "Wrong tenant")
    control.domain(one, first.hostname, "disable", "Domain retired")
    with database.runtime.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT tenant_id FROM tenant_hostnames WHERE hostname = :host"),
                {"host": first.hostname},
            )
            is None
        )
    alternate = f"alternate-{uuid4().hex}.example"
    control.domain(one, alternate, "add", "Additional salon hostname")
    control.domain(one, alternate, "activate", "Ownership verified")
    with database.runtime.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT tenant_id FROM tenant_hostnames WHERE hostname = :host"),
                {"host": alternate},
            )
            == one
        )


def test_operator_reason_is_required_and_rolls_back(
    control: TenantAdministration, database: Database
) -> None:
    with database.lab.admin.connect() as connection:
        before = connection.scalar(select(func.count()).select_from(Salon))
    with pytest.raises(ValidationError):
        control.create(payload(), " ")
    with database.lab.admin.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Salon)) == before


def test_retired_domain_invalidates_a_previously_resolved_context(
    auth_lab: AuthLab, control: TenantAdministration
) -> None:
    lab = auth_lab
    register(lab)
    assert login(lab).status_code == 200
    raw = lab.client.cookies.get("__Host-salonbook-session")
    assert raw is not None
    context = lab.context
    control.domain(lab.tenant, lab.origin.removeprefix("https://"), "disable", "Domain retired")
    with pytest.raises(AppError, match="unknown_salon"):
        lab.auth.sessions.current(context, raw)
    assert lab.client.get("/api/v1/auth/me").status_code == 404


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com",
        "example.com:443",
        "*.example.com",
        "bad/name",
        "-bad.example",
        "",
        "a..example",
    ],
)
def test_invalid_domains_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        canonical_hostname(value)


def test_hostname_canonicalization() -> None:
    assert canonical_hostname("  SALON.Example. ") == "salon.example"
    assert canonical_hostname("127.0.0.1") == "127.0.0.1"


def test_first_manager_bootstrap_is_explicit_tenant_bound_and_invalidates_sessions(
    auth_lab: AuthLab, control: TenantAdministration
) -> None:
    lab = auth_lab
    register(lab)
    response = login(lab)
    user_id = UUID(response.json()["user"]["id"])
    with pytest.raises(AppError, match="not_found"):
        control.bootstrap_manager(lab.other_tenant, user_id, "Wrong tenant")
    control.bootstrap_manager(lab.tenant, user_id, "Operator reviewed existing account ownership")
    assert lab.client.get("/api/v1/auth/me").status_code == 401
    assert login(lab).status_code == 200
    assert lab.client.get("/api/v1/users").status_code == 200
    with pytest.raises(AppError, match="manager_exists"):
        control.bootstrap_manager(lab.tenant, user_id, "Cannot appoint again")
