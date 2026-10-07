"""Bounded durable scans. Attempt/refund state is the work queue, not process memory."""

from datetime import UTC, datetime
from threading import Event
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.core.logging import logger
from app.db.enums import AppointmentStatus, PaymentStatus, RefundStatus
from app.modules.appointments.models import Appointment
from app.modules.payments.models import PaymentAttempt, PaymentIntent, PaymentTransaction, Refund
from app.modules.payments.processing import OPEN, REFUND_OPEN, PaymentProcessor


class PaymentWorker:
    def __init__(self, processor: PaymentProcessor) -> None:
        self.processor = processor

    def batch(self, tenant: UUID, limit: int = 50) -> int:
        if not 1 <= limit <= 200:
            raise ValueError("Batch limit must be 1 to 200.")
        now = datetime.now(UTC)
        with self.processor.database.transaction(tenant, read_only=True) as session:
            attempts = list(
                session.scalars(
                    select(PaymentAttempt.id)
                    .where(
                        PaymentAttempt.status != PaymentStatus.SUCCEEDED,
                        or_(
                            PaymentAttempt.next_check_at <= now,
                            (
                                PaymentAttempt.next_check_at.is_(None)
                                & PaymentAttempt.status.in_(OPEN)
                            ),
                        ),
                    )
                    .order_by(PaymentAttempt.next_check_at.nullsfirst(), PaymentAttempt.id)
                    .limit(limit)
                )
            )
        completed = 0
        for identifier in attempts:
            try:
                self.processor.reconcile(tenant, identifier)
                completed += 1
            except (AppError, SQLAlchemyError) as exc:
                self.failed(exc)
        with self.processor.database.transaction(tenant, read_only=True) as session:
            reserved = (
                select(func.coalesce(func.sum(Refund.amount), 0))
                .where(
                    Refund.transaction_id == PaymentTransaction.id,
                    Refund.status.not_in([RefundStatus.FAILED, RefundStatus.CANCELLED]),
                )
                .correlate(PaymentTransaction)
                .scalar_subquery()
            )
            cancellations = list(
                session.scalars(
                    select(PaymentAttempt.id)
                    .join(PaymentIntent, PaymentIntent.id == PaymentAttempt.intent_id)
                    .join(Appointment, Appointment.id == PaymentIntent.appointment_id)
                    .join(PaymentTransaction, PaymentTransaction.attempt_id == PaymentAttempt.id)
                    .where(
                        Appointment.status == AppointmentStatus.CANCELLED,
                        PaymentTransaction.amount > reserved,
                        ~exists().where(
                            Refund.transaction_id == PaymentTransaction.id,
                            Refund.request_key.like("auto:%"),
                            Refund.status == RefundStatus.FAILED,
                        ),
                    )
                    .order_by(PaymentAttempt.id)
                    .limit(limit)
                )
            )
        for identifier in cancellations:
            try:
                self.processor.cancel_review(tenant, identifier)
                completed += 1
            except (AppError, SQLAlchemyError) as exc:
                self.failed(exc)
        with self.processor.database.transaction(tenant, read_only=True) as session:
            refunds = list(
                session.scalars(
                    select(Refund.id)
                    .where(
                        Refund.status.in_(REFUND_OPEN),
                        or_(
                            Refund.next_check_at.is_(None),
                            Refund.next_check_at <= datetime.now(UTC),
                        ),
                    )
                    .order_by(Refund.next_check_at.nullsfirst(), Refund.id)
                    .limit(limit)
                )
            )
        for identifier in refunds:
            try:
                self.processor.refund(tenant, identifier)
                completed += 1
            except (AppError, SQLAlchemyError) as exc:
                self.failed(exc)
        return completed

    @staticmethod
    def failed(exc: Exception) -> None:
        logger.error(
            "payment.reconciliation_failed",
            extra={"event": "payment.reconciliation_failed", "error_type": type(exc).__name__},
        )

    def run(self, tenant: UUID, stop: Event, interval: float = 5) -> None:
        while not stop.is_set():
            try:
                self.batch(tenant)
            except (AppError, SQLAlchemyError) as exc:
                self.failed(exc)
            stop.wait(interval)
