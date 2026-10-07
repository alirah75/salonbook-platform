"""Durable payment/refund processing: prepare, external call, atomic application."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.database import Database
from app.db.enums import AppointmentStatus, PaymentStatus, RefundStatus
from app.modules.appointments import domain
from app.modules.appointments.models import Appointment
from app.modules.billing import service as billing
from app.modules.payments import common
from app.modules.payments.mock import MockPaymentProvider
from app.modules.payments.models import (
    PaymentAllocation,
    PaymentAttempt,
    PaymentIntent,
    PaymentTransaction,
    Refund,
)
from app.modules.payments.providers import (
    Order,
    PaymentProvider,
    ProviderUnavailable,
    RefundResult,
    Verification,
)
from app.modules.scheduling.coordination import lock_calendar
from app.modules.tenancy.locks import tenant_lock
from app.modules.tenancy.models import Salon

OPEN = (
    PaymentStatus.CREATED,
    PaymentStatus.PENDING,
    PaymentStatus.VERIFYING,
    PaymentStatus.RECONCILIATION_REQUIRED,
)
REFUND_OPEN = (RefundStatus.APPROVED, RefundStatus.PROCESSING, RefundStatus.RECONCILIATION_REQUIRED)


class PaymentProcessor:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database, self.settings = database, settings

    def provider(self, name: str, is_test: bool) -> PaymentProvider:
        if name != "mock" or not is_test or not self.settings.mock_payments_enabled:
            raise AppError("provider_unavailable", "The payment provider is not enabled.", 503)
        return MockPaymentProvider(self.database)

    @contextmanager
    def locked(
        self, tenant: UUID, identifier: UUID
    ) -> Iterator[tuple[Session, Appointment, PaymentIntent, PaymentAttempt]]:
        with self.database.transaction(tenant) as session:
            tenant_lock(session, tenant, "lifecycle", shared=True)
            lock_calendar(session, tenant, shared=True)
            row = common.attempt(session, identifier)
            intent = common.intent(session, row)
            appointment = common.appointment(session, intent.appointment_id, lock=True)
            session.refresh(intent, with_for_update=True)
            session.refresh(row, with_for_update=True)
            yield session, appointment, intent, row

    def snapshot(self, tenant: UUID, identifier: UUID) -> tuple[Order, PaymentProvider]:
        with self.database.transaction(tenant, read_only=True) as session:
            row = common.attempt(session, identifier)
            order, account = common.order(session, row)
            return order, self.provider(account.provider, account.is_test)

    def reconcile(self, tenant: UUID, identifier: UUID) -> None:
        order, provider = self.snapshot(tenant, identifier)
        with self.locked(tenant, identifier) as (session, appointment, intent, row):
            if row.status == PaymentStatus.SUCCEEDED:
                return
            gateway_id = row.gateway_order_id
            # Creating again uses a durable key, including recovery after an ambiguous create.
            if gateway_id is None and not provider.capabilities.idempotent_create:
                raise AppError("provider_contract", "Provider needs manual reconciliation.", 503)
            if row.status in OPEN:
                row.status = PaymentStatus.VERIFYING
            row.next_check_at = datetime.now(UTC) + timedelta(seconds=30)
        try:
            if gateway_id is None:
                gateway_id = provider.create(order)
            with self.locked(tenant, identifier) as (session, appointment, intent, row):
                if row.gateway_order_id is not None and row.gateway_order_id != gateway_id:
                    raise AppError("provider_order_conflict", "Provider order needs review.", 409)
                row.gateway_order_id = gateway_id
            result = provider.verify(order, gateway_id)
        except (ProviderUnavailable, TimeoutError, ConnectionError):
            result = Verification(
                "UNKNOWN", order.merchant, gateway_id or "", order.amount, order.currency
            )
        domain.retry(lambda: self.apply(tenant, identifier, result))

    def apply(self, tenant: UUID, identifier: UUID, result: Verification) -> None:
        with self.locked(tenant, identifier) as (session, appointment, intent, row):
            if row.status == PaymentStatus.SUCCEEDED:
                return
            order, _ = common.order(session, row)
            now = datetime.now(UTC)
            was_open = row.status in OPEN
            row.next_check_at = now + timedelta(seconds=30)
            # Merchant/currency/order mismatch cannot be accepted as our financial evidence.
            matched = (
                result.merchant == order.merchant
                and result.currency == order.currency
                and bool(result.order_id)
                and len(result.order_id) <= 180
                and (row.gateway_order_id is None or result.order_id == row.gateway_order_id)
            )
            if not matched or result.outcome == "UNKNOWN":
                if was_open:
                    row.status = PaymentStatus.RECONCILIATION_REQUIRED
                row.failure_code = (
                    "provider_identity_mismatch"
                    if not matched and result.outcome != "UNKNOWN"
                    else "unknown_outcome"
                )
                if matched:
                    row.gateway_order_id = result.order_id
                if was_open and intent.status != PaymentStatus.SUCCEEDED:
                    intent.status = row.status
                return
            row.gateway_order_id = result.order_id
            row.failure_code = None
            if result.outcome != "SUCCEEDED":
                if was_open:
                    row.status = PaymentStatus(result.outcome)
                if was_open and intent.status != PaymentStatus.SUCCEEDED:
                    intent.status = row.status
                # Final negative outcomes get a bounded late-receipt surveillance window.
                if result.outcome != "PENDING" and now > intent.expires_at + timedelta(days=7):
                    row.next_check_at = None
                return
            if (
                not result.transaction_id
                or len(result.transaction_id) > 180
                or type(result.amount) is not int
                or result.amount <= 0
                or result.amount > 2**63 - 1
                or result.received_at is None
                or result.received_at.tzinfo is None
                or result.received_at > now + timedelta(minutes=5)
            ):
                if was_open:
                    row.status = PaymentStatus.RECONCILIATION_REQUIRED
                row.failure_code = "invalid_verified_receipt"
                return
            existing = session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.account_id == row.account_id,
                    PaymentTransaction.gateway_transaction_id == result.transaction_id,
                )
            )
            if existing is not None:
                # An ID attached to a different order is a provider contract violation.
                if was_open:
                    row.status = PaymentStatus.RECONCILIATION_REQUIRED
                row.failure_code = "transaction_identity_conflict"
                return
            transaction = PaymentTransaction(
                tenant_id=tenant,
                attempt_id=row.id,
                intent_id=intent.id,
                account_id=row.account_id,
                amount=result.amount,
                currency=result.currency,
                is_test=row.is_test,
                gateway_transaction_id=result.transaction_id,
                received_at=result.received_at,
                verified_at=now,
                evidence={
                    "provider_verified": True,
                    "merchant": result.merchant,
                    "order_id": result.order_id,
                },
            )
            session.add(transaction)
            session.flush()
            billing.capture(session, transaction)
            row.status, row.verified_at, row.next_check_at = PaymentStatus.SUCCEEDED, now, None
            common.event(
                session,
                tenant,
                "payment.received",
                transaction.id,
                {
                    "amount": transaction.amount,
                    "is_test": transaction.is_test,
                    "appointment_id": str(appointment.id),
                },
            )
            session.flush()
            domain.expire(session, appointment, datetime.now(UTC))
            live = (
                appointment.status == AppointmentStatus.AWAITING_PAYMENT
                and appointment.hold_expires_at is not None
                and appointment.hold_expires_at > datetime.now(UTC)
                and session.scalar(select(Salon.status).where(Salon.id == tenant)) == "ACTIVE"
            )
            allocated = session.scalar(
                select(PaymentAllocation.id).where(PaymentAllocation.intent_id == intent.id)
            )
            applied = False
            if live and allocated is None and transaction.amount == intent.amount:
                try:
                    with session.begin_nested():
                        intent.status = PaymentStatus.SUCCEEDED
                        session.add(
                            PaymentAllocation(
                                tenant_id=tenant,
                                intent_id=intent.id,
                                transaction_id=transaction.id,
                                amount=transaction.amount,
                                currency=transaction.currency,
                                is_test=transaction.is_test,
                            )
                        )
                        session.flush()
                        domain.confirm_verified(session, appointment, None)
                        billing.invoice(session, appointment)
                        session.flush()
                    applied = True
                except domain.ExpiredHold:
                    domain.expire(session, appointment, datetime.now(UTC))
            if not applied:
                if intent.status != PaymentStatus.SUCCEEDED:
                    intent.status = PaymentStatus.RECONCILIATION_REQUIRED
                common.automatic_refund(
                    session,
                    transaction,
                    "Unallocated receipt: expired, cancelled, duplicate or amount mismatch",
                )
            session.flush()

    def refund(self, tenant: UUID, identifier: UUID) -> None:
        with self.database.transaction(tenant, read_only=True) as session:
            refund = session.scalar(select(Refund).where(Refund.id == identifier))
            if refund is None:
                return
            transaction = session.scalar(
                select(PaymentTransaction).where(PaymentTransaction.id == refund.transaction_id)
            )
            assert transaction is not None
            attempt_id = transaction.attempt_id
        order, provider = self.snapshot(tenant, attempt_id)
        with self.locked(tenant, attempt_id) as (session, appointment, intent, attempt):
            transaction = session.scalar(
                select(PaymentTransaction).where(PaymentTransaction.id == transaction.id)
            )
            refund = session.scalar(select(Refund).where(Refund.id == identifier).with_for_update())
            assert transaction is not None and refund is not None
            if refund.status not in REFUND_OPEN:
                return
            if not provider.capabilities.refunds or not provider.capabilities.idempotent_refund:
                refund.status = RefundStatus.RECONCILIATION_REQUIRED
                refund.next_check_at = datetime.now(UTC) + timedelta(hours=1)
                return
            refund.status = RefundStatus.PROCESSING
            refund.next_check_at = datetime.now(UTC) + timedelta(seconds=30)
            transaction_id, amount, key = (
                transaction.gateway_transaction_id,
                refund.amount,
                str(refund.id),
            )
        try:
            result = provider.refund_status(order, key)
            if result.outcome == "PENDING":
                result = provider.refund(order, transaction_id, key, amount)
        except (ProviderUnavailable, TimeoutError, ConnectionError):
            result = RefundResult("UNKNOWN")
        with self.locked(tenant, attempt_id) as (session, appointment, intent, attempt):
            refund = session.scalar(select(Refund).where(Refund.id == identifier).with_for_update())
            assert refund is not None
            if refund.status == RefundStatus.SUCCEEDED:
                return
            if (
                refund.status in {RefundStatus.FAILED, RefundStatus.CANCELLED}
                and result.outcome != "SUCCEEDED"
            ):
                return
            if (
                result.outcome == "SUCCEEDED"
                and result.refund_id
                and len(result.refund_id) <= 180
                and result.merchant == order.merchant
                and result.transaction_id == transaction_id
                and type(result.amount) is int
                and result.amount == amount
                and result.currency == order.currency
            ):
                refund.status, refund.succeeded_at = RefundStatus.SUCCEEDED, datetime.now(UTC)
                refund.gateway_refund_id, refund.next_check_at = result.refund_id, None
                billing.credit(session, refund)
                common.event(
                    session,
                    tenant,
                    "refund.succeeded",
                    refund.id,
                    {"amount": refund.amount, "is_test": refund.is_test},
                )
            elif result.outcome in {"FAILED", "CANCELLED"}:
                refund.status, refund.next_check_at = RefundStatus.FAILED, None
                common.event(session, tenant, "refund.failed", refund.id, {"amount": refund.amount})
            else:
                refund.status = RefundStatus.RECONCILIATION_REQUIRED
                refund.next_check_at = datetime.now(UTC) + timedelta(seconds=30)
            session.flush()

    def cancel_review(self, tenant: UUID, identifier: UUID) -> None:
        with self.locked(tenant, identifier) as (session, appointment, intent, attempt):
            if appointment.status != AppointmentStatus.CANCELLED:
                return
            for transaction in session.scalars(
                select(PaymentTransaction).where(PaymentTransaction.attempt_id == attempt.id)
            ):
                common.automatic_refund(
                    session,
                    transaction,
                    "Appointment cancelled under the saved cancellation policy",
                )
