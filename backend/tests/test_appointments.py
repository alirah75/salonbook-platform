from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError

from app.main import create_app
from app.modules.access.models import Role, RoleAssignment
from app.modules.appointments import domain
from app.modules.appointments.expiry import ExpiryService
from app.modules.appointments.models import (
    Appointment,
    AppointmentHistory,
    IdempotencyRecord,
)
from app.modules.identity.models import CustomerProfile, User
from app.modules.operations.models import OutboxEvent
from app.modules.workforce.models import EmployeeProfile
from tests.conftest import add
from tests.test_authentication import auth_lab as auth_lab
from tests.test_catalog_workforce import catalog as catalog
from tests.test_scheduling import Schedule
from tests.test_scheduling import schedule as schedule
from tests.test_tenant_management import assign, mutate, new_user, sign_in
from tests.test_tenant_management import manager as manager

pytestmark = pytest.mark.postgres


def command(
    s: Schedule,
    path: str = "",
    body: dict[str, Any] | None = None,
    *,
    key: str | None = None,
    client: TestClient | None = None,
    csrf: str | None = None,
) -> Response:
    m = s.catalog.manager
    browser = client or m.lab.client
    return browser.post(
        f"/api/v1/appointments{path}",
        json=body or {},
        headers={
            "Origin": str(browser.base_url).rstrip("/"),
            "X-CSRF-Token": csrf or m.csrf,
            "Idempotency-Key": key or uuid4().hex,
        },
    )


def create(s: Schedule, minute: int = 540, **options: Any) -> Response:
    return command(
        s,
        body={
            "line_id": s.catalog.line,
            "service_ids": [s.catalog.service],
            "employee_id": s.catalog.employee,
            "starts_at": s.at(minute).isoformat(),
        },
        **options,
    )


def free(s: Schedule) -> None:
    response = mutate(
        s.catalog.manager,
        "PUT",
        s.catalog.offer_path,
        {"price_amount": 0, "duration_minutes": 30, "is_free": True},
    )
    assert response.status_code == 200, response.text


def expire_in_db(s: Schedule, identifier: str) -> None:
    now = datetime.now(UTC)
    with s.catalog.manager.lab.database.lab.admin.begin() as connection:
        connection.execute(
            update(Appointment)
            .where(Appointment.id == UUID(identifier))
            .values(
                created_at=now - timedelta(minutes=30), hold_expires_at=now - timedelta(minutes=1)
            )
        )


def settlement(s: Schedule, identifier: str) -> None:
    """Persist matched fixture evidence; no HTTP endpoint can fabricate this evidence."""
    lab = s.catalog.manager.lab
    with lab.database.lab.admin.begin() as connection:
        common = {"tenant_id": lab.tenant}
        amount = connection.scalar(
            select(Appointment.total_amount).where(Appointment.id == UUID(identifier))
        )
        money = {"amount": amount, "currency": "IRR", "is_test": True}
        intent = add(
            connection,
            "payment_intents",
            **common,
            appointment_id=UUID(identifier),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            status="SUCCEEDED",
            **money,
        )
        account = add(
            connection,
            "payment_accounts",
            **common,
            provider="mock",
            merchant_reference=uuid4().hex,
            is_test=True,
        )
        attempt = add(
            connection,
            "payment_attempts",
            **common,
            intent_id=intent,
            account_id=account,
            request_key=uuid4().hex,
            status="SUCCEEDED",
            **money,
        )
        transaction = add(
            connection,
            "payment_transactions",
            **common,
            attempt_id=attempt,
            intent_id=intent,
            account_id=account,
            gateway_transaction_id=uuid4().hex,
            received_at=datetime.now(UTC),
            verified_at=datetime.now(UTC),
            evidence={"verified": True},
            **money,
        )
        add(
            connection,
            "payment_allocations",
            **common,
            intent_id=intent,
            transaction_id=transaction,
            **money,
        )


