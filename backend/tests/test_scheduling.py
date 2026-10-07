from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from threading import Event
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Connection, event, select, update

from app.db.enums import AppointmentStatus
from app.modules.appointments.models import Appointment
from app.modules.identity.context import require_active_context
from app.modules.scheduling.coordination import lock_calendar
from app.modules.scheduling.engine import availability
from app.modules.scheduling.intervals import local_instant
from app.modules.scheduling.schemas import AvailabilityQuery
from app.modules.tenancy.models import Salon
from tests.conftest import add, appointment_values
from tests.test_authentication import auth_lab as auth_lab
from tests.test_catalog_workforce import Catalog
from tests.test_catalog_workforce import catalog as catalog
from tests.test_tenant_management import assign, mutate, new_user, sign_in
from tests.test_tenant_management import manager as manager

pytestmark = pytest.mark.postgres
ZONE = ZoneInfo("Asia/Tehran")


@dataclass
class Schedule:
    catalog: Catalog
    salon: str
    employee: str
    day: date

    def at(self, minute: int) -> datetime:
        return local_instant(self.day, minute, ZONE)

    def query(self, **changes: Any) -> Response:
        params = {
            "line_id": self.catalog.line,
            "service_ids": [self.catalog.service],
            "date_from": self.day.isoformat(),
            "date_until": (self.day + timedelta(days=1)).isoformat(),
            "limit": 500,
            **changes,
        }
        return self.catalog.manager.lab.client.get("/api/v1/scheduling/availability", params=params)

    def minutes(self) -> list[int]:
        response = self.query()
        assert response.status_code == 200, response.text
        return [
            int((datetime.fromisoformat(s["starts_at"]) - self.at(0)).total_seconds() / 60)
            for s in response.json()["items"]
        ]

    def weekly(
        self, calendar: str, start: int = 540, end: int = 1020, *, breaks: bool = False
    ) -> Response:
        periods = [
            {
                "weekday": d,
                "kind": "OPEN",
                "start_minute": start,
                "end_minute": end,
                "valid_from": self.day.isoformat(),
            }
            for d in range(7)
        ]
        if breaks:
            periods.extend(
                {
                    "weekday": d,
                    "kind": "BREAK",
                    "start_minute": 720,
                    "end_minute": 780,
                    "valid_from": self.day.isoformat(),
                }
                for d in range(7)
            )
        return mutate(
            self.catalog.manager,
            "PUT",
            f"/scheduling/calendars/{calendar}/weekly",
            {"periods": periods},
        )

    def override(self, calendar: str, body: dict[str, Any]) -> Response:
        return mutate(
            self.catalog.manager,
            "PUT",
            f"/scheduling/calendars/{calendar}/overrides/{self.day}",
            body,
        )

    def block(
        self, calendar: str, start: int = 780, end: int = 840, kind: str = "BLOCKED"
    ) -> Response:
        return mutate(
            self.catalog.manager,
            "POST",
            f"/scheduling/calendars/{calendar}/blocks",
            {
                "kind": kind,
                "starts_at": self.at(start).isoformat(),
                "ends_at": self.at(end).isoformat(),
                "reason": "Unavailable",
            },
        )


@pytest.fixture
def schedule(catalog: Catalog) -> Schedule:
    m = catalog.manager
    salon = m.lab.client.get("/api/v1/scheduling/calendars").json()["items"][0]["id"]
    employee = mutate(
        m, "POST", "/scheduling/calendars", {"scope": "EMPLOYEE", "employee_id": catalog.employee}
    )
    assert employee.status_code == 201, employee.text
    result = Schedule(
        catalog, salon, employee.json()["id"], datetime.now(ZONE).date() + timedelta(days=7)
    )
    assert result.weekly(result.salon).status_code == 200
    assert result.weekly(result.employee).status_code == 200
    assert (
        mutate(
            m, "PUT", catalog.offer_path, {"price_amount": 1_000_000, "duration_minutes": 30}
        ).status_code
        == 200
    )
    return result


