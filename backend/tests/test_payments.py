from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from time import sleep
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.appointments import domain
from app.modules.appointments.models import Appointment, AppointmentHistory
from app.modules.billing.models import CreditNote, FinancialEntry, Invoice, Receipt
from app.modules.payments.mock import MockPaymentProvider
from app.modules.payments.models import (
    CallbackEvent,
    MockOrder,
    MockRefund,
    PaymentAllocation,
    PaymentAttempt,
    PaymentTransaction,
    Refund,
)
from app.modules.payments.processing import PaymentProcessor
from app.modules.payments.providers import Order, ProviderUnavailable, RefundResult, Verification
from app.modules.payments.worker import PaymentWorker
from tests.test_appointments import command, create, expire_in_db, free
from tests.test_authentication import auth_lab as auth_lab
from tests.test_catalog_workforce import catalog as catalog
from tests.test_scheduling import Schedule
from tests.test_scheduling import schedule as schedule
from tests.test_tenant_management import manager as manager
from tests.test_tenant_management import new_user, sign_in

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def mock_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALONBOOK_MOCK_PAYMENTS_ENABLED", "true")


def pay(
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
        f"/api/v1/payments{path}",
        json=body or {},
        headers={
            "Origin": str(browser.base_url).rstrip("/"),
            "X-CSRF-Token": csrf or m.csrf,
            "Idempotency-Key": key or uuid4().hex,
        },
    )


def started(s: Schedule) -> tuple[dict[str, Any], dict[str, Any]]:
    enabled = pay(s, "/mock-account")
    assert enabled.status_code == 200, enabled.text
    appointment = create(s)
    assert appointment.status_code == 201, appointment.text
    payment = pay(s, body={"appointment_id": appointment.json()["id"]})
    assert payment.status_code == 201, payment.text
    assert payment.json()["status"] == "PENDING"
    return appointment.json(), payment.json()


def finish(s: Schedule, payment: dict[str, Any], scenario: str = "success") -> dict[str, Any]:
    result = pay(s, f"/{payment['id']}/mock-checkout", {"scenario": scenario})
    assert result.status_code == 200, result.text
    body: dict[str, Any] = result.json()
    return body


def processor(s: Schedule) -> PaymentProcessor:
    lab = s.catalog.manager.lab
    return PaymentProcessor(lab.runtime.database, lab.auth.sessions.settings)


