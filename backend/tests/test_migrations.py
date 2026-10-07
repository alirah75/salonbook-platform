from unittest.mock import patch

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.db.models import Base
from app.db.schema import REQUIRED_SCHEMA_REVISION
from scripts.postgres_lab import temporary_postgres
from tests.conftest import Database, add, seed_tenant

pytestmark = pytest.mark.postgres


def test_scheduling_migration_preserves_custom_roles_and_updates_existing_system_roles() -> None:
    with (
        temporary_postgres() as lab,
        patch.dict("os.environ", {"DATABASE_MIGRATION_URL": lab.owner_url}),
    ):
        config = Config("alembic.ini")
        command.upgrade(config, "0007")
        with lab.admin.begin() as connection:
            tenant = add(connection, "salons", name="Existing salon")
            ids = {
                code: add(
                    connection,
                    "roles",
                    tenant_id=tenant,
                    code=code,
                    name=code,
                    is_system=code != "custom",
                )
                for code in ("employee", "line_manager", "salon_manager", "custom")
            }
        command.upgrade(config, "0008")
        with lab.admin.connect() as connection:
            query = text("SELECT permission_code FROM role_permissions WHERE role_id = :role")
            own = {"schedule.read_own", "leave.request_own"}
            management = {"schedule.read", "schedule.manage"}
            assert set(connection.scalars(query, {"role": ids["employee"]})) == own
            assert set(connection.scalars(query, {"role": ids["line_manager"]})) == management
            assert (
                set(connection.scalars(query, {"role": ids["salon_manager"]})) == own | management
            )
            assert set(connection.scalars(query, {"role": ids["custom"]})) == set()
            assert (
                connection.scalar(
                    text(
                        "SELECT bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class WHERE relname IN ('roles', 'role_permissions')"
                    )
                )
                is True
            )
        command.downgrade(config, "0007")
        with lab.admin.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM role_permissions WHERE tenant_id = :tenant"),
                    {"tenant": tenant},
                )
                == 0
            )
        command.upgrade(config, "head")


def test_catalog_migration_rejects_inconsistent_legacy_prices_without_changing_them() -> None:
    with temporary_postgres() as lab:
        with patch.dict("os.environ", {"DATABASE_MIGRATION_URL": lab.owner_url}):
            config = Config("alembic.ini")
            command.upgrade(config, "0006")
            with lab.admin.begin() as connection:
                seed = seed_tenant(connection)
                manager = add(
                    connection,
                    "roles",
                    tenant_id=seed["tenant"],
                    code="line_manager",
                    name="Manager",
                    is_system=True,
                )
                connection.execute(
                    text("UPDATE line_services SET is_free = true WHERE tenant_id = :tenant"),
                    {"tenant": seed["tenant"]},
                )
            with pytest.raises(IntegrityError):
                command.upgrade(config, "head")
            with lab.admin.begin() as connection:
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
                row = connection.execute(
                    text(
                        "SELECT price_amount, is_free FROM line_services WHERE tenant_id = :tenant"
                    ),
                    {"tenant": seed["tenant"]},
                ).one()
                assert tuple(row) == (1_000_000, True)
                # Simulate an operator-reviewed correction; migration never changes financial terms.
                connection.execute(
                    text("UPDATE line_services SET is_free = false WHERE tenant_id = :tenant"),
                    {"tenant": seed["tenant"]},
                )
            command.upgrade(config, "head")
            with lab.admin.connect() as connection:
                assert (
                    connection.scalar(
                        text(
                            "SELECT permission_code FROM role_permissions WHERE role_id = :role AND permission_code = 'staff.assign'"
                        ),
                        {"role": manager},
                    )
                    == "staff.assign"
                )
                assert (
                    connection.scalar(
                        text("SELECT price_amount FROM line_services WHERE tenant_id = :tenant"),
                        {"tenant": seed["tenant"]},
                    )
                    == 1_000_000
                )
            command.downgrade(config, "0006")
            command.upgrade(config, "head")


