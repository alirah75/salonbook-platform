from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, event, func, select, update
from sqlalchemy.exc import IntegrityError

from app.db.enums import AppointmentStatus
from app.modules.access.models import RoleAssignment
from app.modules.appointments.models import Appointment, AppointmentItem
from app.modules.catalog.models import Line, LineService, Service
from app.modules.identity.context import require_active_context
from app.modules.identity.models import User
from app.modules.operations.models import AuditLog
from app.modules.scheduling.coordination import lock_calendar
from app.modules.tenancy.models import CalendarControl
from app.modules.workforce.models import EmployeeLine, EmployeeProfile, EmployeeService
from tests.conftest import add, appointment_values
from tests.test_authentication import auth_lab as auth_lab
from tests.test_tenant_management import Manager, assign, mutate, new_user, sign_in
from tests.test_tenant_management import manager as manager

pytestmark = pytest.mark.postgres
OFFER: dict[str, Any] = {
    "price_amount": 1_000_000,
    "duration_minutes": 30,
    "buffer_before_minutes": 5,
    "buffer_after_minutes": 10,
}


@dataclass
class Catalog:
    manager: Manager
    line: str
    service: str
    employee: str
    user: dict[str, Any]

    @property
    def offer_path(self) -> str:
        return f"/lines/{self.line}/services/{self.service}"

    @property
    def link_path(self) -> str:
        return f"/lines/{self.line}/employees/{self.employee}"

    @property
    def skill_path(self) -> str:
        return f"{self.link_path}/services/{self.service}"

    @property
    def public_path(self) -> str:
        return f"/api/v1/catalog/lines/{self.line}/services/{self.service}/employees"


@pytest.fixture
def catalog(manager: Manager) -> Catalog:
    line = mutate(manager, "POST", "/lines", {"name": "آرایش مو", "slug": "new-hair"})
    product = mutate(
        manager,
        "POST",
        "/services",
        {"name": "کوتاهی مو", "code": "new-cut", "description": "شرح خدمت"},
    )
    assert line.status_code == 201, line.text
    assert product.status_code == 201, product.text
    user = new_user(manager, kind="employee")
    result = Catalog(manager, line.json()["id"], product.json()["id"], user["employee"]["id"], user)
    for path, body in ((result.offer_path, OFFER), (result.link_path, {}), (result.skill_path, {})):
        response = mutate(manager, "PUT", path, body)
        assert response.status_code == 200, response.text
    return result


def booking(
    catalog: Catalog,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
    *,
    using: Connection | None = None,
) -> UUID:
    lab = catalog.manager.lab
    seed = {
        "tenant": lab.tenant,
        "line": UUID(catalog.line),
        "employee": UUID(catalog.employee),
        "customer": UUID(catalog.user["customer_id"]),
    }
    with nullcontext(using) if using is not None else lab.database.lab.admin.begin() as connection:
        identifier = add(
            connection,
            "appointments",
            **appointment_values(
                seed,
                status=status,
                confirmed_at=datetime.now(UTC) if status == AppointmentStatus.CONFIRMED else None,
            ),
        )
        add(
            connection,
            "appointment_items",
            tenant_id=lab.tenant,
            appointment_id=identifier,
            original_employee_id=UUID(catalog.employee),
            line_id=UUID(catalog.line),
            service_id=UUID(catalog.service),
            position=1,
            service_name="Original service",
            line_name="Original line",
            employee_name="Original employee",
            duration_minutes=30,
            amount=1_000_000,
        )
    return identifier


def test_complete_catalog_and_workforce_flow_has_private_and_public_views(catalog: Catalog) -> None:
    c, m = catalog, catalog.manager
    assert m.lab.client.get(f"/api/v1/lines/{c.line}").json()["name"] == "آرایش مو"
    assert m.lab.client.get(f"/api/v1/services/{c.service}").json()["code"] == "new-cut"
    assert c.employee in {e["id"] for e in m.lab.client.get("/api/v1/employees").json()["items"]}
    links = m.lab.client.get(f"/api/v1/lines/{c.line}/employees").json()["items"]
    assert links[0]["employee_id"] == c.employee and links[0]["effective_active"]
    assert m.lab.client.get(f"/api/v1{c.link_path}/services").json()["items"][0]["effective_active"]
    with TestClient(m.lab.app, base_url=m.lab.origin) as visitor:
        assert visitor.get("/api/v1/lines").status_code == 401
        assert visitor.get("/api/v1/employees").status_code == 401
        assert c.line in {r["id"] for r in visitor.get("/api/v1/catalog/lines").json()["items"]}
        public_offer = visitor.get(f"/api/v1/catalog/lines/{c.line}/services").json()["items"][0]
        assert public_offer["price_amount"] == OFFER["price_amount"]
        assert public_offer["currency"] == "IRR" and public_offer["buffer_after_minutes"] == 10
        staff = visitor.get(c.public_path).json()["items"]
        assert staff == [{"id": c.employee, "public_name": "New person"}]
        assert visitor.get("/api/v1/catalog/lines?limit=1").json()["has_more"] is True
    with m.lab.database.lab.admin.connect() as connection:
        actions = set(
            connection.scalars(select(AuditLog.action).where(AuditLog.tenant_id == m.lab.tenant))
        )
        assert actions >= {
            "line.created",
            "service.created",
            "line_service.saved",
            "employee_line.saved",
            "employee_service.saved",
        }


