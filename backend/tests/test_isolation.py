from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import Database, add, tenant_connection

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "table",
    [
        "users",
        "customer_profiles",
        "employee_profiles",
        "lines",
        "services",
        "line_services",
        "employee_lines",
        "employee_services",
        "roles",
        "salon_settings",
        "calendars",
    ],
)
def test_rls_filters_actual_tenant_data(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]], table: str
) -> None:
    a, b = tenants
    with tenant_connection(database, a["tenant"]) as connection:
        rows = connection.execute(text(f'SELECT DISTINCT tenant_id FROM "{table}"')).scalars().all()
        assert rows == [a["tenant"]]
        assert (
            connection.scalar(
                text(f'SELECT count(*) FROM "{table}" WHERE tenant_id = :tenant'),
                {"tenant": b["tenant"]},
            )
            == 0
        )


def test_missing_context_fails_closed_on_read_and_write(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    with database.runtime.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == 0
    with pytest.raises(DBAPIError) as caught, database.runtime.begin() as connection:
        add(connection, "lines", tenant_id=tenants[0]["tenant"], name="Rejected", slug="rejected")
    assert getattr(caught.value.orig, "sqlstate", None) == "42501"


def test_cross_tenant_write_and_reference_are_rejected(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    a, b = tenants
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, a["tenant"]) as connection,
    ):
        add(connection, "lines", tenant_id=b["tenant"], name="Rejected", slug="rejected")
    assert getattr(caught.value.orig, "sqlstate", None) == "42501"
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, a["tenant"]) as connection,
    ):
        add(connection, "customer_profiles", tenant_id=a["tenant"], user_id=b["customer_user"])
    assert getattr(caught.value.orig, "sqlstate", None) == "23503"


def test_identity_cannot_be_moved_even_by_privileged_connection(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    a, b = tenants
    with pytest.raises(DBAPIError) as caught, database.lab.admin.begin() as connection:
        connection.execute(
            text("UPDATE users SET tenant_id = :other WHERE tenant_id = :tenant"),
            {"other": b["tenant"], "tenant": a["tenant"]},
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"


@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_pool_reuse_clears_transaction_local_tenant(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]], finish: str
) -> None:
    engine = create_engine(database.lab.runtime_url, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenants[0]["tenant"])},
            )
            assert connection.scalar(text("SELECT count(*) FROM users")) == 2
            getattr(connection, finish)()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM users")) == 0
    finally:
        engine.dispose()


def test_owner_is_subject_to_force_rls(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    with database.lab.owner.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == 0
        assert (
            connection.scalar(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
            is False
        )


@pytest.mark.parametrize(
    "table",
    [
        "platform_users",
        "platform_sessions",
        "platform_roles",
        "platform_role_assignments",
        "platform_role_permissions",
        "platform_audit_logs",
        "support_grants",
        "tenant_domains",
        "alembic_version",
    ],
)
def test_runtime_cannot_read_control_plane(database: Database, table: str) -> None:
    with pytest.raises(DBAPIError) as caught, database.runtime.connect() as connection:
        connection.execute(text(f'SELECT * FROM "{table}"'))
    assert getattr(caught.value.orig, "sqlstate", None) == "42501"


def test_hostname_registry_only_publishes_verified_active_domains(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    from datetime import UTC, datetime

    prefix = uuid4().hex
    with database.lab.admin.begin() as connection:
        for suffix, active, verified in (
            ("valid", True, datetime.now(UTC)),
            ("unverified", True, None),
            ("disabled", False, datetime.now(UTC)),
        ):
            add(
                connection,
                "tenant_domains",
                tenant_id=tenants[0]["tenant"],
                hostname=f"{prefix}-{suffix}.example.test",
                is_active=active,
                verified_at=verified,
            )
    with database.runtime.connect() as connection:
        domains = (
            connection.execute(
                text("SELECT hostname FROM tenant_hostnames WHERE hostname LIKE :pattern"),
                {"pattern": prefix + "%"},
            )
            .scalars()
            .all()
        )
    assert domains == [f"{prefix}-valid.example.test"]


def test_runtime_is_unprivileged_and_cannot_truncate(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    with database.runtime.connect() as connection:
        assert connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
            )
        ).one() == (False, False, False, False)
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, tenants[0]["tenant"]) as connection,
    ):
        connection.exec_driver_sql("TRUNCATE users")
    assert getattr(caught.value.orig, "sqlstate", None) == "42501"
