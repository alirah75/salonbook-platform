"""Tenant-explicit bounded expiry batches, safe for multiple concurrent workers."""

from datetime import UTC, datetime
from functools import partial
from threading import Event
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.core.logging import logger
from app.db.database import Database
from app.db.enums import AppointmentStatus
from app.modules.appointments import domain
from app.modules.appointments.models import Appointment
from app.modules.scheduling.coordination import lock_calendar
from app.modules.tenancy.locks import tenant_lock


class ExpiryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def batch(self, tenant: UUID, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("Batch limit must be 1 to 1000.")
        with self.database.transaction(tenant, read_only=True) as session:
            ids = list(
                session.scalars(
                    select(Appointment.id)
                    .where(
                        Appointment.status == AppointmentStatus.AWAITING_PAYMENT,
                        Appointment.hold_expires_at <= datetime.now(UTC),
                    )
                    .order_by(Appointment.hold_expires_at, Appointment.id)
                    .limit(limit)
                )
            )
        return sum(domain.retry(partial(self.one, tenant, identifier)) for identifier in ids)

    def one(self, tenant: UUID, identifier: UUID) -> bool:
        with self.database.transaction(tenant) as session:
            # Suspended tenants still need expiry; this worker has no interactive access.
            tenant_lock(session, tenant, "lifecycle", shared=True)
            lock_calendar(session, tenant, shared=True)
            row = session.scalar(select(Appointment).where(Appointment.id == identifier))
            if row is None:
                return False
            domain.customer_lock(session, row.customer_id)
            session.refresh(row)
            domain.employee_locks(session, {row.employee_id})
            session.refresh(row, with_for_update=True)
            result = domain.expire(session, row, datetime.now(UTC))
        return result

    def run(self, tenant: UUID, stop: Event, interval: float = 5) -> None:
        while not stop.is_set():
            try:
                self.batch(tenant)
            except (AppError, SQLAlchemyError) as exc:
                logger.error(
                    "appointment.expiry_failed",
                    extra={"event": "appointment.expiry_failed", "error_type": type(exc).__name__},
                )
            stop.wait(interval)