def test_shared_service_has_independent_line_price_duration_and_buffers(catalog: Catalog) -> None:
    c, m = catalog, catalog.manager
    second = mutate(m, "POST", "/lines", {"name": "Second", "slug": "second"}).json()["id"]
    modified = {
        **OFFER,
        "price_amount": 2_500_000,
        "duration_minutes": 50,
        "buffer_before_minutes": 15,
    }
    assert mutate(m, "PUT", f"/lines/{second}/services/{c.service}", modified).status_code == 200
    original = m.lab.client.get(f"/api/v1/lines/{c.line}/services").json()["items"][0]
    other = m.lab.client.get(f"/api/v1/lines/{second}/services").json()["items"][0]
    assert original["price_amount"] == 1_000_000 and other["price_amount"] == 2_500_000
    assert original["duration_minutes"] == 30 and other["duration_minutes"] == 50
    assert (
        mutate(
            m, "PATCH", f"/services/{c.service}", {"name": "New common name", "description": None}
        ).status_code
        == 200
    )
    assert (
        m.lab.client.get(f"/api/v1/catalog/lines/{c.line}/services").json()["items"][0][
            "service_name"
        ]
        == "New common name"
    )
    assert (
        mutate(
            m, "PATCH", f"/lines/{c.line}", {"slug": "changed-slug", "name": "New line"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "change",
    [
        {"price_amount": -1},
        {"price_amount": 1.5},
        {"price_amount": True},
        {"price_amount": "1000"},
        {"price_amount": 0},
        {"price_amount": 2**63},
        {"is_free": True},
        {"currency": "USD"},
        {"duration_minutes": 0},
        {"duration_minutes": 1441},
        {"duration_minutes": 1.5},
        {"buffer_before_minutes": -1},
        {"buffer_after_minutes": 241},
        {"tenant_id": str(uuid4())},
    ],
)
def test_offer_rejects_invalid_money_duration_buffers_and_tenant_injection(
    manager: Manager, change: dict[str, Any]
) -> None:
    response = mutate(manager, "PUT", f"/lines/{uuid4()}/services/{uuid4()}", {**OFFER, **change})
    assert response.status_code == 422


def test_free_price_and_repeated_put_preserve_identity(catalog: Catalog) -> None:
    c, m = catalog, catalog.manager
    first = mutate(m, "PUT", c.offer_path, {**OFFER, "price_amount": 0, "is_free": True})
    assert first.status_code == 200 and first.json()["is_free"]
    assert mutate(m, "PUT", c.offer_path, OFFER).json()["id"] == first.json()["id"]
    link = mutate(m, "PUT", c.link_path, {}).json()["id"]
    skill = mutate(m, "PUT", c.skill_path, {}).json()["id"]
    assert mutate(m, "PUT", c.link_path, {}).json()["id"] == link
    assert mutate(m, "PUT", c.skill_path, {}).json()["id"] == skill
    with m.lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(EmployeeService)
                .where(
                    EmployeeService.line_id == UUID(c.line),
                    EmployeeService.employee_id == UUID(c.employee),
                )
            )
            == 1
        )


def test_skills_require_both_line_membership_and_offer(catalog: Catalog) -> None:
    c, m = catalog, catalog.manager
    second = mutate(m, "POST", "/lines", {"name": "Second", "slug": "second"}).json()["id"]
    skill = f"/lines/{second}/employees/{c.employee}/services/{c.service}"
    assert mutate(m, "PUT", skill, {}).status_code == 404
    assert mutate(m, "PUT", f"/lines/{second}/employees/{c.employee}", {}).status_code == 200
    assert mutate(m, "PUT", skill, {}).status_code == 404
    assert mutate(m, "PUT", f"/lines/{second}/services/{c.service}", OFFER).status_code == 200
    assert mutate(m, "PUT", skill, {}).status_code == 200


