"""Booking locks and state changes shared by HTTP, expiry and future verified payments."""

from collections.abc import Callable
from datetime import UTC, datetime
from time import sleep
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.base import JsonObject
from app.db.enums import AppointmentStatus, PaymentStatus
from app.modules.appointments.models import Appointment, AppointmentHistory
from app.modules.identity.models import CustomerProfile
from app.modules.operations.models import AuditLog, OutboxEvent
from app.modules.payments.models import PaymentAllocation, PaymentIntent
from app.modules.workforce.models import EmployeeLine, EmployeeProfile


class ExpiredHold(AppError):
    """The expiry transition must commit together with this deliberate 409 result."""

    def __init__(self) -> None:
        super().__init__("hold_expired", "This hold has expired.", 409)


def retry[T](operation: Callable[[], T]) -> T:
    for attempt in range(3):
        try:
            return operation()
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) not in {"40001", "40P01", "55P03"}:
                raise
            if attempt == 2:
                raise AppError(
                    "booking_busy", "Booking is busy. Retry with the same idempotency key.", 503
                ) from None
            sleep(0.03 * (attempt + 1))
    raise AssertionError("Unreachable")


def customer_lock(session: Session, identifier: UUID) -> CustomerProfile:
    customer = session.scalar(
        select(CustomerProfile).where(CustomerProfile.id == identifier).with_for_update()
    )
    if customer is None:
        raise AppError("not_found", "Customer unavailable in this salon.", 404)
    return customer


def employee_locks(session: Session, identifiers: set[UUID]) -> None:
    # Stable employee rows protect intervals that have no appointment row yet.
    list(
        session.scalars(
            select(EmployeeProfile)
            .where(EmployeeProfile.id.in_(identifiers))
            .order_by(EmployeeProfile.id)
            .with_for_update()
        )
    )


def candidate_ids(session: Session, line_id: UUID, employee_id: UUID | None) -> set[UUID]:
    if employee_id is not None:
        return {employee_id}
    ids = set(
        session.scalars(
            select(EmployeeLine.employee_id)
            .where(
                EmployeeLine.line_id == line_id,
                EmployeeLine.is_active.is_(True),
                EmployeeLine.deleted_at.is_(None),
            )
            .order_by(EmployeeLine.employee_id)
            .limit(101)
        )
    )
    if len(ids) > 100:
        raise AppError("availability_limit", "Select a specific employee.", 422)
    return ids


def event(
    session: Session,
    row: Appointment,
    action: str,
    actor: UUID | None,
    reason: str | None = None,
    *,
    data: JsonObject | None = None,
    request_id: UUID | None = None,
) -> None:
    payload: JsonObject = {
        "appointment_id": str(row.id),
        "customer_id": str(row.customer_id),
        "line_id": str(row.line_id),
        "employee_id": str(row.employee_id),
        "status": row.status.value,
        "version": row.version,
        **(data or {}),
    }
    session.add_all(
        [
            AppointmentHistory(
                tenant_id=row.tenant_id,
                appointment_id=row.id,
                actor_id=actor,
                action=action,
                reason=reason,
                event_data=payload,
            ),
            AuditLog(
                tenant_id=row.tenant_id,
                actor_kind="USER" if actor else "SYSTEM",
                actor_id=actor,
                action=f"appointment.{action}",
                entity_type="appointment",
                entity_id=row.id,
                reason=reason,
                request_id=request_id,
                event_data=payload,
            ),
            OutboxEvent(
                tenant_id=row.tenant_id,
                event_type=f"appointment.{action}",
                aggregate_id=row.id,
                deduplication_key=f"appointment:{row.id}:{row.version}:{action}",
                payload=payload,
            ),
        ]
    )


def expire(session: Session, row: Appointment, now: datetime) -> bool:
    if (
        row.status != AppointmentStatus.AWAITING_PAYMENT
        or row.hold_expires_at is None
        or row.hold_expires_at > now
    ):
        return False
    row.status = AppointmentStatus.EXPIRED
    row.version += 1
    event(session, row, "expired", None)
    session.flush()
    return True


def expire_related(
    session: Session, customer_id: UUID, employees: set[UUID], now: datetime
) -> None:
    rows = session.scalars(
        select(Appointment)
        .where(
            Appointment.status == AppointmentStatus.AWAITING_PAYMENT,
            Appointment.hold_expires_at <= now,
            or_(Appointment.customer_id == customer_id, Appointment.employee_id.in_(employees)),
        )
        .order_by(Appointment.id)
        .with_for_update()
    ).all()
    for row in rows:
        expire(session, row, now)


def confirm_verified(
    session: Session, row: Appointment, actor: UUID | None, *, request_id: UUID | None = None
) -> None:
    """Caller holds calendar/customer/employee/appointment locks in this same UoW.

    A provider callback must never call this before creating matched immutable
    receipt/allocation evidence. This function performs no payment I/O or commit.
    """
    now = datetime.now(UTC)
    if expire(session, row, now):
        raise ExpiredHold()
    if (
        row.status != AppointmentStatus.AWAITING_PAYMENT
        or row.hold_expires_at is None
        or row.hold_expires_at <= now
    ):
        raise AppError("invalid_transition", "Only a live hold can be confirmed.", 409)
    intent = session.scalar(
        select(PaymentIntent).where(PaymentIntent.appointment_id == row.id).with_for_update()
    )
    allocated = (
        None
        if intent is None
        else session.scalar(
            select(PaymentAllocation.id).where(
                PaymentAllocation.intent_id == intent.id,
                PaymentAllocation.amount == row.total_amount,
                PaymentAllocation.currency == row.currency,
                PaymentAllocation.is_test == row.is_test,
            )
        )
    )
    if (
        row.total_amount <= 0
        or intent is None
        or intent.status != PaymentStatus.SUCCEEDED
        or allocated is None
    ):
        raise AppError(
            "payment_required",
            "A matched verified payment is required to confirm this booking.",
            409,
        )
    now = datetime.now(UTC)
    if expire(session, row, now):
        raise ExpiredHold()
    row.status, row.confirmed_at = AppointmentStatus.CONFIRMED, now
    row.version += 1
    event(session, row, "confirmed", actor, request_id=request_id)


def payment_review(session: Session, row: Appointment) -> None:
    """Cancellation does not invent a refund or rewrite immutable payment evidence."""
    if row.total_amount > 0:
        session.add(
            OutboxEvent(
                tenant_id=row.tenant_id,
                event_type="appointment.payment_review",
                aggregate_id=row.id,
                deduplication_key=f"appointment:{row.id}:{row.version}:payment-review",
                payload={"appointment_id": str(row.id), "version": row.version},
            )
        )