def due(s: Schedule) -> None:
    lab = s.catalog.manager.lab
    with lab.runtime.database.transaction(lab.tenant) as session:
        session.execute(
            update(PaymentAttempt).values(next_check_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        session.execute(
            update(Refund).values(next_check_at=datetime.now(UTC) - timedelta(seconds=1))
        )


def test_verified_payment_confirms_once_and_issues_immutable_documents(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    appointment, payment = started(s)
    result = finish(s, payment)
    assert result["status"] == "SUCCEEDED" and result["appointment_status"] == "CONFIRMED"
    assert result["is_test"] and result["transactions"][0]["allocated"]
    assert finish(s, payment) == result
    assert pay(s, f"/{payment['id']}/verify").json() == result
    invoice = lab.client.get(f"/api/v1/payments/invoices/{appointment['id']}")
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["total_amount"] == 1_000_000
    assert invoice.json()["number"].startswith("TEST-")
    assert sum(item["amount"] for item in invoice.json()["items"]) == 1_000_000
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        for model in (PaymentTransaction, PaymentAllocation, Receipt, Invoice, FinancialEntry):
            assert session.scalar(select(func.count()).select_from(model)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AppointmentHistory)
                .where(AppointmentHistory.action == "confirmed")
            )
            == 1
        )


def test_payment_keys_hold_snapshot_and_negative_attempt_retry(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    assert pay(s, "/mock-account").status_code == 200
    appointment = create(s).json()
    key = uuid4().hex
    body = {"appointment_id": appointment["id"]}
    first = pay(s, body=body, key=key)
    assert first.status_code == 201, first.text
    assert pay(s, body=body, key=key).json()["id"] == first.json()["id"]
    assert pay(s, body=body).status_code == 409
    assert pay(s, body={**body, "amount": 1}).status_code == 422
    failed = finish(s, first.json(), "failure")
    assert failed["status"] == "FAILED" and not failed["transactions"]
    second = pay(s, body=body)
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first.json()["id"]
    assert second.json()["expires_at"] == first.json()["expires_at"]
    # Inquiry into an older failed attempt cannot collide with or replace the new open one.
    assert pay(s, f"/{first.json()['id']}/verify").json()["status"] == "FAILED"
    assert finish(s, second.json())["appointment_status"] == "CONFIRMED"
    another = create(s, 600).json()
    assert (
        pay(s, body={"appointment_id": another["id"]}, key=key).json()["error"]["code"]
        == "idempotency_conflict"
    )
    assert (
        lab.client.get(f"/api/v1/payments?appointment_id={appointment['id']}").json()[1]["status"]
        == "SUCCEEDED"
    )


@pytest.mark.parametrize("scenario", ["timeout", "cancel", "amount_mismatch"])
def test_mock_outcomes_are_verified_and_unknown_is_reconciled(
    schedule: Schedule, scenario: str
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    appointment, payment = started(s)
    result = finish(s, payment, scenario)
    if scenario == "timeout":
        assert result["status"] == "RECONCILIATION_REQUIRED"
        assert result["appointment_status"] == "AWAITING_PAYMENT" and not result["transactions"]
        assert pay(s, body={"appointment_id": appointment["id"]}).status_code == 409
        due(s)
        PaymentWorker(processor(s)).batch(lab.tenant)
        assert (
            lab.client.get(f"/api/v1/payments/{payment['id']}").json()["appointment_status"]
            == "CONFIRMED"
        )
    elif scenario == "cancel":
        assert result["status"] == "CANCELLED" and not result["transactions"]
    else:
        assert result["appointment_status"] == "AWAITING_PAYMENT"
        transaction = result["transactions"][0]
        assert transaction["amount"] == 1_000_001 and not transaction["allocated"]
        PaymentWorker(processor(s)).batch(lab.tenant)
        refund = lab.client.get(
            f"/api/v1/payments/refunds/{transaction['refunds'][0]['id']}"
        ).json()
        assert refund["status"] == "SUCCEEDED" and refund["amount"] == 1_000_001


@pytest.mark.parametrize("cancelled", [False, True])
def test_late_receipt_is_preserved_refunded_and_never_resurrects_booking(
    schedule: Schedule, cancelled: bool
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    appointment, payment = started(s)
    if cancelled:
        assert (
            command(
                s,
                f"/{appointment['id']}/cancel",
                {"expected_version": 1, "reason": "Changed plans"},
            ).status_code
            == 200
        )
    else:
        expire_in_db(s, appointment["id"])
    result = finish(s, payment)
    assert result["appointment_status"] == ("CANCELLED" if cancelled else "EXPIRED")
    assert not result["transactions"][0]["allocated"]
    PaymentWorker(processor(s)).batch(lab.tenant)
    current = lab.client.get(f"/api/v1/payments/{payment['id']}").json()
    assert current["transactions"][0]["refunds"][0]["status"] == "SUCCEEDED"
    assert lab.client.get(f"/api/v1/payments/invoices/{appointment['id']}").status_code == 404


def test_callback_is_only_a_deduplicated_wakeup_and_cross_tenant_hidden(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    appointment, payment = started(s)
    with TestClient(lab.app, base_url=lab.origin) as anonymous:
        for _ in range(3):
            assert (
                anonymous.post(
                    f"/api/v1/payments/{payment['id']}/callback?success=true",
                    json={"status": "SUCCEEDED"},
                ).status_code
                == 202
            )
        assert anonymous.get(f"/api/v1/payments/{payment['id']}").status_code == 401
        assert (
            anonymous.post(
                f"/api/v1/payments/{payment['id']}/mock-checkout", json={"scenario": "success"}
            ).status_code
            == 403
        )
    PaymentWorker(processor(s)).batch(lab.tenant)
    assert (
        lab.client.get(f"/api/v1/appointments/{appointment['id']}").json()["status"]
        == "AWAITING_PAYMENT"
    )
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert session.scalar(select(func.count()).select_from(CallbackEvent)) == 1
        assert session.scalar(select(func.count()).select_from(PaymentTransaction)) == 0
    with TestClient(lab.app, base_url=lab.other_origin) as other:
        assert other.post(f"/api/v1/payments/{payment['id']}/callback").status_code == 404
    # A return without login can still schedule a successful server-side inquiry.
    p = processor(s)
    order, provider = p.snapshot(lab.tenant, UUID(payment["id"]))
    assert isinstance(provider, MockPaymentProvider)
    provider.simulate(order, "success")
    lab.client.post(f"/api/v1/payments/{payment['id']}/callback")
    PaymentWorker(processor(s)).batch(lab.tenant)
    assert (
        lab.client.get(f"/api/v1/appointments/{appointment['id']}").json()["status"] == "CONFIRMED"
    )


def test_refund_reservations_idempotency_credit_note_and_ceiling(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    _, payment = started(s)
    transaction = finish(s, payment)["transactions"][0]
    path = f"/transactions/{transaction['id']}/refunds"
    key = uuid4().hex
    request = {"amount": 600_000, "reason": "Service adjustment"}
    first = pay(s, path, request, key=key)
    assert first.status_code == 201, first.text
    refund = first.json()
    assert refund["status"] == "REQUESTED"
    assert pay(s, path, request, key=key).json() == refund
    assert pay(s, path, {**request, "amount": 1}, key=key).status_code == 409
    assert pay(s, path, request).json()["error"]["code"] == "refund_exceeds_balance"
    assert pay(s, path, {**request, "amount": 1.5}).status_code == 422
    approved = pay(s, f"/refunds/{refund['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "SUCCEEDED"
    assert pay(s, f"/refunds/{refund['id']}/approve").json() == approved.json()
    assert pay(s, f"/refunds/{refund['id']}/cancel").status_code == 409
    credit = lab.client.get(f"/api/v1/payments/refunds/{refund['id']}/credit-note")
    assert credit.status_code == 200 and credit.json()["number"].startswith("TEST-")
    rest = pay(s, path, {"amount": 400_000, "reason": "Rest"}).json()
    assert pay(s, f"/refunds/{rest['id']}/cancel").json()["status"] == "CANCELLED"
    assert pay(s, path, {"amount": 400_001, "reason": "Too much"}).status_code == 409
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert (
            session.scalar(
                select(func.sum(FinancialEntry.amount)).where(FinancialEntry.kind == "REFUND")
            )
            == 600_000
        )
        assert session.scalar(select(func.count()).select_from(CreditNote)) == 1
        assert session.scalar(select(func.count()).select_from(MockRefund)) == 1


def test_cancellation_worker_refunds_verified_receipt(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    appointment, payment = started(s)
    finish(s, payment)
    assert (
        command(
            s,
            f"/{appointment['id']}/cancel",
            {"expected_version": 2, "reason": "Customer cancellation"},
        ).status_code
        == 200
    )
    worker = PaymentWorker(processor(s))
    worker.batch(lab.tenant)
    worker.batch(lab.tenant)
    result = lab.client.get(f"/api/v1/payments/{payment['id']}").json()
    assert result["transactions"][0]["refunds"][0]["status"] == "SUCCEEDED"
    assert len(result["transactions"][0]["refunds"]) == 1


def test_simultaneous_verify_has_one_financial_effect(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    _, payment = started(s)
    p = processor(s)
    order, provider = p.snapshot(lab.tenant, UUID(payment["id"]))
    assert isinstance(provider, MockPaymentProvider)
    provider.simulate(order, "success")
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda _: processor(s).reconcile(lab.tenant, UUID(payment["id"])), range(8)
            )
        )
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert session.scalar(select(func.count()).select_from(PaymentTransaction)) == 1
        assert session.scalar(select(func.count()).select_from(Receipt)) == 1
        assert session.scalar(select(func.count()).select_from(PaymentAllocation)) == 1


def test_disabled_mock_and_other_customer_permissions(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, m = schedule, schedule.catalog.manager
    lab = m.lab
    monkeypatch.setattr(
        lab.auth.sessions,
        "settings",
        lab.auth.sessions.settings.model_copy(update={"mock_payments_enabled": False}),
    )
    assert pay(s, "/mock-account").status_code == 503
    monkeypatch.setattr(
        lab.auth.sessions,
        "settings",
        lab.auth.sessions.settings.model_copy(update={"mock_payments_enabled": True}),
    )
    _, payment = started(s)
    user = new_user(m, phone="09129998877")
    with TestClient(lab.app, base_url=lab.origin) as browser:
        csrf = sign_in(m, browser, phone="09129998877")
        assert browser.get(f"/api/v1/payments/{payment['id']}").status_code == 403
        assert (
            pay(
                s,
                f"/{payment['id']}/mock-checkout",
                {"scenario": "success"},
                client=browser,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert pay(s, "/mock-account", client=browser, csrf=csrf).status_code == 403
    assert user["id"]


def test_free_booking_issues_zero_invoice_without_payment(schedule: Schedule) -> None:
    free(schedule)
    appointment = create(schedule).json()
    invoice = schedule.catalog.manager.lab.client.get(
        f"/api/v1/payments/invoices/{appointment['id']}"
    )
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["total_amount"] == 0
    assert pay(schedule, body={"appointment_id": appointment["id"]}).status_code == 409


def test_create_timeout_after_gateway_commit_recovers_same_order(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    original = MockPaymentProvider.create

    def interrupted(provider: MockPaymentProvider, order: Order) -> str:
        original(provider, order)
        raise ProviderUnavailable()

    monkeypatch.setattr(MockPaymentProvider, "create", interrupted)
    pay(s, "/mock-account")
    appointment = create(s).json()
    key = uuid4().hex
    result = pay(s, body={"appointment_id": appointment["id"]}, key=key)
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "RECONCILIATION_REQUIRED"
    monkeypatch.setattr(MockPaymentProvider, "create", original)
    resumed = pay(s, body={"appointment_id": appointment["id"]}, key=key)
    assert resumed.json()["id"] == result.json()["id"] and resumed.json()["status"] == "PENDING"
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert session.scalar(select(func.count()).select_from(MockOrder)) == 1
        assert session.scalar(select(func.count()).select_from(PaymentAttempt)) == 1


def test_gateway_success_survives_crash_before_application_commit(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    _, payment = started(s)
    p = processor(s)
    order, provider = p.snapshot(lab.tenant, UUID(payment["id"]))
    assert isinstance(provider, MockPaymentProvider)
    provider.simulate(order, "success")
    original = PaymentProcessor.apply

    def interrupted(
        self: PaymentProcessor, tenant: UUID, identifier: UUID, result: Verification
    ) -> None:
        raise RuntimeError("Injected crash before local settlement")

    monkeypatch.setattr(PaymentProcessor, "apply", interrupted)
    with pytest.raises(RuntimeError, match="Injected crash"):
        p.reconcile(lab.tenant, UUID(payment["id"]))
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert session.scalar(select(func.count()).select_from(PaymentTransaction)) == 0
        assert session.scalar(select(PaymentAttempt.status)) == "VERIFYING"
    monkeypatch.setattr(PaymentProcessor, "apply", original)
    due(s)
    PaymentWorker(processor(s)).batch(lab.tenant)
    assert (
        lab.client.get(f"/api/v1/payments/{payment['id']}").json()["appointment_status"]
        == "CONFIRMED"
    )


def test_unknown_refund_reserves_money_and_recovers_without_second_transfer(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    _, payment = started(s)
    transaction = finish(s, payment)["transactions"][0]
    path = f"/transactions/{transaction['id']}/refunds"
    refund = pay(s, path, {"amount": 1_000_000, "reason": "All"}).json()
    original = MockPaymentProvider.refund

    def interrupted(
        self: MockPaymentProvider, order: Order, transaction_id: str, key: str, amount: int
    ) -> RefundResult:
        original(self, order, transaction_id, key, amount)
        raise ProviderUnavailable()

    monkeypatch.setattr(MockPaymentProvider, "refund", interrupted)
    response = pay(s, f"/refunds/{refund['id']}/approve")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "RECONCILIATION_REQUIRED"
    assert pay(s, path, {"amount": 1, "reason": "Too much"}).status_code == 409
    due(s)
    PaymentWorker(processor(s)).batch(lab.tenant)
    assert (
        lab.client.get(f"/api/v1/payments/refunds/{refund['id']}").json()["status"] == "SUCCEEDED"
    )
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert session.scalar(select(func.count()).select_from(MockRefund)) == 1
        assert session.scalar(select(func.count()).select_from(CreditNote)) == 1


def test_wrong_merchant_or_order_is_never_financial_evidence(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    _, payment = started(s)
    original = MockPaymentProvider.verify

    def wrong(self: MockPaymentProvider, order: Order, gateway_order_id: str) -> Verification:
        return Verification(
            "SUCCEEDED",
            "another merchant",
            "another-order",
            order.amount,
            "IRR",
            "invalid-transaction",
            datetime.now(UTC),
        )

    monkeypatch.setattr(MockPaymentProvider, "verify", wrong)
    result = pay(s, f"/{payment['id']}/verify")
    assert result.json()["status"] == "RECONCILIATION_REQUIRED"
    assert result.json()["failure_code"] == "provider_identity_mismatch"
    assert not result.json()["transactions"]
    monkeypatch.setattr(MockPaymentProvider, "verify", original)
    assert finish(s, payment)["appointment_status"] == "CONFIRMED"
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert session.scalar(select(func.count()).select_from(PaymentTransaction)) == 1


def test_actual_second_receipt_is_kept_and_refunded(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    appointment, first = started(s)
    original = MockPaymentProvider.verify

    def negative(self: MockPaymentProvider, order: Order, gateway_order_id: str) -> Verification:
        return Verification(
            "FAILED", order.merchant, gateway_order_id, order.amount, order.currency
        )

    monkeypatch.setattr(MockPaymentProvider, "verify", negative)
    assert pay(s, f"/{first['id']}/verify").json()["status"] == "FAILED"
    monkeypatch.setattr(MockPaymentProvider, "verify", original)
    second = pay(s, body={"appointment_id": appointment["id"]}).json()
    finish(s, second)
    # An older order settles late after the retry has already settled the appointment.
    result = finish(s, first)
    assert result["appointment_status"] == "CONFIRMED"
    assert not result["transactions"][0]["allocated"]
    PaymentWorker(processor(s)).batch(lab.tenant)
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert session.scalar(select(func.count()).select_from(PaymentTransaction)) == 2
        assert session.scalar(select(func.count()).select_from(PaymentAllocation)) == 1
        assert session.scalar(select(func.count()).select_from(Receipt)) == 2
        assert session.scalar(select(func.count()).select_from(Invoice)) == 1
        assert (
            session.scalar(
                select(func.sum(FinancialEntry.amount)).where(FinancialEntry.kind == "REFUND")
            )
            == 1_000_000
        )


def test_simultaneous_refund_requests_cannot_overreserve(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    _, payment = started(s)
    transaction = finish(s, payment)["transactions"][0]
    path = f"/transactions/{transaction['id']}/refunds"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: pay(s, path, {"amount": 600_000, "reason": "Concurrent adjustment"}),
                range(2),
            )
        )
    assert sorted(response.status_code for response in results) == [201, 409]
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert session.scalar(select(func.sum(Refund.amount))) == 600_000


def test_provider_calls_hold_no_application_transaction(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    original_create, original_verify, original_refund = (
        MockPaymentProvider.create,
        MockPaymentProvider.verify,
        MockPaymentProvider.refund,
    )
    calls = []

    def checked_create(self: MockPaymentProvider, order: Order) -> str:
        assert lab.runtime.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        calls.append("create")
        return original_create(self, order)

    def checked_verify(
        self: MockPaymentProvider, order: Order, gateway_order_id: str
    ) -> Verification:
        assert lab.runtime.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        calls.append("verify")
        return original_verify(self, order, gateway_order_id)

    def checked_refund(
        self: MockPaymentProvider, order: Order, transaction_id: str, key: str, amount: int
    ) -> RefundResult:
        assert lab.runtime.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        calls.append("refund")
        return original_refund(self, order, transaction_id, key, amount)

    monkeypatch.setattr(MockPaymentProvider, "create", checked_create)
    monkeypatch.setattr(MockPaymentProvider, "verify", checked_verify)
    monkeypatch.setattr(MockPaymentProvider, "refund", checked_refund)
    _, payment = started(s)
    transaction = finish(s, payment)["transactions"][0]
    refund = pay(
        s, f"/transactions/{transaction['id']}/refunds", {"amount": 1_000_000, "reason": "Test"}
    ).json()
    assert pay(s, f"/refunds/{refund['id']}/approve").json()["status"] == "SUCCEEDED"
    assert set(calls) == {"create", "verify", "refund"}


def test_deadline_crossed_during_confirmation_keeps_receipt_and_refund(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    appointment, payment = started(s)
    original = domain.confirm_verified

    def delayed(
        session: Session, row: Appointment, actor: UUID | None, *, request_id: UUID | None = None
    ) -> None:
        sleep(0.5)
        original(session, row, actor, request_id=request_id)

    monkeypatch.setattr(domain, "confirm_verified", delayed)
    with lab.runtime.database.transaction(lab.tenant) as session:
        session.execute(
            update(Appointment)
            .where(Appointment.id == UUID(appointment["id"]))
            .values(hold_expires_at=datetime.now(UTC) + timedelta(seconds=0.4))
        )
    result = finish(s, payment)
    assert result["appointment_status"] == "EXPIRED"
    assert len(result["transactions"]) == 1
    assert not result["transactions"][0]["allocated"]
    assert result["transactions"][0]["refunds"][0]["status"] == "APPROVED"


def test_released_manual_reservation_after_cancellation_is_also_refunded(
    schedule: Schedule,
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    appointment, payment = started(s)
    transaction = finish(s, payment)["transactions"][0]
    requested = pay(
        s,
        f"/transactions/{transaction['id']}/refunds",
        {"amount": 400_000, "reason": "Partial request"},
    ).json()
    command(s, f"/{appointment['id']}/cancel", {"expected_version": 2, "reason": "Cancelled"})
    worker = PaymentWorker(processor(s))
    worker.batch(lab.tenant)
    assert pay(s, f"/refunds/{requested['id']}/cancel").status_code == 200
    worker.batch(lab.tenant)
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert (
            session.scalar(
                select(func.sum(FinancialEntry.amount)).where(FinancialEntry.kind == "REFUND")
            )
            == 1_000_000
        )


def test_simulator_rows_are_tenant_isolated(schedule: Schedule) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    _, payment = started(s)
    transaction = finish(s, payment)["transactions"][0]
    requested = pay(
        s, f"/transactions/{transaction['id']}/refunds", {"amount": 100, "reason": "Test"}
    ).json()
    assert pay(s, f"/refunds/{requested['id']}/approve").status_code == 200
    with lab.runtime.database.transaction(lab.other_tenant, read_only=True) as session:
        for model in (
            MockOrder,
            MockRefund,
            PaymentTransaction,
            Refund,
            Invoice,
            Receipt,
            CreditNote,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_live_mode_cannot_use_mock_account(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    assert pay(s, "/mock-account").status_code == 200
    monkeypatch.setattr(
        lab.auth.sessions,
        "settings",
        lab.auth.sessions.settings.model_copy(update={"payments_mode": "live"}),
    )
    appointment = create(s).json()
    assert appointment["is_test"] is False
    assert (
        pay(s, body={"appointment_id": appointment["id"]}).json()["error"]["code"]
        == "payment_unavailable"
    )


def test_wrong_refund_verification_keeps_balance_reserved(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, lab = schedule, schedule.catalog.manager.lab
    _, payment = started(s)
    transaction = finish(s, payment)["transactions"][0]
    path = f"/transactions/{transaction['id']}/refunds"
    refund = pay(s, path, {"amount": 1_000_000, "reason": "Test"}).json()

    def wrong(self: MockPaymentProvider, order: Order, key: str) -> RefundResult:
        return RefundResult(
            "SUCCEEDED", "wrong-refund", "other merchant", "wrong-transaction", 1, "IRR"
        )

    monkeypatch.setattr(MockPaymentProvider, "refund_status", wrong)
    assert pay(s, f"/refunds/{refund['id']}/approve").json()["status"] == "RECONCILIATION_REQUIRED"
    assert pay(s, path, {"amount": 1, "reason": "More"}).status_code == 409
    with lab.runtime.database.transaction(lab.tenant, read_only=True) as session:
        assert session.scalar(select(func.count()).select_from(CreditNote)) == 0