def test_database_also_rejects_paid_offer_marked_free(catalog: Catalog) -> None:
    with (
        pytest.raises(IntegrityError),
        catalog.manager.lab.database.lab.admin.begin() as connection,
    ):
        connection.execute(
            update(LineService)
            .where(
                LineService.line_id == UUID(catalog.line),
                LineService.service_id == UUID(catalog.service),
            )
            .values(price_amount=1_000_000, is_free=True)
        )


def test_line_manager_can_manage_own_assignments_without_global_or_other_line_access(
    catalog: Catalog,
) -> None:
    c, m = catalog, catalog.manager
    person = new_user(m, "09121234568")
    assert assign(m, person, m.roles["line_manager"], line=UUID(c.line)).status_code == 201
    with TestClient(m.lab.app, base_url=m.lab.origin) as client:
        csrf = sign_in(m, client, "09121234568")
        assert {row["id"] for row in client.get("/api/v1/lines").json()["items"]} == {c.line}
        assert client.get("/api/v1/services").status_code == 200
        candidates = client.get(f"/api/v1/lines/{c.line}/employee-candidates").json()["items"]
        assert {"id", "public_name"} == set(candidates[0])
        assert c.employee in {r["id"] for r in candidates}
        for path in (f"/lines/{c.line}/employees", f"{c.link_path}/services"):
            assert client.get(f"/api/v1{path}").status_code == 200
        assert (
            mutate(
                m, "PATCH", f"/lines/{c.line}", {"name": "Own line"}, client=client, csrf=csrf
            ).status_code
            == 200
        )
        assert (
            mutate(
                m,
                "PUT",
                c.offer_path,
                {**OFFER, "price_amount": 2_000_000},
                client=client,
                csrf=csrf,
            ).status_code
            == 200
        )
        assert mutate(m, "DELETE", c.link_path, client=client, csrf=csrf).status_code == 204
        assert mutate(m, "PUT", c.link_path, {}, client=client, csrf=csrf).status_code == 200
        assert mutate(m, "PUT", c.skill_path, {}, client=client, csrf=csrf).status_code == 200
        for method, path, body in (
            ("POST", "/lines", {"name": "Denied", "slug": "denied"}),
            ("DELETE", f"/lines/{c.line}", {}),
            ("PATCH", f"/lines/{m.lab.line}", {"name": "Other line"}),
            ("PUT", f"/lines/{m.lab.line}/employees/{c.employee}", {}),
            ("PATCH", f"/services/{c.service}", {"name": "Global edit"}),
            ("DELETE", f"/employees/{c.employee}", {}),
            ("PUT", f"/users/{c.user['id']}/employee", {"public_name": "Global edit"}),
        ):
            assert mutate(m, method, path, body, client=client, csrf=csrf).status_code == 403
        assert client.get("/api/v1/employees").status_code == 403


def test_customer_cannot_mutate_catalog_or_employee_links(catalog: Catalog) -> None:
    c, m = catalog, catalog.manager
    with TestClient(m.lab.app, base_url=m.lab.origin) as client:
        csrf = sign_in(m, client)
        for path in ("/lines", "/services", "/employees", f"/lines/{c.line}/employees"):
            assert client.get(f"/api/v1{path}").status_code == 403
        for method, path, data in (
            ("PATCH", f"/lines/{c.line}", {"name": "Bad"}),
            ("PUT", c.skill_path, {}),
            ("DELETE", f"/employees/{c.employee}", {}),
        ):
            assert mutate(m, method, path, data, client=client, csrf=csrf).status_code == 403
        assert client.get(c.public_path).status_code == 200


