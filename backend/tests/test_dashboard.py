from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.appointments.models import Appointment
from tests.test_authentication import AuthLab, login, register
from tests.test_authentication import auth_lab as auth_lab
from tests.test_catalog_workforce import booking
from tests.test_catalog_workforce import catalog as catalog
from tests.test_scheduling import Schedule
from tests.test_scheduling import schedule as schedule
from tests.test_tenant_management import assign, mutate, new_user, sign_in
from tests.test_tenant_management import manager as manager

pytestmark = pytest.mark.postgres


def test_customer_cannot_enter_workspace(auth_lab: AuthLab) -> None:
    register(auth_lab)
    login(auth_lab)
    assert auth_lab.client.get("/api/v1/dashboard/context").status_code == 403
    assert auth_lab.client.get("/api/v1/dashboard/overview").status_code == 403


def test_staff_counts_scope_and_personal_appointments(schedule: Schedule) -> None:
    s = schedule
    m = s.catalog.manager
    identifier = booking(s.catalog)
    with m.lab.database.lab.admin.connect() as conn:
        starts = conn.scalar(select(Appointment.starts_at).where(Appointment.id == identifier))
    assert starts is not None
    day = (starts + timedelta(hours=3, minutes=30)).date().isoformat()
    path = f"/api/v1/dashboard/overview?day={day}&limit=1"
    overview = m.lab.client.get(path)
    assert overview.status_code == 200, overview.text
    assert overview.json()["counts"] == {"CONFIRMED": 1}
    assert overview.json()["appointments"]["items"][0]["total_amount"] == 1_000_000
    with TestClient(m.lab.app, base_url=str(m.lab.client.base_url)) as employee:
        sign_in(m, employee)
        workspace = employee.get("/api/v1/dashboard/context").json()
        assert workspace["employee_id"] == s.catalog.employee
        result = employee.get(path)
        assert result.status_code == 200, result.text
        # This booking happens to be the employee's personal booking, but remains assigned.
        assert result.json()["counts"] == {"CONFIRMED": 1}
    person = new_user(m, "09125550002")
    assert assign(m, person, m.roles["line_manager"], line=UUID(s.catalog.line)).status_code == 201
    with TestClient(m.lab.app, base_url=str(m.lab.client.base_url)) as line_manager:
        sign_in(m, line_manager, "09125550002")
        context = line_manager.get("/api/v1/dashboard/context").json()
        assert [line["id"] for line in context["lines"]] == [s.catalog.line]
        assert line_manager.get(path).json()["counts"] == {"CONFIRMED": 1}
        other = mutate(m, "POST", "/lines", {"name": "Other", "slug": "other-work"}).json()["id"]
        assert line_manager.get(path + f"&line_id={other}").json()["counts"] == {}
        assert line_manager.get("/api/v1/users").status_code == 403


def test_employee_workspace_does_not_include_unassigned_personal_booking(
    schedule: Schedule,
) -> None:
    s, m = schedule, schedule.catalog.manager
    # Catalog booking belongs to employee's customer account; assign it to another employee.
    second = new_user(m, "09125550003", "employee")
    assert (
        mutate(
            m, "PUT", f"/lines/{s.catalog.line}/employees/{second['employee']['id']}", {}
        ).status_code
        == 200
    )
    identifier = booking(s.catalog)
    with m.lab.database.lab.admin.begin() as conn:
        from sqlalchemy import update

        conn.execute(
            update(Appointment)
            .where(Appointment.id == identifier)
            .values(employee_id=UUID(second["employee"]["id"]))
        )
        starts = conn.scalar(select(Appointment.starts_at).where(Appointment.id == identifier))
    assert starts is not None
    day = (starts + timedelta(hours=3, minutes=30)).date().isoformat()
    with TestClient(m.lab.app, base_url=str(m.lab.client.base_url)) as employee:
        sign_in(m, employee)
        own = employee.get("/api/v1/appointments?mine=true").json()
        assert len(own["items"]) == 1
        overview = employee.get(f"/api/v1/dashboard/overview?day={day}").json()
        assert overview["counts"] == {} and overview["appointments"]["items"] == []
