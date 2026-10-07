from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.base import JsonObject
from app.db.enums import RefundStatus
from app.modules.access.service import Principal
from app.modules.appointments import domain
from app.modules.appointments.models import Appointment
from app.modules.appointments.service import allowed
from app.modules.catalog.common import missing
from app.modules.identity.models import CustomerProfile
from app.modules.operations.models import AuditLog, OutboxEvent
from app.modules.payments.models import (
    PaymentAccount,
    PaymentAttempt,
    PaymentIntent,
    PaymentTransaction,
    Refund,
)
from app.modules.payments.providers import Order


def appointment(session: Session, identifier: UUID, *, lock: bool = False) -> Appointment:
    row = session.scalar(select(Appointment).where(Appointment.id == identifier))
    if row is None:
        raise missing()
    if lock:
        domain.customer_lock(session, row.customer_id)
        session.refresh(row)
        domain.employee_locks(session, {row.employee_id})
        session.refresh(row, with_for_update=True)
    return row


def financial_access(
    session: Session, principal: Principal, row: Appointment, *, pay: bool = False
) -> None:
    owner = session.scalar(
        select(CustomerProfile.user_id).where(CustomerProfile.id == row.customer_id)
    )
    if allowed(principal, "appointment.read_own", row, owner=owner):
        return
    if allowed(principal, "finance.read", row) and (
        not pay or allowed(principal, "appointment.manage", row)
    ):
        return
    raise AppError("forbidden", "Access denied.", 403)


def attempt(session: Session, identifier: UUID) -> PaymentAttempt:
    row = session.scalar(select(PaymentAttempt).where(PaymentAttempt.id == identifier))
    if row is None:
        raise missing()
    return row


def intent(session: Session, row: PaymentAttempt) -> PaymentIntent:
    result = session.scalar(select(PaymentIntent).where(PaymentIntent.id == row.intent_id))
    assert result is not None
    return result


def order(session: Session, row: PaymentAttempt) -> tuple[Order, PaymentAccount]:
    account = session.scalar(select(PaymentAccount).where(PaymentAccount.id == row.account_id))
    assert account is not None
    request = Order(
        row.tenant_id,
        row.account_id,
        account.merchant_reference,
        str(row.id),
        row.amount,
        row.currency,
        intent(session, row).expires_at,
    )
    return request, account


def event(
    session: Session,
    tenant: UUID,
    kind: str,
    identifier: UUID,
    data: JsonObject,
    *,
    actor: UUID | None = None,
    reason: str | None = None,
) -> None:
    session.add_all(
        [
            AuditLog(
                tenant_id=tenant,
                actor_kind="USER" if actor else "SYSTEM",
                actor_id=actor,
                action=kind,
                entity_type="payment",
                entity_id=identifier,
                reason=reason,
                event_data=data,
            ),
            OutboxEvent(
                tenant_id=tenant,
                event_type=kind,
                aggregate_id=identifier,
                deduplication_key=f"{kind}:{identifier}",
                payload=data,
            ),
        ]
    )


def remaining(session: Session, transaction: PaymentTransaction) -> int:
    # Caller holds the parent appointment lock; unknown/refund requests reserve money.
    reserved = (
        session.scalar(
            select(func.coalesce(func.sum(Refund.amount), 0)).where(
                Refund.transaction_id == transaction.id,
                Refund.status.not_in([RefundStatus.FAILED, RefundStatus.CANCELLED]),
            )
        )
        or 0
    )
    # PostgreSQL SUM(bigint) returns exact numeric/Decimal; API and JSON money stays integer.
    return max(0, transaction.amount - int(reserved))


def automatic_refund(
    session: Session, transaction: PaymentTransaction, reason: str
) -> Refund | None:
    failed = session.scalar(
        select(Refund).where(
            Refund.transaction_id == transaction.id,
            Refund.request_key.like("auto:%"),
            Refund.status == RefundStatus.FAILED,
        )
    )
    if failed is not None:
        return failed  # Definitive failure requires operator review, never an automatic new key.
    amount = remaining(session, transaction)
    if amount == 0:
        return None
    count = session.scalar(
        select(func.count()).select_from(Refund).where(Refund.transaction_id == transaction.id)
    )
    key = f"auto:{transaction.id}:{count}"
    row = Refund(
        tenant_id=transaction.tenant_id,
        transaction_id=transaction.id,
        captured_amount=transaction.amount,
        amount=amount,
        currency=transaction.currency,
        is_test=transaction.is_test,
        status=RefundStatus.APPROVED,
        request_key=key,
        reason=reason,
        next_check_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    event(
        session,
        row.tenant_id,
        "refund.approved",
        row.id,
        {"amount": amount, "automatic": True},
        reason=reason,
    )
    return row