def test_catalog_and_employee_identifiers_are_tenant_isolated(catalog: Catalog) -> None:
    c, m = catalog, catalog.manager
    with m.lab.database.lab.admin.connect() as connection:
        other_service = connection.scalar(
            select(Service.id).where(Service.tenant_id == m.lab.other_tenant)
        )
        other_employee = connection.scalar(
            select(EmployeeProfile.id).where(EmployeeProfile.tenant_id == m.lab.other_tenant)
        )
    for path in (
        f"/lines/{m.lab.other_line}",
        f"/services/{other_service}",
        f"/catalog/lines/{m.lab.other_line}/services",
    ):
        assert m.lab.client.get(f"/api/v1{path}").status_code == 404
    for method, path, data in (
        ("PATCH", f"/lines/{m.lab.other_line}", {"name": "Cross tenant"}),
        ("DELETE", f"/services/{other_service}", {}),
        ("PUT", f"/lines/{c.line}/services/{other_service}", OFFER),
        ("PUT", f"/lines/{c.line}/employees/{other_employee}", {}),
        ("PUT", f"{c.link_path}/services/{other_service}", {}),
        ("DELETE", f"/employees/{other_employee}", {}),
    ):
        assert mutate(m, method, path, data).status_code == 404
    public = m.lab.client.get(
        "/api/v1/catalog/lines", headers={"X-Tenant-ID": str(m.lab.other_tenant)}
    ).json()["items"]
    assert str(m.lab.other_line) not in {row["id"] for row in public}


@pytest.mark.parametrize(
    "parent", ["line", "service", "offer", "employee", "user", "employee_line", "employee_service"]
)
def test_inactive_resource_is_not_publicly_selectable_and_cannot_be_assigned(
    catalog: Catalog, parent: str
) -> None:
    c, m = catalog, catalog.manager
    actions: dict[str, tuple[str, str, dict[str, Any]]] = {
        "line": ("PATCH", f"/lines/{c.line}", {"is_active": False}),
        "service": ("PATCH", f"/services/{c.service}", {"is_active": False}),
        "offer": ("PUT", c.offer_path, {**OFFER, "is_active": False}),
        "employee": (
            "PUT",
            f"/users/{c.user['id']}/employee",
            {"public_name": "Employee", "is_active": False},
        ),
        "user": ("PATCH", f"/users/{c.user['id']}", {"is_active": False}),
        "employee_line": ("PUT", c.link_path, {"is_active": False}),
        "employee_service": ("PUT", c.skill_path, {"is_active": False}),
    }
    method, path, data = actions[parent]
    assert mutate(m, method, path, data).status_code == 200
    response = m.lab.client.get(c.public_path)
    assert response.status_code == 404 or response.json()["items"] == []
    if parent != "employee_service":
        assert mutate(m, "PUT", c.skill_path, {}).status_code == 409
    if parent in ("line", "employee", "user"):
        assert mutate(m, "PUT", c.link_path, {}).status_code == 409


@pytest.mark.parametrize("relation", ["offer", "employee_line"])
def test_detach_and_restore_keeps_ids_without_resurrecting_old_skills(
    catalog: Catalog, relation: str
) -> None:
    c, m = catalog, catalog.manager
    path, data = (c.offer_path, OFFER) if relation == "offer" else (c.link_path, {})
    original = mutate(m, "PUT", path, data).json()["id"]
    old_skill = mutate(m, "PUT", c.skill_path, {}).json()["id"]
    assert mutate(m, "DELETE", path).status_code == 204
    assert mutate(m, "PUT", path, data).json()["id"] == original
    assert m.lab.client.get(c.public_path).json()["items"] == []
    assert mutate(m, "PUT", c.skill_path, {}).json()["id"] == old_skill
    assert m.lab.client.get(c.public_path).json()["items"][0]["id"] == c.employee
    assert mutate(m, "DELETE", c.skill_path).status_code == 204
    assert mutate(m, "DELETE", c.skill_path).status_code == 404


def test_delete_employee_preserves_customer_and_history_but_revokes_staff_session(
    catalog: Catalog,
) -> None:
    c, m = catalog, catalog.manager
    with TestClient(m.lab.app, base_url=m.lab.origin) as client:
        sign_in(m, client)
        assert mutate(m, "DELETE", f"/employees/{c.employee}").status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
        sign_in(m, client)
        assert client.get("/api/v1/auth/me").json()["user"]["roles"] == ["customer"]
    with m.lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(select(User.is_active).where(User.id == UUID(c.user["id"]))) is True
        )
        assert (
            connection.scalar(
                select(EmployeeProfile.deleted_at).where(EmployeeProfile.id == UUID(c.employee))
            )
            is not None
        )
        assert (
            connection.scalar(
                select(EmployeeLine.deleted_at).where(
                    EmployeeLine.employee_id == UUID(c.employee),
                    EmployeeLine.line_id == UUID(c.line),
                )
            )
            is not None
        )
    assert m.lab.client.get(c.public_path).json()["items"] == []
    restored = mutate(
        m, "PUT", f"/users/{c.user['id']}/employee", {"public_name": "Returned employee"}
    )
    assert restored.status_code == 200 and restored.json()["employee"]["id"] == c.employee
    assert m.lab.client.get(c.public_path).json()["items"] == []


