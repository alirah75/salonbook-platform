from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.access.models import Role, RoleAssignment
from app.modules.appointments.models import AppointmentItem
from app.modules.billing import service as billing
from app.modules.billing.models import FinancialEntry
from app.modules.identity.models import User
from app.modules.payments.models import PaymentTransaction, Refund
from app.modules.payments.worker import PaymentWorker
from tests.test_appointments import command
from tests.test_authentication import auth_lab as auth_lab
from tests.test_authentication import login, register
from tests.test_catalog_workforce import catalog as catalog
from tests.test_payments import finish, pay, processor, started
from tests.test_scheduling import Schedule
from tests.test_scheduling import schedule as schedule
from tests.test_tenant_management import assign, mutate, new_user, sign_in
from tests.test_tenant_management import manager as manager

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def mock_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALONBOOK_MOCK_PAYMENTS_ENABLED", "true")


def query(s: Schedule, path: str = "report", **params: Any) -> dict[str, Any]:
    today = datetime.now(ZoneInfo("Asia/Tehran")).date().isoformat()
    response = s.catalog.manager.lab.client.get(
        f"/api/v1/finance/{path}", params={"start": today, "end": today, **params}
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_cash_report_refund_reservation_and_documents(schedule: Schedule) -> None:
    s = schedule
    appointment, payment = started(s)
    assert query(s)["totals"]["received"] == "0"
    receipt = finish(s, payment)["transactions"][0]
    report = query(s)
    assert report["totals"]["revenue"] == "1000000"
    assert report["daily"][0]["received"] == "1000000"
    assert query(s, is_test=False)["totals"]["received"] == "0"
    request = pay(
        s, f"/transactions/{receipt['id']}/refunds", {"amount": 123457, "reason": "Partial refund"}
    )
    assert request.status_code == 201, request.text
    assert query(s)["totals"]["refunded"] == "0"
    docs = query(s, "documents", kind="payments")["items"]
    assert docs[0]["refundable"] == "876543" and docs[0]["allocated"]
    assert pay(s, f"/refunds/{request.json()['id']}/approve").json()["status"] == "SUCCEEDED"
    report = query(s)
    assert report["totals"]["refunded"] == "123457"
    assert report["totals"]["net"] == report["totals"]["revenue"] == "876543"
    for dimension in ("line", "employee", "service"):
        row = query(s, "breakdown", dimension=dimension)["items"][0]
        assert (row["received"], row["refunded"], row["net"]) == ("1000000", "123457", "876543")
    refunds = query(s, "documents", kind="refunds")["items"]
    assert refunds[0]["status"] == "SUCCEEDED" and refunds[0]["number"].startswith("TEST-CR-")
    invoice = query(s, "documents", kind="invoices")["items"][0]
    assert invoice["appointment_id"] == appointment["id"]
    detail = s.catalog.manager.lab.client.get(f"/api/v1/finance/invoices/{invoice['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["amount"] == "1000000" and detail.json()["items"][0]["amount"] == "1000000"
    assert not query(s, "documents", kind="invoices", offset=1)["items"]


def test_unallocated_receipt_never_becomes_service_revenue(schedule: Schedule) -> None:
    s = schedule
    _, payment = started(s)
    finish(s, payment, "amount_mismatch")
    report = query(s)
    assert report["totals"]["received"] == report["totals"]["unallocated_net"] == "1000001"
    assert report["totals"]["revenue"] == "0"
    assert not query(s, "breakdown", dimension="service")["items"]
    assert not query(s, "documents", kind="invoices")["items"]
    PaymentWorker(processor(s)).batch(s.catalog.manager.lab.tenant)
    assert query(s)["totals"]["refunded"] == "1000001"
    assert query(s)["totals"]["unallocated_net"] == "0"


def test_scope_is_finance_permission_only_and_invoice_is_private(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    _, payment = started(s)
    finish(s, payment)
    invoice = query(s, "documents", kind="invoices")["items"][0]
    today = datetime.now(ZoneInfo("Asia/Tehran")).date().isoformat()
    paths = [
        f"/api/v1/finance/{p}?start={today}&end={today}"
        for p in (
            "report",
            "breakdown&dimension=line",
            "documents&kind=payments",
        )
    ]
    paths = [
        p.replace("breakdown&dimension=line?", "breakdown?dimension=line&").replace(
            "documents&kind=payments?", "documents?kind=payments&"
        )
        for p in paths
    ]
    paths.append(f"/api/v1/finance/invoices/{invoice['id']}")
    with TestClient(m.lab.app, base_url=m.lab.origin) as browser:
        assert all(browser.get(p).status_code == 401 for p in paths)
        sign_in(m, browser)  # Employee, even when personally owning appointments.
        assert all(browser.get(p).status_code == 403 for p in paths)
    person = new_user(m, "09125550123")
    other = mutate(m, "POST", "/lines", {"name": "Other finance", "slug": "other-finance"}).json()[
        "id"
    ]
    assert assign(m, person, m.roles["line_manager"], line=UUID(other)).status_code == 201
    with TestClient(m.lab.app, base_url=m.lab.origin) as browser:
        sign_in(m, browser, "09125550123")
        assert browser.get(paths[0]).json()["totals"]["received"] == "0"
        assert browser.get(paths[1]).json()["items"] == []
        assert browser.get(paths[2]).json()["items"] == []
        assert browser.get(paths[3]).status_code == 404
        assert browser.get(paths[0] + f"&line_id={s.catalog.line}").status_code == 403
        assert (
            assign(m, person, m.roles["line_manager"], line=UUID(s.catalog.line)).status_code == 201
        )
        assert browser.get(paths[0]).status_code == 401  # Changed grants revoke old session.
        sign_in(m, browser, "09125550123")
        assert browser.get(paths[0]).json()["totals"]["received"] == "1000000"
        assert browser.get(paths[3]).status_code == 200
    with TestClient(m.lab.app, base_url=m.lab.other_origin) as browser:
        browser.cookies.update(m.lab.client.cookies)
        assert all(browser.get(p).status_code == 401 for p in paths)
        browser.cookies.clear()
        assert register(m.lab, client=browser).status_code == 202
        with Session(m.lab.database.lab.admin) as session, session.begin():
            person_id = session.scalar(
                select(User.id).where(
                    User.tenant_id == m.lab.other_tenant, User.phone_normalized.is_not(None)
                )
            )
            role_id = session.scalar(
                select(Role.id).where(
                    Role.tenant_id == m.lab.other_tenant, Role.code == "salon_manager"
                )
            )
            assert person_id is not None and role_id is not None
            session.add(
                RoleAssignment(
                    tenant_id=m.lab.other_tenant, user_id=person_id, role_id=role_id, scope="TENANT"
                )
            )
        assert login(m.lab, client=browser).status_code == 200
        assert browser.get(paths[0]).json()["totals"]["received"] == "0"
        assert browser.get(paths[1]).json()["items"] == []
        assert browser.get(paths[2]).json()["items"] == []
        assert browser.get(paths[3]).status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2026-01-02", "end": "2026-01-01"},
        {"start": "2024-01-01", "end": "2025-01-01"},
        {"start": "1999-12-31"},
        {"end": "2101-01-01"},
    ],
)
def test_bounded_report_dates(schedule: Schedule, params: dict[str, str]) -> None:
    response = schedule.catalog.manager.lab.client.get(
        "/api/v1/finance/report", params={"start": "2026-01-01", "end": "2026-01-01", **params}
    )
    assert response.status_code == 422, response.text


def test_local_midnight_and_refund_on_later_day(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = schedule
    boundary = datetime(2026, 1, 2, tzinfo=ZoneInfo("Asia/Tehran")).astimezone(UTC)
    capture, credit = billing.capture, billing.credit

    def historical_capture(session: Session, transaction: PaymentTransaction) -> None:
        capture(session, transaction)
        for item in session.new:
            if isinstance(item, FinancialEntry):
                item.booked_at = boundary - timedelta(microseconds=1)

    def historical_credit(session: Session, row: Refund) -> None:
        credit(session, row)
        for item in session.new:
            if isinstance(item, FinancialEntry):
                item.booked_at = boundary

    monkeypatch.setattr(billing, "capture", historical_capture)
    monkeypatch.setattr(billing, "credit", historical_credit)
    _, payment = started(s)
    receipt = finish(s, payment)["transactions"][0]
    refund = pay(
        s, f"/transactions/{receipt['id']}/refunds", {"amount": 1, "reason": "One rial"}
    ).json()
    assert pay(s, f"/refunds/{refund['id']}/approve").json()["status"] == "SUCCEEDED"
    first = query(s, start="2026-01-01", end="2026-01-01")
    second = query(s, start="2026-01-02", end="2026-01-02")
    assert first["totals"]["received"] == "1000000" and first["totals"]["refunded"] == "0"
    assert second["totals"]["net"] == "-1"
    breakdown = query(s, "breakdown", dimension="service", start="2026-01-02", end="2026-01-02")
    assert breakdown["items"][0]["net"] == "-1"
    empty = query(s, start="2026-01-03", end="2026-01-05")
    assert len(empty["daily"]) == 3 and all(d["net"] == "0" for d in empty["daily"])


def test_document_pagination_has_no_duplicates(schedule: Schedule) -> None:
    s = schedule
    _, payment = started(s)
    receipt = finish(s, payment)["transactions"][0]
    for amount in (1, 2, 3):
        assert (
            pay(
                s,
                f"/transactions/{receipt['id']}/refunds",
                {"amount": amount, "reason": uuid4().hex},
            ).status_code
            == 201
        )
    pages = [query(s, "documents", kind="refunds", limit=1, offset=n) for n in range(3)]
    assert [p["has_more"] for p in pages] == [True, True, False]
    assert len({p["items"][0]["id"] for p in pages}) == 3
    with s.catalog.manager.lab.runtime.database.transaction(
        s.catalog.manager.lab.tenant, read_only=True
    ) as session:
        assert session.scalar(select(PaymentTransaction.amount)) == 1000000


def test_partial_refunds_follow_item_order_across_report_boundaries(
    schedule: Schedule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s, m = schedule, schedule.catalog.manager
    assert (
        mutate(
            m, "PUT", s.catalog.offer_path, {"price_amount": 5, "duration_minutes": 30}
        ).status_code
        == 200
    )
    product = mutate(
        m, "POST", "/services", {"name": "Second item", "code": "second-finance"}
    ).json()["id"]
    assert (
        mutate(
            m,
            "PUT",
            f"/lines/{s.catalog.line}/services/{product}",
            {"price_amount": 7, "duration_minutes": 30},
        ).status_code
        == 200
    )
    assert mutate(m, "PUT", f"{s.catalog.link_path}/services/{product}", {}).status_code == 200
    appointment = command(
        s,
        body={
            "line_id": s.catalog.line,
            "service_ids": [s.catalog.service, product],
            "employee_id": s.catalog.employee,
            "starts_at": s.at(540).isoformat(),
        },
    ).json()
    assert pay(s, "/mock-account").status_code == 200
    payment = pay(s, body={"appointment_id": appointment["id"]}).json()
    receipt = finish(s, payment)["transactions"][0]
    with m.lab.runtime.database.transaction(m.lab.tenant, read_only=True) as session:
        items = session.scalars(
            select(AppointmentItem)
            .where(AppointmentItem.appointment_id == UUID(appointment["id"]))
            .order_by(AppointmentItem.position)
        ).all()
        item_ids = [str(i.service_id) for i in items]
        first_amount = items[0].amount
    credit = billing.credit
    for day, amount in ((1, 4), (2, 5), (3, 3)):
        when = datetime(2026, 1, day, 12, tzinfo=UTC)

        def historical_credit(session: Session, refund: Refund, at: datetime = when) -> None:
            credit(session, refund)
            for item in session.new:
                if isinstance(item, FinancialEntry):
                    item.booked_at = at

        monkeypatch.setattr(billing, "credit", historical_credit)
        refund = pay(
            s, f"/transactions/{receipt['id']}/refunds", {"amount": amount, "reason": f"Part {day}"}
        ).json()
        assert pay(s, f"/refunds/{refund['id']}/approve").json()["status"] == "SUCCEEDED"
    all_parts = query(s, "breakdown", dimension="service", start="2026-01-01", end="2026-01-03")[
        "items"
    ]
    assert sum(int(r["refunded"]) for r in all_parts) == 12
    refunded = {r["id"]: int(r["refunded"]) for r in all_parts}
    assert refunded[item_ids[0]] == first_amount and refunded[item_ids[1]] == 12 - first_amount
    second = query(s, "breakdown", dimension="service", start="2026-01-02", end="2026-01-02")[
        "items"
    ]
    assert sum(int(r["refunded"]) for r in second) == 5
    assert {r["id"]: int(r["refunded"]) for r in second}[item_ids[0]] == min(first_amount, 9) - min(
        first_amount, 4
    )


def test_finance_only_custom_role_can_enter_workspace(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    person = new_user(m, "09125550124")
    role = mutate(
        m,
        "POST",
        "/roles",
        {"name": "Financial reader", "code": "financial_reader", "permissions": ["finance.read"]},
    )
    assert role.status_code == 201, role.text
    assert assign(m, person, role.json()["id"], line=UUID(s.catalog.line)).status_code == 201
    with TestClient(m.lab.app, base_url=m.lab.origin) as browser:
        sign_in(m, browser, "09125550124")
        result = browser.get("/api/v1/dashboard/context")
        assert result.status_code == 200, result.text
        assert [line["id"] for line in result.json()["lines"]] == [s.catalog.line]
        today = result.json()["today"]
        assert browser.get(f"/api/v1/finance/report?start={today}&end={today}").status_code == 200


def test_exact_aggregate_serialization_beyond_javascript_integer_limit() -> None:
    from app.modules.finance.service import totals

    values = totals(9007199254740993, 2, 9007199254740992, 1)
    assert values.received == "9007199254740993" and values.net == "9007199254740991"
    assert values.unallocated_net == "0"
