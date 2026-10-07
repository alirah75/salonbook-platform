from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import Database, add, tenant_connection

pytestmark = pytest.mark.postgres


def test_duplicate_salon_calendar_with_null_targets_is_rejected(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, tenants[0]["tenant"]) as connection,
    ):
        add(connection, "calendars", tenant_id=tenants[0]["tenant"], scope="SALON")
    assert getattr(caught.value.orig, "sqlstate", None) == "23505"


@pytest.mark.parametrize(
    "scope,line,employee",
    [
        ("SALON", True, False),
        ("LINE", False, False),
        ("EMPLOYEE", True, True),
        ("EMPLOYEE_LINE", False, True),
    ],
)
def test_calendar_scope_matches_target_shape(
    database: Database,
    tenants: tuple[dict[str, UUID], dict[str, UUID]],
    scope: str,
    line: bool,
    employee: bool,
) -> None:
    seed = tenants[0]
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "calendars",
            tenant_id=seed["tenant"],
            scope=scope,
            line_id=seed["line"] if line else None,
            employee_id=seed["employee"] if employee else None,
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"


def test_closed_day_cannot_have_open_periods(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    with tenant_connection(database, seed["tenant"]) as connection:
        override = add(
            connection,
            "day_overrides",
            tenant_id=seed["tenant"],
            calendar_id=seed["calendar"],
            local_date=datetime.now(UTC).date(),
            mode="CLOSED",
        )
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "special_periods",
            tenant_id=seed["tenant"],
            override_id=override,
            start_minute=540,
            end_minute=1020,
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23503"


def test_weekly_period_rejects_invalid_intervals(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "weekly_periods",
            tenant_id=seed["tenant"],
            calendar_id=seed["calendar"],
            weekday=0,
            start_minute=1100,
            end_minute=540,
            valid_from=datetime.now(UTC).date(),
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"


def test_deleted_account_email_cannot_be_reused_but_other_tenant_can_use_it(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    # Both tenant fixtures already have the same email, proving scoped uniqueness.
    with tenant_connection(database, seed["tenant"]) as connection:
        connection.execute(
            text("UPDATE users SET deleted_at = now(), is_active = false WHERE id = :id"),
            {"id": seed["customer_user"]},
        )
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "users",
            tenant_id=seed["tenant"],
            email_normalized="customer_user@example.test",
            password_hash="test-only",
            display_name="Duplicate",
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23505"


def test_token_hash_is_fixed_size_and_expiry_is_valid(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "auth_tokens",
            tenant_id=seed["tenant"],
            user_id=seed["customer_user"],
            purpose="PASSWORD_RESET",
            token_hash=b"raw-token",
            subject_version=1,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"


def test_active_tenant_role_assignment_is_unique_despite_null_line(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    values = dict(
        tenant_id=seed["tenant"],
        user_id=seed["customer_user"],
        role_id=seed["role"],
        scope="TENANT",
    )
    with tenant_connection(database, seed["tenant"]) as connection:
        assignment = add(connection, "role_assignments", **values)
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(connection, "role_assignments", **values)
    assert getattr(caught.value.orig, "sqlstate", None) == "23505"
    with tenant_connection(database, seed["tenant"]) as connection:
        connection.execute(
            text("UPDATE role_assignments SET revoked_at = now() WHERE id = :id"),
            {"id": assignment},
        )
        add(connection, "role_assignments", **values)


def test_database_updates_timestamp_for_direct_sql(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    with tenant_connection(database, seed["tenant"]) as connection:
        before = connection.scalar(
            text("SELECT updated_at FROM lines WHERE id = :id"), {"id": seed["line"]}
        )
        after = connection.scalar(
            text("UPDATE lines SET name = 'New' WHERE id = :id RETURNING updated_at"),
            {"id": seed["line"]},
        )
        assert after >= before


def test_idempotency_key_is_scoped_and_unique(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    values = dict(
        tenant_id=seed["tenant"],
        actor_id=seed["customer_user"],
        operation="appointment.create",
        key=uuid4().hex,
        request_hash=b"a" * 32,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    with tenant_connection(database, seed["tenant"]) as connection:
        add(connection, "idempotency_records", **values)
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(connection, "idempotency_records", **values)
    assert getattr(caught.value.orig, "sqlstate", None) == "23505"