@pytest.mark.parametrize(
    "resource",
    [
        "line",
        "service",
        "offer",
        "employee",
        "employee_line",
        "employee_service",
        "user",
        "employee_status",
    ],
)
def test_upcoming_bookings_block_removal_and_existing_status_endpoints(
    catalog: Catalog, resource: str
) -> None:
    c, m = catalog, catalog.manager
    identifier = booking(c)
    cases: dict[str, tuple[str, str, dict[str, Any]]] = {
        "line": ("DELETE", f"/lines/{c.line}", {}),
        "service": ("DELETE", f"/services/{c.service}", {}),
        "offer": ("DELETE", c.offer_path, {}),
        "employee": ("DELETE", f"/employees/{c.employee}", {}),
        "employee_line": ("DELETE", c.link_path, {}),
        "employee_service": ("DELETE", c.skill_path, {}),
        "user": ("PATCH", f"/users/{c.user['id']}", {"is_active": False}),
        "employee_status": (
            "PUT",
            f"/users/{c.user['id']}/employee",
            {"public_name": "Hidden", "is_active": False},
        ),
    }
    method, path, data = cases[resource]
    with m.lab.database.lab.admin.connect() as connection:
        version = connection.scalar(
            select(CalendarControl.version).where(CalendarControl.tenant_id == m.lab.tenant)
        )
    response = mutate(m, method, path, data)
    assert response.status_code == 409 and response.json()["error"]["code"] == "upcoming_bookings"
    with m.lab.database.lab.admin.begin() as connection:
        assert (
            connection.scalar(
                select(CalendarControl.version).where(CalendarControl.tenant_id == m.lab.tenant)
            )
            == version
        )
        assert (
            connection.scalar(select(Appointment.status).where(Appointment.id == identifier))
            == AppointmentStatus.CONFIRMED
        )
        connection.execute(
            update(Appointment)
            .where(Appointment.id == identifier)
            .values(status=AppointmentStatus.CANCELLED, cancelled_at=datetime.now(UTC))
        )
    assert mutate(m, method, path, data).status_code in (200, 204)
    with m.lab.database.lab.admin.connect() as connection:
        assert connection.scalar(
            select(AppointmentItem.id).where(AppointmentItem.appointment_id == identifier)
        )


def test_repricing_keeps_existing_booking_snapshots_and_hold_blocks_deactivation(
    catalog: Catalog,
) -> None:
    c, m = catalog, catalog.manager
    identifier = booking(c, AppointmentStatus.AWAITING_PAYMENT)
    assert (
        mutate(
            m, "PUT", c.offer_path, {**OFFER, "price_amount": 5_000_000, "duration_minutes": 90}
        ).status_code
        == 200
    )
    for method, path, body in (
        ("PATCH", f"/lines/{c.line}", {"is_active": False}),
        ("PATCH", f"/services/{c.service}", {"is_active": False}),
        ("PUT", c.offer_path, {**OFFER, "is_active": False}),
        ("PUT", c.link_path, {"is_active": False}),
        ("PUT", c.skill_path, {"is_active": False}),
    ):
        assert mutate(m, method, path, body).status_code == 409
    with m.lab.database.lab.admin.connect() as connection:
        row = connection.execute(
            select(
                AppointmentItem.amount,
                AppointmentItem.duration_minutes,
                AppointmentItem.service_name,
            ).where(AppointmentItem.appointment_id == identifier)
        ).one()
        assert tuple(row) == (1_000_000, 30, "Original service")
        assert (
            connection.scalar(select(Appointment.total_amount).where(Appointment.id == identifier))
            == 1_000_000
        )