def insert_booking(
    s: Schedule,
    start: int = 600,
    duration: int = 90,
    *,
    using: Connection | None = None,
    **changes: Any,
) -> UUID:
    c, lab = s.catalog, s.catalog.manager.lab
    seed = {
        "tenant": lab.tenant,
        "line": UUID(c.line),
        "employee": UUID(c.employee),
        "customer": UUID(c.user["customer_id"]),
    }
    values = appointment_values(
        seed,
        starts_at=s.at(start),
        ends_at=s.at(start + duration),
        occupied_starts_at=s.at(start),
        occupied_ends_at=s.at(start + duration),
        duration_minutes=duration,
        status=AppointmentStatus.CONFIRMED,
        confirmed_at=datetime.now(UTC),
    )
    values.update(changes)
    if using is not None:
        return add(using, "appointments", **values)
    with lab.database.lab.admin.begin() as connection:
        return add(connection, "appointments", **values)


def test_availability_is_public_bounded_and_contains_no_private_identity(
    schedule: Schedule,
) -> None:
    s, m = schedule, schedule.catalog.manager
    assert s.minutes() == list(range(540, 991, 15))
    result = s.query(limit=2).json()
    assert result["has_more"] and len(result["items"]) == 2
    assert s.query(limit=2, offset=2).json()["items"][0]["starts_at"] == s.at(
        570
    ).isoformat().replace("+00:00", "Z")
    assert result["timezone"] == "Asia/Tehran" and result["total_amount"] == 1_000_000
    assert set(result["items"][0]) == {
        "employee_id",
        "employee_name",
        "starts_at",
        "ends_at",
        "occupied_starts_at",
        "occupied_ends_at",
    }
    assert s.query(date_until=(s.day + timedelta(days=8)).isoformat()).status_code == 422
    assert (
        s.query(
            date_from=(s.day - timedelta(days=8)).isoformat(),
            date_until=(s.day - timedelta(days=7)).isoformat(),
        ).status_code
        == 422
    )
    assert (
        s.query(
            date_from=(s.day + timedelta(days=100)).isoformat(),
            date_until=(s.day + timedelta(days=101)).isoformat(),
        ).status_code
        == 422
    )
    with TestClient(m.lab.app, base_url=m.lab.origin) as visitor:
        params = {
            "line_id": s.catalog.line,
            "service_ids": s.catalog.service,
            "date_from": str(s.day),
            "date_until": str(s.day + timedelta(days=1)),
        }
        assert visitor.get("/api/v1/scheduling/availability", params=params).status_code == 200
        assert visitor.get(f"/api/v1/scheduling/calendars/{s.employee}/weekly").status_code == 401