def test_paid_hold_snapshot_idempotency_and_server_price(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    key = uuid4().hex
    response = create(s, key=key)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["status"] == "AWAITING_PAYMENT" and row["total_amount"] == 1_000_000
    assert row["items"][0]["service_id"] == s.catalog.service
    assert row["hold_expires_at"] and row["version"] == 1 and row["is_test"]
    assert create(s, key=key).json() == row
    assert create(s, key=key).headers["Idempotency-Replayed"] == "true"
    assert create(s, 600, key=key).json()["error"]["code"] == "idempotency_conflict"
    assert create(s, 600).json()["error"]["code"] == "active_hold"
    invalid = command(
        s,
        body={
            "line_id": s.catalog.line,
            "service_ids": [s.catalog.service],
            "starts_at": s.at(600).isoformat(),
            "total_amount": 1,
        },
    )
    assert invalid.status_code == 422
    with m.lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.tenant_id == m.lab.tenant)
            )
            == 1
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(AppointmentHistory)
                .where(AppointmentHistory.appointment_id == UUID(row["id"]))
            )
            == 1
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.aggregate_id == UUID(row["id"]))
            )
            == 1
        )
    assert m.lab.client.get("/api/v1/appointments").json()["items"][0]["id"] == row["id"]


def test_free_confirmation_reschedule_and_cancellation_preserve_snapshots(
    schedule: Schedule,
) -> None:
    s, m = schedule, schedule.catalog.manager
    free(s)
    response = create(s)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["status"] == "CONFIRMED" and row["hold_expires_at"] is None
    assert (
        mutate(
            m, "PUT", s.catalog.offer_path, {"price_amount": 2_000_000, "duration_minutes": 90}
        ).status_code
        == 200
    )
    changed = command(
        s,
        f"/{row['id']}/reschedule",
        {
            "expected_version": 1,
            "starts_at": s.at(600).isoformat(),
            "employee_id": s.catalog.employee,
            "reason": "Later time",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["duration_minutes"] == 30 and changed.json()["total_amount"] == 0
    assert changed.json()["items"] == row["items"] and changed.json()["version"] == 2
    assert (
        command(s, f"/{row['id']}/cancel", {"expected_version": 1, "reason": "Cancel"}).json()[
            "error"
        ]["code"]
        == "stale_appointment"
    )
    cancelled = command(
        s, f"/{row['id']}/cancel", {"expected_version": 2, "reason": "Plans changed"}
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    actions = m.lab.client.get(f"/api/v1/appointments/{row['id']}/history").json()["items"]
    assert {r["action"] for r in actions} == {"confirmed_free", "rescheduled", "cancelled"}


def test_paid_confirmation_requires_matched_evidence_and_active_hold(schedule: Schedule) -> None:
    s = schedule
    identifier = create(s).json()["id"]
    response = command(s, f"/{identifier}/confirm", {"expected_version": 1})
    assert response.status_code == 409 and response.json()["error"]["code"] == "payment_required"
    settlement(s, identifier)
    key = uuid4().hex
    response = command(s, f"/{identifier}/confirm", {"expected_version": 1}, key=key)
    assert response.status_code == 200 and response.json()["status"] == "CONFIRMED", response.text
    assert (
        command(s, f"/{identifier}/confirm", {"expected_version": 1}, key=key).json()
        == response.json()
    )
    assert command(s, f"/{identifier}/confirm", {"expected_version": 2}).status_code == 409


def test_expired_confirm_returns_409_and_commits_expiry_once(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    identifier = create(s).json()["id"]
    settlement(s, identifier)
    expire_in_db(s, identifier)
    key = uuid4().hex
    response = command(s, f"/{identifier}/confirm", {"expected_version": 1}, key=key)
    assert response.status_code == 409 and response.json()["error"]["code"] == "hold_expired", (
        response.text
    )
    assert (
        command(s, f"/{identifier}/confirm", {"expected_version": 1}, key=key).json()
        == response.json()
    )
    row = m.lab.client.get(f"/api/v1/appointments/{identifier}").json()
    assert row["status"] == "EXPIRED" and row["version"] == 2
    with m.lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(AppointmentHistory)
                .where(
                    AppointmentHistory.appointment_id == UUID(identifier),
                    AppointmentHistory.action == "expired",
                )
            )
            == 1
        )


def test_lazy_expiry_frees_constraint_and_customer_hold(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    identifier = create(s).json()["id"]
    expire_in_db(s, identifier)
    response = create(s)
    assert response.status_code == 201, response.text
    assert response.json()["id"] != identifier
    assert m.lab.client.get(f"/api/v1/appointments/{identifier}").json()["status"] == "EXPIRED"


def test_two_expiry_workers_emit_one_transition(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    identifier = create(s).json()["id"]
    expire_in_db(s, identifier)
    worker = ExpiryService(lab.runtime.database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker.one, lab.tenant, UUID(identifier)) for _ in range(2)]
        assert sorted(f.result(timeout=10) for f in futures) == [False, True]
    assert worker.batch(lab.tenant) == 0
    assert worker.one(lab.other_tenant, UUID(identifier)) is False


def test_reschedule_conflict_rolls_back_and_failed_idempotency_is_stable(
    schedule: Schedule,
) -> None:
    s, m = schedule, schedule.catalog.manager
    free(s)
    first, other = create(s).json(), create(s, 600).json()
    key = uuid4().hex
    body = {
        "expected_version": 1,
        "starts_at": s.at(600).isoformat(),
        "employee_id": s.catalog.employee,
        "reason": "Move",
    }
    failed = command(s, f"/{first['id']}/reschedule", body, key=key)
    assert failed.status_code == 409, failed.text
    assert m.lab.client.get(f"/api/v1/appointments/{first['id']}").json() == first
    assert (
        command(
            s, f"/{other['id']}/cancel", {"expected_version": 1, "reason": "Free destination"}
        ).status_code
        == 200
    )
    assert command(s, f"/{first['id']}/reschedule", body, key=key).json() == failed.json()
    assert command(s, f"/{first['id']}/reschedule", body).status_code == 200


def test_customer_cannot_access_other_bookings_or_override_deadline(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    free(s)
    identifier = create(s).json()["id"]
    new_user(m, "09121234568")
    with TestClient(m.lab.app, base_url=m.lab.origin) as customer:
        csrf = sign_in(m, customer, "09121234568")
        assert customer.get(f"/api/v1/appointments/{identifier}").status_code == 404
        assert customer.get(f"/api/v1/appointments/{identifier}/history").status_code == 404
        assert (
            command(
                s,
                f"/{identifier}/cancel",
                {"expected_version": 1, "reason": "No"},
                client=customer,
                csrf=csrf,
            ).status_code
            == 403
        )
        # A long snapshotted cutoff places tomorrow's booking inside the cutoff.
        assert (
            mutate(m, "PUT", "/scheduling/settings", {"cancel_before_minutes": 20000}).status_code
            == 200
        )
        own = create(s, 600, client=customer, csrf=csrf).json()["id"]
        assert (
            command(
                s,
                f"/{own}/cancel",
                {"expected_version": 1, "reason": "No"},
                client=customer,
                csrf=csrf,
            ).json()["error"]["code"]
            == "cancellation_cutoff"
        )
        assert (
            command(
                s,
                f"/{own}/cancel",
                {"expected_version": 1, "reason": "No", "override_policy": True},
                client=customer,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            command(
                s,
                f"/{own}/cancel",
                {"expected_version": 1, "reason": "Manager exception", "override_policy": True},
            ).status_code
            == 200
        )


def test_employee_view_hides_financials_and_completion_requires_time(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    identifier = create(s).json()["id"]
    settlement(s, identifier)
    assert command(s, f"/{identifier}/confirm", {"expected_version": 1}).status_code == 200
    with TestClient(m.lab.app, base_url=m.lab.origin) as employee:
        csrf = sign_in(m, employee)
        row = employee.get(f"/api/v1/appointments/{identifier}").json()
        assert row["total_amount"] is None and row["items"][0]["amount"] is None
        assert "phone" not in str(row)
        for action in ("complete", "no-show"):
            assert (
                command(
                    s,
                    f"/{identifier}/{action}",
                    {"expected_version": 2, "reason": "Done"},
                    client=employee,
                    csrf=csrf,
                ).json()["error"]["code"]
                == "too_early"
            )
        with m.lab.database.lab.admin.begin() as connection:
            start = datetime.now(UTC) - timedelta(hours=1)
            connection.execute(
                update(Appointment)
                .where(Appointment.id == UUID(identifier))
                .values(
                    starts_at=start,
                    occupied_starts_at=start,
                    ends_at=start + timedelta(minutes=30),
                    occupied_ends_at=start + timedelta(minutes=30),
                )
            )
        completed = command(
            s,
            f"/{identifier}/complete",
            {"expected_version": 2, "reason": "Done"},
            client=employee,
            csrf=csrf,
        )
        assert completed.status_code == 200 and completed.json()["status"] == "COMPLETED", (
            completed.text
        )
        assert (
            command(
                s,
                f"/{identifier}/no-show",
                {"expected_version": 3, "reason": "No"},
                client=employee,
                csrf=csrf,
            ).status_code
            == 409
        )


def test_booking_rejects_closed_schedule_wrong_scope_bad_time_and_missing_csrf(
    schedule: Schedule,
) -> None:
    s, m = schedule, schedule.catalog.manager
    assert create(s, 545).status_code == 409
    assert create(s, 1200).status_code == 409
    assert s.override(s.salon, {"mode": "CLOSED"}).status_code == 200
    assert create(s).status_code == 409
    assert m.lab.client.post("/api/v1/appointments", json={}).status_code == 403
    assert (
        command(
            s,
            body={
                "line_id": str(m.lab.other_line),
                "service_ids": [s.catalog.service],
                "starts_at": s.at(540).isoformat(),
            },
        ).status_code
        == 404
    )


def test_same_key_concurrency_one_row_and_one_outbox(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    key = uuid4().hex
    barrier = Barrier(10)

    def reserve() -> Response:
        barrier.wait(timeout=10)
        return create(s, key=key)

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(lambda _: reserve(), range(10)))
    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    with m.lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.tenant_id == m.lab.tenant)
            )
            == 1
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.tenant_id == m.lab.tenant)
            )
            == 1
        )


def test_two_reschedules_with_same_version_one_wins(schedule: Schedule) -> None:
    s = schedule
    free(s)
    row = create(s).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                command,
                s,
                f"/{row['id']}/reschedule",
                {"expected_version": 1, "starts_at": s.at(minute).isoformat(), "reason": "Move"},
            )
            for minute in (600, 660)
        ]
        responses = [f.result(timeout=10) for f in futures]
    assert sorted(r.status_code for r in responses) == [200, 409]


