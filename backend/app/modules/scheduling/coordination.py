"""Calendar coordination shared by catalog writes and the future booking engine."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.enums import AppointmentStatus
from app.modules.appointments.models import Appointment, AppointmentItem
from app.modules.tenancy.models import CalendarControl


def lock_calendar(session: Session, tenant: UUID, *, shared: bool = False) -> CalendarControl:
    control = session.scalar(
        select(CalendarControl)
        .where(CalendarControl.tenant_id == tenant)
        .with_for_update(read=shared)
    )
    if control is None:
        raise AppError("calendar_unavailable", "Salon calendar is not configured.", 503)
    return control


def require_no_upcoming_bookings(
    session: Session,
    *,
    line_id: UUID | None = None,
    employee_id: UUID | None = None,
    service_id: UUID | None = None,
) -> None:
    """Caller holds the exclusive CalendarControl lock; never cancel bookings implicitly.

    Unprocessed expired holds remain blocked until the booking engine releases them.
    A service's snapshots identify affected bookings even after repricing/rescheduling.
    """
    statement = select(Appointment.id).where(
        Appointment.status.in_((AppointmentStatus.AWAITING_PAYMENT, AppointmentStatus.CONFIRMED)),
        Appointment.occupied_ends_at > datetime.now(UTC),
    )
    if line_id is not None:
        statement = statement.where(Appointment.line_id == line_id)
    if employee_id is not None:
        statement = statement.where(Appointment.employee_id == employee_id)
    if service_id is not None:
        statement = statement.where(
            select(AppointmentItem.id)
            .where(
                AppointmentItem.appointment_id == Appointment.id,
                AppointmentItem.tenant_id == Appointment.tenant_id,
                AppointmentItem.service_id == service_id,
            )
            .exists()
        )
    if session.scalar(statement.limit(1)) is not None:
        raise AppError(
            "upcoming_bookings", "Resolve upcoming bookings before deactivating this resource.", 409
        )