def test_delete_line_revokes_scoped_roles_and_soft_deletes_only_its_relations(
    catalog: Catalog,
) -> None:
    c, m = catalog, catalog.manager
    person = new_user(m, "09121234568")
    assert assign(m, person, m.roles["line_manager"], line=UUID(c.line)).status_code == 201
    assert assign(m, person, m.roles["line_manager"], line=m.lab.line).status_code == 201
    with TestClient(m.lab.app, base_url=m.lab.origin) as client:
        sign_in(m, client, "09121234568")
        assert mutate(m, "DELETE", f"/lines/{c.line}").status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
        sign_in(m, client, "09121234568")
        assert {r["id"] for r in client.get("/api/v1/lines").json()["items"]} == {str(m.lab.line)}
    with m.lab.database.lab.admin.connect() as connection:
        assert connection.scalar(select(Line.deleted_at).where(Line.id == UUID(c.line)))
        assert connection.scalar(
            select(LineService.deleted_at).where(LineService.line_id == UUID(c.line))
        )
        assert connection.scalar(
            select(EmployeeService.deleted_at).where(EmployeeService.line_id == UUID(c.line))
        )
        assert connection.scalar(
            select(RoleAssignment.revoked_at).where(
                RoleAssignment.user_id == UUID(person["id"]), RoleAssignment.line_id == UUID(c.line)
            )
        )
        assert (
            connection.scalar(select(Service.deleted_at).where(Service.id == UUID(c.service)))
            is None
        )


def test_concurrent_detach_and_skill_assignment_cannot_leave_an_active_orphan(
    catalog: Catalog,
) -> None:
    c, m = catalog, catalog.manager
    person = new_user(m, "09121234568")
    assert assign(m, person, m.roles["salon_manager"]).status_code == 201
    with TestClient(m.lab.app, base_url=m.lab.origin) as second:
        csrf = sign_in(m, second, "09121234568")
        with ThreadPoolExecutor(max_workers=2) as pool:
            deleting = pool.submit(mutate, m, "DELETE", c.link_path)
            saving = pool.submit(mutate, m, "PUT", c.skill_path, {}, client=second, csrf=csrf)
            assert deleting.result().status_code == 204
            assert saving.result().status_code in (200, 404)
    with m.lab.database.lab.admin.connect() as connection:
        row = connection.execute(
            select(EmployeeService.is_active, EmployeeService.deleted_at).where(
                EmployeeService.employee_id == UUID(c.employee),
                EmployeeService.line_id == UUID(c.line),
            )
        ).one()
        assert not row.is_active and row.deleted_at is not None


def test_catalog_removal_waits_for_booking_transaction_and_then_rechecks(catalog: Catalog) -> None:
    c, m = catalog, catalog.manager
    requested = Event()
    engine = m.lab.runtime.database.engine

    def before_execute(
        connection: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if "calendar_controls" in statement and "FOR UPDATE" in statement:
            requested.set()

    event.listen(engine, "before_cursor_execute", before_execute)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with m.lab.runtime.database.transaction(m.lab.tenant) as session:
                require_active_context(session, m.lab.context)
                lock_calendar(session, m.lab.tenant, shared=True)
                deleting = pool.submit(mutate, m, "DELETE", f"/employees/{c.employee}")
                assert requested.wait(timeout=2), "Catalog writer did not acquire the calendar lock"
                assert not deleting.done()
                booking(c, using=session.connection())
            response = deleting.result(timeout=5)
            assert (
                response.status_code == 409
                and response.json()["error"]["code"] == "upcoming_bookings"
            )
    finally:
        event.remove(engine, "before_cursor_execute", before_execute)


def test_names_unique_codes_input_limits_and_csrf(catalog: Catalog) -> None:
    c, m = catalog, catalog.manager
    assert mutate(m, "POST", "/lines", {"name": "Duplicate", "slug": "new-hair"}).status_code == 409
    assert (
        mutate(m, "POST", "/services", {"name": "Duplicate", "code": "new-cut"}).status_code == 409
    )
    for path, data in (
        ("/lines", {"name": " ", "slug": "valid"}),
        ("/lines", {"name": "Invalid", "slug": "../bad"}),
        ("/services", {"name": " ", "code": "valid"}),
        ("/services", {"name": "Invalid", "code": "bad code"}),
    ):
        assert mutate(m, "POST", path, data).status_code == 422
    assert mutate(m, "PATCH", f"/lines/{c.line}", {}).status_code == 422
    assert mutate(m, "PATCH", f"/services/{c.service}", {"name": None}).status_code == 422
    assert mutate(m, "PUT", c.link_path, {"user_id": str(uuid4())}).status_code == 422
    for path in ("/catalog/lines?limit=101", "/services?offset=-1", "/employees?limit=0"):
        assert m.lab.client.get(f"/api/v1{path}").status_code == 422
    assert mutate(m, "PUT", c.offer_path, OFFER, csrf="f" * 64).status_code == 403
    assert (
        m.lab.client.delete(f"/api/v1{c.link_path}", headers={"X-CSRF-Token": m.csrf}).status_code
        == 403
    )