def test_fifty_authenticated_customers_same_capacity_exactly_one_hold(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    credentials: list[tuple[str, str]] = []
    with lab.runtime.database.transaction(lab.tenant) as session:
        role = session.scalar(select(Role).where(Role.code == "customer"))
        assert role is not None
        for index in range(50):
            user = User(
                tenant_id=lab.tenant,
                phone_normalized=f"+98912{index:07d}",
                password_hash="fixture-only-session-provisioning",
                display_name=f"Customer {index}",
            )
            session.add(user)
            session.flush()
            session.add_all(
                [
                    CustomerProfile(tenant_id=lab.tenant, user_id=user.id),
                    RoleAssignment(
                        tenant_id=lab.tenant, user_id=user.id, role_id=role.id, scope="TENANT"
                    ),
                ]
            )
            session.flush()
            token, response = lab.auth.sessions.create(session, lab.context, user)
            credentials.append((token, response.csrf_token))
    # The test provisions real session tokens and then uses HTTP with 50 distinct actors.
    # Pool/wait capacity is explicit so admission timeouts do not mask booking correctness.
    settings = lab.runtime.settings.model_copy(
        update={
            "db_pool_size": 50,
            "db_max_overflow": 0,
            "db_lock_timeout_ms": 10000,
            "db_statement_timeout_ms": 15000,
            "db_idle_transaction_timeout_ms": 30000,
        }
    )
    barrier = Barrier(50)
    with TestClient(create_app(settings), base_url=lab.origin) as browser:

        def reserve(index: int) -> Response:
            token, csrf = credentials[index]
            barrier.wait(timeout=20)
            return browser.post(
                "/api/v1/appointments",
                json={
                    "line_id": s.catalog.line,
                    "service_ids": [s.catalog.service],
                    "starts_at": s.at(540).isoformat(),
                },
                headers={
                    "Origin": lab.origin,
                    "Cookie": f"__Host-salonbook-session={token}",
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": uuid4().hex,
                },
            )

        with ThreadPoolExecutor(max_workers=50) as pool:
            responses = list(pool.map(reserve, range(50)))
    assert [r.status_code for r in responses].count(201) == 1
    assert [r.status_code for r in responses].count(409) == 49
    with lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.tenant_id == lab.tenant)
            )
            == 1
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.tenant_id == lab.tenant)
            )
            == 1
        )