def test_duration_buffers_breaks_and_architecture_example(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    assert s.weekly(s.employee, breaks=True).status_code == 200
    insert_booking(s)
    assert (
        mutate(
            m,
            "PUT",
            s.catalog.offer_path,
            {"price_amount": 1_000_000, "duration_minutes": 90, "buffer_after_minutes": 15},
        ).status_code
        == 200
    )
    assert s.minutes() == list(range(780, 916, 15))


def test_missing_hours_fail_closed_and_line_hours_restrict(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    assert (
        mutate(m, "PUT", f"/scheduling/calendars/{s.employee}/weekly", {"periods": []}).status_code
        == 200
    )
    assert s.minutes() == []
    assert s.weekly(s.employee).status_code == 200
    line = mutate(m, "POST", "/scheduling/calendars", {"scope": "LINE", "line_id": s.catalog.line})
    assert line.status_code == 201, line.text
    assert s.minutes() == []
    assert s.weekly(line.json()["id"], 600, 720).status_code == 200
    assert s.minutes() == list(range(600, 691, 15))
    narrower = mutate(
        m,
        "POST",
        "/scheduling/calendars",
        {"scope": "EMPLOYEE_LINE", "line_id": s.catalog.line, "employee_id": s.catalog.employee},
    ).json()["id"]
    assert s.weekly(narrower, 660, 780).status_code == 200
    assert s.minutes() == [660, 675, 690]


def test_day_override_replaces_breaks_and_cannot_bypass_salon_closure(schedule: Schedule) -> None:
    s = schedule
    assert s.weekly(s.employee, breaks=True).status_code == 200
    assert 720 not in s.minutes()
    assert (
        s.override(
            s.employee, {"mode": "REPLACE", "periods": [{"start_minute": 660, "end_minute": 840}]}
        ).status_code
        == 200
    )
    assert s.minutes() == list(range(660, 811, 15))
    assert s.override(s.salon, {"mode": "CLOSED", "reason": "Holiday"}).status_code == 200
    assert s.minutes() == []
    assert (
        mutate(
            s.catalog.manager, "DELETE", f"/scheduling/calendars/{s.salon}/overrides/{s.day}"
        ).status_code
        == 204
    )
    assert 720 in s.minutes()
    listed = s.catalog.manager.lab.client.get(
        f"/api/v1/scheduling/calendars/{s.employee}/overrides",
        params={"date_from": str(s.day), "date_until": str(s.day + timedelta(days=1))},
    )
    assert listed.status_code == 200 and len(listed.json()) == 1


@pytest.mark.parametrize("kind", ["LEAVE", "HOLIDAY", "BLOCKED"])
def test_approved_blocks_and_cancellation_restore_time(schedule: Schedule, kind: str) -> None:
    s, m = schedule, schedule.catalog.manager
    response = s.block(s.employee, kind=kind)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "APPROVED"
    assert 750 in s.minutes() and 765 not in s.minutes() and 840 in s.minutes()
    identifier = response.json()["id"]
    assert (
        mutate(m, "PATCH", f"/scheduling/blocks/{identifier}", {"status": "CANCELLED"}).status_code
        == 200
    )
    assert 780 in s.minutes()
    assert (
        mutate(m, "PATCH", f"/scheduling/blocks/{identifier}", {"status": "APPROVED"}).status_code
        == 409
    )


@pytest.mark.parametrize("change", ["weekly", "override", "block"])
def test_conflicts_return_ids_and_roll_back_schedule_and_version(
    schedule: Schedule, change: str
) -> None:
    s = schedule
    identifier = insert_booking(s)
    version = s.query().json()["calendar_version"]
    if change == "weekly":
        response = s.weekly(s.employee, 720, 1020)
    elif change == "override":
        response = s.override(s.employee, {"mode": "CLOSED"})
    else:
        response = s.block(s.employee, 600, 660)
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "schedule_conflict"
    assert error["details"][0]["field"] == f"appointments.{identifier}"
    assert s.query().json()["calendar_version"] == version
    assert 540 in s.minutes() and 780 in s.minutes()
    assert s.weekly(s.employee, 480, 1080).status_code == 200


def test_valid_holds_block_time_but_expired_and_cancelled_do_not(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    active = insert_booking(
        s, 600, 30, status=AppointmentStatus.AWAITING_PAYMENT, confirmed_at=None
    )
    now = datetime.now(UTC)
    other_customer = new_user(m, "09121234568")
    expired = insert_booking(
        s,
        660,
        30,
        status=AppointmentStatus.AWAITING_PAYMENT,
        confirmed_at=None,
        created_at=now - timedelta(minutes=30),
        hold_expires_at=now - timedelta(minutes=1),
        customer_id=UUID(other_customer["customer_id"]),
    )
    insert_booking(
        s, 720, 30, status=AppointmentStatus.CANCELLED, confirmed_at=None, cancelled_at=now
    )
    assert 600 not in s.minutes() and 660 in s.minutes() and 720 in s.minutes()
    assert s.block(s.employee, 660, 690).status_code == 201
    assert s.block(s.employee, 600, 630).status_code == 409
    with m.lab.database.lab.admin.connect() as connection:
        # Availability is a read: stage 8 owns hold expiry transitions.
        assert (
            connection.scalar(select(Appointment.status).where(Appointment.id == expired))
            == AppointmentStatus.AWAITING_PAYMENT
        )
        assert (
            connection.scalar(select(Appointment.status).where(Appointment.id == active))
            == AppointmentStatus.AWAITING_PAYMENT
        )


def test_bookings_in_another_line_use_same_employee_capacity(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    other = mutate(m, "POST", "/lines", {"name": "Other", "slug": "other-line"}).json()["id"]
    assert mutate(m, "PUT", f"/lines/{other}/employees/{s.catalog.employee}").status_code == 200
    insert_booking(s, line_id=UUID(other))
    assert 600 not in s.minutes() and 690 in s.minutes()


def test_multi_service_requires_all_skills_and_shared_buffers(schedule: Schedule) -> None:
    s, c, m = schedule, schedule.catalog, schedule.catalog.manager
    product = mutate(m, "POST", "/services", {"name": "Color", "code": "color"}).json()["id"]
    assert (
        mutate(
            m,
            "PUT",
            f"/lines/{c.line}/services/{product}",
            {
                "price_amount": 2_000_000,
                "duration_minutes": 45,
                "buffer_before_minutes": 15,
                "buffer_after_minutes": 20,
            },
        ).status_code
        == 200
    )
    assert s.query(service_ids=[c.service, product]).json()["items"] == []
    assert (
        mutate(m, "PUT", f"/lines/{c.line}/employees/{c.employee}/services/{product}").status_code
        == 200
    )
    assert (
        mutate(
            m,
            "PUT",
            c.offer_path,
            {
                "price_amount": 1_000_000,
                "duration_minutes": 30,
                "buffer_before_minutes": 5,
                "buffer_after_minutes": 10,
            },
        ).status_code
        == 200
    )
    result = s.query(service_ids=[c.service, product]).json()
    assert (
        result["duration_minutes"],
        result["buffer_before_minutes"],
        result["buffer_after_minutes"],
        result["total_amount"],
    ) == (90, 5, 20, 3_000_000)
    assert result["items"][0]["starts_at"] == s.at(555).isoformat().replace("+00:00", "Z")
    reverse = s.query(service_ids=[product, c.service]).json()
    assert (
        reverse["duration_minutes"],
        reverse["buffer_before_minutes"],
        reverse["buffer_after_minutes"],
    ) == (95, 15, 10)
    assert s.query(service_ids=[c.service, c.service]).status_code == 422


def test_employee_leave_needs_approval_and_is_private(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    with TestClient(m.lab.app, base_url=m.lab.origin) as employee:
        csrf = sign_in(m, employee)
        calendars = employee.get("/api/v1/scheduling/calendars").json()["items"]
        assert {r["id"] for r in calendars} == {s.employee}
        assert employee.get(f"/api/v1/scheduling/calendars/{s.salon}/weekly").status_code == 403
        body = {
            "kind": "LEAVE",
            "starts_at": s.at(780).isoformat(),
            "ends_at": s.at(840).isoformat(),
            "reason": "Personal",
        }
        assert (
            mutate(
                m,
                "POST",
                f"/scheduling/calendars/{s.employee}/blocks",
                body,
                client=employee,
                csrf=csrf,
            ).status_code
            == 403
        )
        response = mutate(
            m,
            "POST",
            f"/scheduling/calendars/{s.employee}/leave-requests",
            body,
            client=employee,
            csrf=csrf,
        )
        assert response.status_code == 201 and response.json()["status"] == "REQUESTED", (
            response.text
        )
        identifier = response.json()["id"]
        assert 780 in s.minutes()
        assert (
            mutate(
                m,
                "PATCH",
                f"/scheduling/blocks/{identifier}",
                {"status": "APPROVED"},
                client=employee,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                m, "PATCH", f"/scheduling/blocks/{identifier}", {"status": "APPROVED"}
            ).status_code
            == 200
        )
        assert 780 not in s.minutes()
        assert (
            mutate(
                m,
                "PATCH",
                f"/scheduling/blocks/{identifier}",
                {"status": "CANCELLED"},
                client=employee,
                csrf=csrf,
            ).status_code
            == 403
        )


def test_line_manager_cannot_edit_global_employee_or_other_line(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    assert (
        assign(m, s.catalog.user, m.roles["line_manager"], line=UUID(s.catalog.line)).status_code
        == 201
    )
    with TestClient(m.lab.app, base_url=m.lab.origin) as employee:
        csrf = sign_in(m, employee)
        assert (
            mutate(
                m,
                "PUT",
                f"/scheduling/calendars/{s.employee}/weekly",
                {"periods": []},
                client=employee,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                m,
                "PUT",
                f"/scheduling/calendars/{s.salon}/weekly",
                {"periods": []},
                client=employee,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                m,
                "POST",
                "/scheduling/calendars",
                {"scope": "LINE", "line_id": str(m.lab.other_line)},
                client=employee,
                csrf=csrf,
            ).status_code
            == 403
        )
        response = mutate(
            m,
            "POST",
            "/scheduling/calendars",
            {
                "scope": "EMPLOYEE_LINE",
                "line_id": s.catalog.line,
                "employee_id": s.catalog.employee,
            },
            client=employee,
            csrf=csrf,
        )
        assert response.status_code == 201, response.text
        assert (
            mutate(m, "PUT", "/scheduling/settings", {}, client=employee, csrf=csrf).status_code
            == 403
        )


def test_tenant_isolation_csrf_and_inactive_resources(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    assert s.query(line_id=str(m.lab.other_line)).status_code == 404
    assert s.query(employee_id=str(m.lab.other_line)).status_code == 404
    path = f"/api/v1/scheduling/calendars/{s.employee}/weekly"
    assert m.lab.client.put(path, json={"periods": []}).status_code == 403
    with TestClient(m.lab.app, base_url=m.lab.other_origin) as other:
        assert (
            other.get(
                "/api/v1/scheduling/availability",
                params={
                    "line_id": s.catalog.line,
                    "service_ids": s.catalog.service,
                    "date_from": str(s.day),
                    "date_until": str(s.day + timedelta(days=1)),
                },
            ).status_code
            == 404
        )
    assert mutate(m, "PUT", s.catalog.link_path, {"is_active": False}).status_code == 200
    assert s.query().json()["items"] == []


def test_dst_gap_override_rejected_and_recurring_gap_fails_closed(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    with m.lab.database.lab.admin.begin() as connection:
        connection.execute(
            update(Salon).where(Salon.id == m.lab.tenant).values(timezone="America/New_York")
        )
    year = datetime.now(UTC).year
    # Find the next spring transition in the next 366 days.
    spring = date(year, 3, 8)
    spring += timedelta(days=(6 - spring.weekday()) % 7)
    if spring < datetime.now(UTC).date():
        spring = date(year + 1, 3, 8)
        spring += timedelta(days=(6 - spring.weekday()) % 7)
    s.day = spring
    assert (
        mutate(m, "PUT", "/scheduling/settings", {"booking_horizon_days": 366}).status_code == 200
    )
    response = s.override(
        s.employee, {"mode": "REPLACE", "periods": [{"start_minute": 150, "end_minute": 240}]}
    )
    assert (
        response.status_code == 422 and response.json()["error"]["code"] == "nonexistent_local_time"
    )
    assert s.weekly(s.salon, 0, 1440).status_code == 200
    assert s.weekly(s.employee, 150, 240).status_code == 200
    assert s.query().json()["items"] == []


def test_schedule_writer_waits_for_booking_lock_then_detects_new_conflict(
    schedule: Schedule,
) -> None:
    s, m = schedule, schedule.catalog.manager
    waiting = Event()

    def observed(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if "calendar_controls" in statement and "FOR UPDATE" in statement:
            waiting.set()

    event.listen(m.lab.runtime.database.engine, "before_cursor_execute", observed)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with m.lab.runtime.database.transaction(m.lab.tenant) as session:
                require_active_context(session, m.lab.context)
                lock_calendar(session, m.lab.tenant, shared=True)
                future = pool.submit(s.override, s.employee, {"mode": "CLOSED"})
                assert waiting.wait(2)
                assert not future.done()
                identifier = insert_booking(s, using=session.connection())
            response = future.result(timeout=10)
            assert response.status_code == 409, response.text
            assert response.json()["error"]["details"][0]["field"] == f"appointments.{identifier}"
    finally:
        event.remove(m.lab.runtime.database.engine, "before_cursor_execute", observed)


def test_auto_assignment_picks_least_daily_load_and_fixed_tie_break(schedule: Schedule) -> None:
    s, c, m = schedule, schedule.catalog, schedule.catalog.manager
    other = new_user(m, "09121234568", "employee")["employee"]["id"]
    assert mutate(m, "PUT", f"/lines/{c.line}/employees/{other}").status_code == 200
    assert (
        mutate(m, "PUT", f"/lines/{c.line}/employees/{other}/services/{c.service}").status_code
        == 200
    )
    calendar = mutate(
        m, "POST", "/scheduling/calendars", {"scope": "EMPLOYEE", "employee_id": other}
    ).json()["id"]
    assert s.weekly(calendar).status_code == 200
    assert s.query(assignment="auto").json()["items"][0]["employee_id"] == min(c.employee, other)
    assert len(s.query().json()["items"]) == 62
    insert_booking(s, 840, 60)
    result = s.query(assignment="auto").json()["items"]
    assert len(result) == 31 and all(item["employee_id"] == other for item in result)
    assert all(
        item["employee_id"] == c.employee
        for item in s.query(employee_id=c.employee).json()["items"]
    )


def test_notice_applies_to_buffer_start_and_settings_limit_packages(schedule: Schedule) -> None:
    s, c, m = schedule, schedule.catalog, schedule.catalog.manager
    assert (
        mutate(
            m,
            "PUT",
            c.offer_path,
            {"price_amount": 1_000_000, "duration_minutes": 30, "buffer_before_minutes": 10},
        ).status_code
        == 200
    )
    query = AvailabilityQuery(
        line_id=UUID(c.line),
        service_ids=[UUID(c.service)],
        date_from=s.day,
        date_until=s.day + timedelta(days=1),
    )
    with m.lab.runtime.database.transaction(m.lab.tenant) as session:
        lock_calendar(session, m.lab.tenant, shared=True)
        result = availability(session, query, now=s.at(490))
    assert result.items[0].starts_at == s.at(570)  # occupied 09:20 >= 08:10 + 60min
    assert mutate(m, "PUT", "/scheduling/settings", {"max_duration_minutes": 35}).status_code == 200
    assert s.query().status_code == 422
    assert mutate(m, "PUT", "/scheduling/settings", {"slot_step_minutes": 30}).status_code == 200
    assert s.minutes()[0] == 570


def test_contiguous_overnight_shift_allows_buffers_across_midnight(schedule: Schedule) -> None:
    s, c, m = schedule, schedule.catalog, schedule.catalog.manager
    for calendar in (s.salon, s.employee):
        assert s.weekly(calendar, 0, 1440).status_code == 200
    assert (
        mutate(
            m,
            "PUT",
            c.offer_path,
            {"price_amount": 1_000_000, "duration_minutes": 30, "buffer_after_minutes": 15},
        ).status_code
        == 200
    )
    assert 1425 in s.minutes()
    tomorrow = s.day + timedelta(days=1)
    assert (
        mutate(
            m, "PUT", f"/scheduling/calendars/{s.employee}/overrides/{tomorrow}", {"mode": "CLOSED"}
        ).status_code
        == 200
    )
    assert 1395 in s.minutes() and 1410 not in s.minutes()


def test_effective_weekly_end_is_exclusive_and_approved_block_survives_override(
    schedule: Schedule,
) -> None:
    s, m = schedule, schedule.catalog.manager
    period = {
        "weekday": s.day.weekday(),
        "start_minute": 540,
        "end_minute": 1020,
        "valid_from": str(s.day - timedelta(days=7)),
        "valid_until": str(s.day),
    }
    assert (
        mutate(
            m, "PUT", f"/scheduling/calendars/{s.employee}/weekly", {"periods": [period]}
        ).status_code
        == 200
    )
    assert s.minutes() == []
    assert (
        s.override(
            s.employee, {"mode": "REPLACE", "periods": [{"start_minute": 540, "end_minute": 1020}]}
        ).status_code
        == 200
    )
    assert s.block(s.employee).status_code == 201
    assert 780 not in s.minutes() and 840 in s.minutes()


def test_removing_special_workday_with_booking_is_rejected(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    assert s.weekly(s.employee, 780, 1020).status_code == 200
    assert (
        s.override(
            s.employee, {"mode": "REPLACE", "periods": [{"start_minute": 540, "end_minute": 1020}]}
        ).status_code
        == 200
    )
    insert_booking(s)
    response = mutate(m, "DELETE", f"/scheduling/calendars/{s.employee}/overrides/{s.day}")
    assert response.status_code == 409
    assert 540 in s.minutes()


def test_leave_approval_rechecks_bookings_and_own_request_can_be_cancelled(
    schedule: Schedule,
) -> None:
    s, m = schedule, schedule.catalog.manager
    with TestClient(m.lab.app, base_url=m.lab.origin) as employee:
        csrf = sign_in(m, employee)
        response = mutate(
            m,
            "POST",
            f"/scheduling/calendars/{s.employee}/leave-requests",
            {
                "kind": "LEAVE",
                "reason": "Travel",
                "starts_at": s.at(600).isoformat(),
                "ends_at": s.at(690).isoformat(),
            },
            client=employee,
            csrf=csrf,
        )
        assert response.status_code == 201
        identifier = response.json()["id"]
        insert_booking(s)
        assert (
            mutate(
                m, "PATCH", f"/scheduling/blocks/{identifier}", {"status": "APPROVED"}
            ).status_code
            == 409
        )
        assert (
            employee.get(f"/api/v1/scheduling/calendars/{s.employee}/blocks").json()["items"][0][
                "status"
            ]
            == "REQUESTED"
        )
        assert (
            mutate(
                m,
                "PATCH",
                f"/scheduling/blocks/{identifier}",
                {"status": "CANCELLED"},
                client=employee,
                csrf=csrf,
            ).status_code
            == 200
        )


def test_custom_personal_read_with_line_scope_cannot_list_global_calendar(
    schedule: Schedule,
) -> None:
    s, c, m = schedule, schedule.catalog, schedule.catalog.manager
    target = mutate(
        m,
        "POST",
        "/scheduling/calendars",
        {"scope": "EMPLOYEE_LINE", "line_id": c.line, "employee_id": c.employee},
    ).json()["id"]
    assignment = next(a["id"] for a in c.user["assignments"] if a["code"] == "employee")
    assert mutate(m, "DELETE", f"/role-assignments/{assignment}").status_code == 204
    role = mutate(
        m,
        "POST",
        "/roles",
        {"code": "limited_reader", "name": "Limited reader", "permissions": ["schedule.read_own"]},
    )
    assert role.status_code == 201, role.text
    assert assign(m, c.user, role.json()["id"], line=UUID(c.line)).status_code == 201
    with TestClient(m.lab.app, base_url=m.lab.origin) as employee:
        sign_in(m, employee)
        assert {r["id"] for r in employee.get("/api/v1/scheduling/calendars").json()["items"]} == {
            target
        }
        assert employee.get(f"/api/v1/scheduling/calendars/{target}/weekly").status_code == 200
        assert employee.get(f"/api/v1/scheduling/calendars/{s.employee}/weekly").status_code == 403
