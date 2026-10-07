from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import Database, add, appointment_values, tenant_connection

pytestmark = pytest.mark.postgres


def test_fifty_concurrent_reservations_with_lock_protocol_have_one_winner(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    customers = []
    with database.lab.admin.begin() as connection:
        for number in range(50):
            user = add(
                connection,
                "users",
                tenant_id=seed["tenant"],
                email_normalized=f"race{number}@example.test",
                password_hash="test-only",
                display_name="Race",
            )
            customers.append(
                add(connection, "customer_profiles", tenant_id=seed["tenant"], user_id=user)
            )
    barrier = Barrier(50)

    def reserve(customer: UUID) -> str:
        barrier.wait(timeout=30)
        try:
            with tenant_connection(database, seed["tenant"]) as connection:
                connection.exec_driver_sql("SET LOCAL lock_timeout = '15s'")
                # Stage-8 service contract, exercised here directly at the DB boundary.
                connection.execute(text("SELECT id FROM calendar_controls FOR SHARE"))
                connection.execute(
                    text("SELECT id FROM customer_profiles WHERE id = :id FOR UPDATE"),
                    {"id": customer},
                )
                connection.execute(
                    text("SELECT id FROM employee_profiles WHERE id = :id FOR UPDATE"),
                    {"id": seed["employee"]},
                )
                add(connection, "appointments", **appointment_values(seed, customer_id=customer))
            return "success"
        except DBAPIError as exc:
            return str(getattr(exc.orig, "sqlstate", None))

    with ThreadPoolExecutor(max_workers=50) as pool:
        outcomes = list(pool.map(reserve, customers))
    assert outcomes.count("success") == 1, outcomes
    assert outcomes.count("23P01") == 49, outcomes
    with tenant_connection(database, seed["tenant"]) as connection:
        assert connection.scalar(text("SELECT count(*) FROM appointments")) == 1


def test_overlap_includes_buffer_but_adjacent_half_open_periods_are_allowed(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    initial = appointment_values(seed, status="CONFIRMED", confirmed_at=datetime.now(UTC))
    initial["buffer_after_minutes"] = 15
    initial["occupied_ends_at"] += timedelta(minutes=15)
    with tenant_connection(database, seed["tenant"]) as connection:
        add(connection, "appointments", **initial)
    for delta, should_succeed in ((30, False), (45, True)):
        next_values = appointment_values(seed, status="CONFIRMED", confirmed_at=datetime.now(UTC))
        for key in ("starts_at", "ends_at", "occupied_starts_at", "occupied_ends_at"):
            next_values[key] += timedelta(minutes=delta)
        if should_succeed:
            with tenant_connection(database, seed["tenant"]) as connection:
                add(connection, "appointments", **next_values)
        else:
            with (
                pytest.raises(DBAPIError) as caught,
                tenant_connection(database, seed["tenant"]) as connection,
            ):
                add(connection, "appointments", **next_values)
            assert getattr(caught.value.orig, "sqlstate", None) == "23P01"


def test_same_employee_cannot_overlap_across_lines(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    with tenant_connection(database, seed["tenant"]) as connection:
        other_line = add(connection, "lines", tenant_id=seed["tenant"], slug="color", name="Color")
        add(
            connection,
            "employee_lines",
            tenant_id=seed["tenant"],
            employee_id=seed["employee"],
            line_id=other_line,
        )
        add(
            connection,
            "appointments",
            **appointment_values(seed, status="CONFIRMED", confirmed_at=datetime.now(UTC)),
        )
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "appointments",
            **appointment_values(
                seed, line_id=other_line, status="CONFIRMED", confirmed_at=datetime.now(UTC)
            ),
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23P01"


def test_expired_clock_does_not_silently_remove_occupancy(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    with tenant_connection(database, seed["tenant"]) as connection:
        appointment = add(
            connection,
            "appointments",
            **appointment_values(
                seed,
                created_at=datetime.now(UTC) - timedelta(minutes=20),
                hold_expires_at=datetime.now(UTC) - timedelta(minutes=10),
            ),
        )
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "appointments",
            **appointment_values(seed, status="CONFIRMED", confirmed_at=datetime.now(UTC)),
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23P01"
    with tenant_connection(database, seed["tenant"]) as connection:
        connection.execute(
            text("UPDATE appointments SET status = 'EXPIRED' WHERE id = :id"), {"id": appointment}
        )
        add(connection, "appointments", **appointment_values(seed))


def test_failed_reschedule_rolls_back_to_original_time(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    now = datetime.now(UTC)
    first = appointment_values(seed, status="CONFIRMED", confirmed_at=now)
    second = appointment_values(seed, status="CONFIRMED", confirmed_at=now)
    for key in ("starts_at", "ends_at", "occupied_starts_at", "occupied_ends_at"):
        second[key] += timedelta(hours=2)
    with tenant_connection(database, seed["tenant"]) as connection:
        first_id = add(connection, "appointments", **first)
        add(connection, "appointments", **second)
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        connection.execute(
            text(
                "UPDATE appointments SET starts_at = starts_at + interval '2 hours', ends_at = ends_at + interval '2 hours', occupied_starts_at = occupied_starts_at + interval '2 hours', occupied_ends_at = occupied_ends_at + interval '2 hours' WHERE id = :id"
            ),
            {"id": first_id},
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23P01"
    with tenant_connection(database, seed["tenant"]) as connection:
        assert (
            connection.scalar(
                text("SELECT starts_at FROM appointments WHERE id = :id"), {"id": first_id}
            )
            == first["starts_at"]
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("duration_minutes", 0),
        ("total_amount", -1),
        ("currency", "USD"),
        ("buffer_before_minutes", -1),
    ],
)
def test_invalid_reservation_values_are_rejected(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]], field: str, value: object
) -> None:
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, tenants[0]["tenant"]) as connection,
    ):
        add(connection, "appointments", **appointment_values(tenants[0], **{field: value}))
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"


def test_one_active_hold_per_customer_even_with_different_request_ids(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    first = appointment_values(seed)
    second = appointment_values(seed)
    for key in ("starts_at", "ends_at", "occupied_starts_at", "occupied_ends_at"):
        second[key] += timedelta(hours=2)
    with tenant_connection(database, seed["tenant"]) as connection:
        add(connection, "appointments", id=uuid4(), **first)
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(connection, "appointments", id=uuid4(), **second)
    assert getattr(caught.value.orig, "sqlstate", None) == "23505"


def test_assignment_is_required_before_booking(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(connection, "appointments", **appointment_values(seed, employee_id=uuid4()))
    assert getattr(caught.value.orig, "sqlstate", None) == "23503"


def test_changing_assigned_employee_preserves_original_commercial_snapshot(
    database: Database, paid_seed: dict[str, UUID]
) -> None:
    seed = paid_seed
    with tenant_connection(database, seed["tenant"]) as connection:
        user = add(
            connection,
            "users",
            tenant_id=seed["tenant"],
            email_normalized="second-employee@example.test",
            password_hash="test-only",
            display_name="Second employee",
        )
        employee = add(
            connection,
            "employee_profiles",
            tenant_id=seed["tenant"],
            user_id=user,
            public_name="Second",
        )
        add(
            connection,
            "employee_lines",
            tenant_id=seed["tenant"],
            employee_id=employee,
            line_id=seed["line"],
        )
        add(
            connection,
            "employee_services",
            tenant_id=seed["tenant"],
            employee_id=employee,
            line_id=seed["line"],
            service_id=seed["service"],
        )
        connection.execute(
            text("UPDATE appointments SET employee_id = :employee WHERE id = :id"),
            {"employee": employee, "id": seed["appointment"]},
        )
        assert (
            connection.scalar(
                text("SELECT original_employee_id FROM appointment_items WHERE id = :id"),
                {"id": seed["item"]},
            )
            == seed["employee"]
        )
        assert (
            connection.scalar(
                text("SELECT total_amount FROM invoices WHERE id = :id"), {"id": seed["invoice"]}
            )
            == 1_000_000
        )