def test_booking_and_schedule_change_share_lock_and_recheck_after_wait(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    booking_waits, schedule_waits = Event(), Event()

    def observed(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if "employee_profiles" in statement and "FOR UPDATE" in statement:
            booking_waits.set()
        if "calendar_controls" in statement and "FOR UPDATE" in statement:
            schedule_waits.set()

    event.listen(lab.runtime.database.engine, "before_cursor_execute", observed)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            with lab.database.lab.admin.begin() as connection:
                connection.execute(
                    select(EmployeeProfile.id)
                    .where(EmployeeProfile.id == UUID(s.catalog.employee))
                    .with_for_update()
                )
                booking = pool.submit(create, s)
                assert booking_waits.wait(2)
                closure = pool.submit(s.override, s.salon, {"mode": "CLOSED"})
                assert schedule_waits.wait(2)
                assert not booking.done() and not closure.done()
            assert booking.result(timeout=10).status_code == 201
            assert closure.result(timeout=10).status_code == 409
    finally:
        event.remove(lab.runtime.database.engine, "before_cursor_execute", observed)


def test_same_employee_across_lines_cannot_be_double_booked(schedule: Schedule) -> None:
    s, c, m = schedule, schedule.catalog, schedule.catalog.manager
    free(s)
    other = mutate(m, "POST", "/lines", {"name": "Second", "slug": "second"}).json()["id"]
    assert (
        mutate(
            m,
            "PUT",
            f"/lines/{other}/services/{c.service}",
            {"price_amount": 0, "duration_minutes": 30, "is_free": True},
        ).status_code
        == 200
    )
    assert mutate(m, "PUT", f"/lines/{other}/employees/{c.employee}").status_code == 200
    assert (
        mutate(m, "PUT", f"/lines/{other}/employees/{c.employee}/services/{c.service}").status_code
        == 200
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(create, s)
        second = pool.submit(
            command,
            s,
            body={
                "line_id": other,
                "service_ids": [c.service],
                "employee_id": c.employee,
                "starts_at": s.at(540).isoformat(),
            },
        )
        assert sorted(
            [first.result(timeout=10).status_code, second.result(timeout=10).status_code]
        ) == [201, 409]


def test_line_manager_scope_and_employee_assignment_visibility(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    free(s)
    row = create(s).json()
    user = new_user(m, "09121234568")
    assert assign(m, user, m.roles["line_manager"], line=m.lab.line).status_code == 201
    with TestClient(m.lab.app, base_url=m.lab.origin) as outsider:
        csrf = sign_in(m, outsider, "09121234568")
        assert outsider.get(f"/api/v1/appointments/{row['id']}").status_code == 404
        assert outsider.get("/api/v1/appointments").json()["items"] == []
        assert (
            command(
                s,
                f"/{row['id']}/cancel",
                {"expected_version": 1, "reason": "Other line"},
                client=outsider,
                csrf=csrf,
            ).status_code
            == 403
        )
    with TestClient(m.lab.app, base_url=m.lab.other_origin) as other:
        assert other.get(f"/api/v1/appointments/{row['id']}").status_code == 401


def test_no_show_after_grace_preserves_occupancy_and_disallows_terminal_edits(
    schedule: Schedule,
) -> None:
    s, m = schedule, schedule.catalog.manager
    free(s)
    row = create(s).json()
    with m.lab.database.lab.admin.begin() as connection:
        start = datetime.now(UTC) - timedelta(minutes=16)
        connection.execute(
            update(Appointment)
            .where(Appointment.id == UUID(row["id"]))
            .values(
                starts_at=start,
                occupied_starts_at=start,
                ends_at=start + timedelta(minutes=30),
                occupied_ends_at=start + timedelta(minutes=30),
            )
        )
    response = command(
        s, f"/{row['id']}/no-show", {"expected_version": 1, "reason": "Absent after grace"}
    )
    assert response.status_code == 200 and response.json()["status"] == "NO_SHOW", response.text
    assert (
        command(
            s,
            f"/{row['id']}/cancel",
            {"expected_version": 2, "reason": "Late", "override_policy": True},
        ).status_code
        == 409
    )
    assert (
        command(
            s,
            f"/{row['id']}/reschedule",
            {
                "expected_version": 2,
                "reason": "Late",
                "starts_at": s.at(600).isoformat(),
                "override_policy": True,
            },
        ).status_code
        == 409
    )


def test_retriable_database_error_rolls_back_before_retry(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, m = schedule, schedule.catalog.manager
    calls = 0
    original = domain.event

    class Deadlock(Exception):
        sqlstate = "40P01"

    def fail_once(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        original(*args, **kwargs)
        if calls == 1:
            raise OperationalError("injected after appointment insert", {}, Deadlock())

    monkeypatch.setattr(domain, "event", fail_once)
    response = create(s)
    assert response.status_code == 201 and calls == 2, response.text
    with m.lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.tenant_id == m.lab.tenant)
            )
            == 1
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.tenant_id == m.lab.tenant)
            )
            == 1
        )


def test_multi_service_booking_snapshots_order_and_internal_buffer(schedule: Schedule) -> None:
    s, c, m = schedule, schedule.catalog, schedule.catalog.manager
    second = mutate(m, "POST", "/services", {"name": "Color", "code": "color"}).json()["id"]
    assert (
        mutate(
            m,
            "PUT",
            c.offer_path,
            {"price_amount": 1_000_000, "duration_minutes": 30, "buffer_after_minutes": 10},
        ).status_code
        == 200
    )
    assert (
        mutate(
            m,
            "PUT",
            f"/lines/{c.line}/services/{second}",
            {
                "price_amount": 2_000_000,
                "duration_minutes": 45,
                "buffer_before_minutes": 15,
                "buffer_after_minutes": 20,
            },
        ).status_code
        == 200
    )
    assert (
        mutate(m, "PUT", f"/lines/{c.line}/employees/{c.employee}/services/{second}").status_code
        == 200
    )
    response = command(
        s,
        body={
            "line_id": c.line,
            "service_ids": [c.service, second],
            "starts_at": s.at(540).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    row = response.json()
    assert (
        row["duration_minutes"] == 90
        and row["total_amount"] == 3_000_000
        and row["buffer_after_minutes"] == 20
    )
    assert [item["service_id"] for item in row["items"]] == [c.service, second]