def test_management_migration_updates_system_roles_even_without_a_domain() -> None:
    with temporary_postgres() as lab:
        with patch.dict("os.environ", {"DATABASE_MIGRATION_URL": lab.owner_url}):
            config = Config("alembic.ini")
            command.upgrade(config, "0005")
            with lab.admin.begin() as connection:
                tenant = connection.scalar(
                    text("INSERT INTO salons (name) VALUES ('No domain yet') RETURNING id")
                )
                manager = connection.scalar(
                    text(
                        "INSERT INTO roles (tenant_id, code, name, is_system) VALUES (:tenant, 'salon_manager', 'Manager', true) RETURNING id"
                    ),
                    {"tenant": tenant},
                )
                custom = connection.scalar(
                    text(
                        "INSERT INTO roles (tenant_id, code, name, is_system) VALUES (:tenant, 'customer', 'Custom legacy role', false) RETURNING id"
                    ),
                    {"tenant": tenant},
                )
                connection.execute(
                    text(
                        "INSERT INTO role_permissions (tenant_id, role_id, permission_code) VALUES (:tenant, :role, 'finance.read')"
                    ),
                    {"tenant": tenant, "role": manager},
                )
            command.upgrade(config, "head")
            with lab.admin.connect() as connection:
                codes = set(
                    connection.scalars(
                        text("SELECT permission_code FROM role_permissions WHERE role_id = :role"),
                        {"role": manager},
                    )
                )
                assert codes >= {
                    "users.manage",
                    "salon.manage",
                    "roles.read",
                    "finance.read",
                    "appointment.create",
                }
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM role_permissions WHERE role_id = :role"),
                        {"role": custom},
                    )
                    == 0
                )
                assert (
                    connection.scalar(
                        text(
                            "SELECT bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class WHERE relname IN ('roles', 'role_permissions')"
                        )
                    )
                    is True
                )
            command.downgrade(config, "0005")
            with lab.admin.connect() as connection:
                codes = set(
                    connection.scalars(
                        text("SELECT permission_code FROM role_permissions WHERE role_id = :role"),
                        {"role": manager},
                    )
                )
                assert "users.manage" not in codes and "finance.read" in codes
                assert (
                    connection.scalar(
                        text(
                            "SELECT bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class WHERE relname IN ('roles', 'role_permissions')"
                        )
                    )
                    is True
                )
            command.upgrade(config, "head")


def test_upgrade_downgrade_and_reupgrade_are_reproducible() -> None:
    # A second disposable DB: existing test/application data is never downgraded.
    with temporary_postgres() as lab:
        with patch.dict("os.environ", {"DATABASE_MIGRATION_URL": lab.owner_url}):
            config = Config("alembic.ini")
            command.upgrade(config, "head")
            command.check(config)
            with lab.owner.connect() as connection:
                assert (
                    connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == REQUIRED_SCHEMA_REVISION
                )
            command.downgrade(config, "base")
            with lab.admin.connect() as connection:
                remaining = (
                    connection.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                    )
                    .scalars()
                    .all()
                )
                assert remaining == ["alembic_version"]
            command.upgrade(config, "head")
            command.check(config)


def test_mobile_migration_preserves_legacy_accounts_and_refuses_lossy_rollback() -> None:
    with temporary_postgres() as lab:
        with patch.dict("os.environ", {"DATABASE_MIGRATION_URL": lab.owner_url}):
            config = Config("alembic.ini")
            command.upgrade(config, "0004")
            with lab.admin.begin() as connection:
                tenant = connection.scalar(
                    text("INSERT INTO salons (name) VALUES ('Legacy') RETURNING id")
                )
                user = connection.scalar(
                    text(
                        "INSERT INTO users (tenant_id, email_normalized, phone, password_hash, display_name) VALUES (:tenant, 'legacy@example.test', '09123456789', 'legacy-hash', 'Legacy') RETURNING id"
                    ),
                    {"tenant": tenant},
                )
            command.upgrade(config, "head")
            with lab.admin.begin() as connection:
                row = connection.execute(
                    text(
                        "SELECT email_normalized, phone, phone_normalized, phone_verified_at, password_hash FROM users WHERE id = :user"
                    ),
                    {"user": user},
                ).one()
                assert tuple(row) == (
                    "legacy@example.test",
                    "09123456789",
                    None,
                    None,
                    "legacy-hash",
                )
                connection.execute(
                    text(
                        "INSERT INTO users (tenant_id, phone_normalized, password_hash, display_name) VALUES (:tenant, '+989123456789', 'mobile-hash', 'Mobile')"
                    ),
                    {"tenant": tenant},
                )
            with pytest.raises(IntegrityError):
                command.downgrade(config, "0004")
            with lab.admin.connect() as connection:
                assert (
                    connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == REQUIRED_SCHEMA_REVISION
                )
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM users WHERE tenant_id = :tenant"),
                        {"tenant": tenant},
                    )
                    == 2
                )


def test_database_security_catalog_matches_all_tenant_tables(database: Database) -> None:
    expected = {
        table.name
        for table in Base.metadata.tables.values()
        if "tenant_id" in table.c and table.name != "tenant_domains"
    } | {"salons"}
    with database.lab.admin.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'"
            )
        ).all()
        secured = {name for name, enabled, forced in rows if enabled and forced}
        assert secured == expected
        for table in expected:
            policy = connection.execute(
                text(
                    "SELECT cmd, qual, with_check FROM pg_policies WHERE schemaname = 'public' AND tablename = :table"
                ),
                {"table": table},
            ).one()
            assert policy.cmd == "ALL"
            assert "app.tenant_id" in policy.qual and "app.tenant_id" in policy.with_check
        exclusion = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ex_appointments_employee_period'"
            )
        )
        assert "EXCLUDE USING gist" in exclusion
        assert "employee_id WITH =" in exclusion
        assert "occupied_period WITH &&" in exclusion
        assert "AWAITING_PAYMENT" in exclusion and "CONFIRMED" in exclusion


def test_all_constraints_are_validated(database: Database) -> None:
    with database.lab.admin.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_constraint WHERE connamespace = 'public'::regnamespace AND NOT convalidated"
                )
            )
            == 0
        )
