"""Read a consistent calendar snapshot under CalendarControl, then compute in memory."""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError, FieldIssue
from app.db.enums import AppointmentStatus, BlockStatus, CalendarScope, DayOverrideMode
from app.modules.appointments.models import Appointment
from app.modules.catalog import common
from app.modules.catalog.models import LineService, Service
from app.modules.identity.models import User
from app.modules.scheduling.intervals import (
    Interval,
    Package,
    contains,
    intersect,
    local_instant,
    local_interval,
    merge,
    package,
    subtract,
)
from app.modules.scheduling.models import (
    Calendar,
    DayOverride,
    ScheduleBlock,
    SpecialPeriod,
    WeeklyPeriod,
)
from app.modules.scheduling.schemas import AvailabilityQuery, AvailabilityResponse, Slot
from app.modules.tenancy.models import CalendarControl, Salon, SalonSettings
from app.modules.workforce.models import EmployeeLine, EmployeeProfile, EmployeeService


def days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days)]


def settings(session: Session) -> tuple[Salon, SalonSettings, CalendarControl]:
    salon = session.scalar(select(Salon))
    policy = session.scalar(select(SalonSettings))
    control = session.scalar(select(CalendarControl))
    if salon is None or policy is None or control is None:
        raise AppError("calendar_unavailable", "Calendar configuration is unavailable.", 503)
    return salon, policy, control


@dataclass
class CalendarData:
    calendar: Calendar
    weekly: list[WeeklyPeriod] = field(default_factory=list)
    overrides: dict[date, DayOverride] = field(default_factory=dict)
    special: dict[UUID, list[SpecialPeriod]] = field(default_factory=lambda: defaultdict(list))
    blocks: list[Interval] = field(default_factory=list)

    def openings(self, day: date, zone: ZoneInfo) -> list[Interval]:
        override = self.overrides.get(day)
        if override is not None and override.mode == DayOverrideMode.CLOSED:
            return []
        openings: list[Interval] = []
        breaks: list[Interval] = []
        try:
            if override is not None:
                openings = [
                    local_interval(day, p.start_minute, p.end_minute, zone)
                    for p in self.special[override.id]
                ]
            else:
                for period in self.weekly:
                    if (
                        period.weekday == day.weekday()
                        and period.valid_from <= day
                        and (period.valid_until is None or day < period.valid_until)
                    ):
                        interval = local_interval(day, period.start_minute, period.end_minute, zone)
                        (openings if period.kind == "OPEN" else breaks).append(interval)
        except ValueError:
            # A recurring endpoint may fall into a DST gap in a future year. Never
            # silently discard a break or invent an instant: this calendar/day closes.
            return []
        return subtract(openings, [*breaks, *self.blocks])


def load_calendars(
    session: Session, calendars: list[Calendar], start: date, end: date
) -> dict[UUID, CalendarData]:
    result = {c.id: CalendarData(c) for c in calendars}
    if not result:
        return result
    for weekly in session.scalars(
        select(WeeklyPeriod).where(
            WeeklyPeriod.calendar_id.in_(result),
            WeeklyPeriod.valid_from < end,
            or_(WeeklyPeriod.valid_until.is_(None), WeeklyPeriod.valid_until > start),
        )
    ):
        result[weekly.calendar_id].weekly.append(weekly)
    overrides = list(
        session.scalars(
            select(DayOverride).where(
                DayOverride.calendar_id.in_(result),
                DayOverride.local_date >= start,
                DayOverride.local_date < end,
            )
        )
    )
    by_override = {row.id: row.calendar_id for row in overrides}
    for row in overrides:
        result[row.calendar_id].overrides[row.local_date] = row
    if by_override:
        for period in session.scalars(
            select(SpecialPeriod).where(SpecialPeriod.override_id.in_(by_override))
        ):
            result[by_override[period.override_id]].special[period.override_id].append(period)
    lower = datetime.combine(start, datetime.min.time(), UTC) - timedelta(days=1)
    upper = datetime.combine(end, datetime.min.time(), UTC) + timedelta(days=1)
    for block in session.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.calendar_id.in_(result),
            ScheduleBlock.status == BlockStatus.APPROVED,
            ScheduleBlock.starts_at < upper,
            ScheduleBlock.ends_at > lower,
        )
    ):
        result[block.calendar_id].blocks.append(Interval(block.starts_at, block.ends_at))
    return result


def occupying(now: datetime) -> ColumnElement[bool]:
    return or_(
        Appointment.status.in_(
            (AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW)
        ),
        (Appointment.status == AppointmentStatus.AWAITING_PAYMENT)
        & (Appointment.hold_expires_at > now),
    )


def require_no_conflicts(session: Session, calendar: Calendar, zone: ZoneInfo) -> None:
    """Check the proposed calendar, after flush, without rewriting booking snapshots."""
    now = datetime.now(UTC)
    query = select(Appointment).where(occupying(now), Appointment.occupied_ends_at > now)
    if calendar.line_id is not None:
        query = query.where(Appointment.line_id == calendar.line_id)
    if calendar.employee_id is not None:
        query = query.where(Appointment.employee_id == calendar.employee_id)
    appointments = list(
        session.scalars(query.order_by(Appointment.starts_at, Appointment.id).limit(5001))
    )
    if len(appointments) > 5000:
        raise AppError(
            "schedule_review_required", "Too many future bookings for this schedule change.", 409
        )
    if not appointments:
        return
    start = min(a.occupied_starts_at for a in appointments).astimezone(zone).date()
    end = max(a.occupied_ends_at for a in appointments).astimezone(zone).date() + timedelta(days=1)
    data = load_calendars(session, [calendar], start, end)[calendar.id]
    cached: dict[date, list[Interval]] = {}
    conflicts: list[FieldIssue] = []
    for appointment in appointments:
        first = appointment.occupied_starts_at.astimezone(zone).date()
        until = appointment.occupied_ends_at.astimezone(zone).date() + timedelta(days=1)
        periods: list[Interval] = []
        for day in days(first, until):
            if day not in cached:
                cached[day] = data.openings(day, zone)
            periods.extend(cached[day])
        if not contains(
            merge(periods), Interval(appointment.occupied_starts_at, appointment.occupied_ends_at)
        ):
            conflicts.append(
                FieldIssue(
                    field=f"appointments.{appointment.id}",
                    code="schedule_conflict",
                    message="Occupied time falls outside the proposed schedule.",
                )
            )
            if len(conflicts) == 100:
                break
    if conflicts:
        raise AppError(
            "schedule_conflict",
            "Resolve conflicting bookings before changing the schedule (up to 100 shown).",
            409,
            details=conflicts,
        )


def availability(
    session: Session,
    query: AvailabilityQuery,
    *,
    now: datetime | None = None,
    at: datetime | None = None,
    reserved_package: Package | None = None,
    exclude_appointment_id: UUID | None = None,
) -> AvailabilityResponse:
    now = now or datetime.now(UTC)
    salon, policy, control = settings(session)
    zone = ZoneInfo(salon.timezone)
    today = now.astimezone(zone).date()
    if query.date_from < today or query.date_until > today + timedelta(
        days=policy.booking_horizon_days + 1
    ):
        raise AppError("booking_window", "Dates fall outside the booking horizon.", 422)
    if len(query.service_ids) > policy.max_services:
        raise AppError("package_limit", "Too many services in one booking.", 422)
    common.require_active(common.line(session, query.line_id))
    offers = list(
        session.scalars(
            select(LineService)
            .join(
                Service,
                (Service.id == LineService.service_id)
                & (Service.tenant_id == LineService.tenant_id),
            )
            .where(
                LineService.line_id == query.line_id,
                LineService.service_id.in_(query.service_ids),
                LineService.is_active.is_(True),
                LineService.deleted_at.is_(None),
                Service.is_active.is_(True),
                Service.deleted_at.is_(None),
            )
        )
    )
    offer_map = {o.service_id: o for o in offers}
    if len(offer_map) != len(query.service_ids):
        raise common.missing()
    ordered = [offer_map[identifier] for identifier in query.service_ids]
    bundle = reserved_package or package(
        [(o.duration_minutes, o.buffer_before_minutes, o.buffer_after_minutes) for o in ordered]
    )
    if bundle.occupied_minutes > policy.max_duration_minutes:
        raise AppError("package_limit", "The package exceeds the maximum occupied duration.", 422)
    candidates = (
        select(EmployeeProfile)
        .join(
            User,
            (User.id == EmployeeProfile.user_id) & (User.tenant_id == EmployeeProfile.tenant_id),
        )
        .join(
            EmployeeLine,
            (EmployeeLine.employee_id == EmployeeProfile.id)
            & (EmployeeLine.tenant_id == EmployeeProfile.tenant_id),
        )
        .where(
            EmployeeLine.line_id == query.line_id,
            EmployeeLine.is_active.is_(True),
            EmployeeLine.deleted_at.is_(None),
            EmployeeProfile.is_active.is_(True),
            EmployeeProfile.deleted_at.is_(None),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    for identifier in query.service_ids:
        candidates = candidates.where(
            select(EmployeeService.id)
            .where(
                EmployeeService.tenant_id == EmployeeProfile.tenant_id,
                EmployeeService.employee_id == EmployeeProfile.id,
                EmployeeService.line_id == query.line_id,
                EmployeeService.service_id == identifier,
                EmployeeService.is_active.is_(True),
                EmployeeService.deleted_at.is_(None),
            )
            .exists()
        )
    if query.employee_id is not None:
        candidates = candidates.where(EmployeeProfile.id == query.employee_id)
    employees = list(session.scalars(candidates.order_by(EmployeeProfile.id).limit(101)))
    if (
        len(employees) > 100
        or len(employees)
        * (query.date_until - query.date_from).days
        * (1 if at is not None else 1440 // policy.slot_step_minutes + 1)
        > 100000
    ):
        raise AppError("availability_limit", "Select fewer days or a specific employee.", 422)
    if query.employee_id is not None and not employees:
        raise common.missing()
    identifiers = [e.id for e in employees]
    calendars = list(
        session.scalars(
            select(Calendar).where(
                or_(
                    Calendar.scope == CalendarScope.SALON,
                    (Calendar.scope == CalendarScope.LINE) & (Calendar.line_id == query.line_id),
                    (Calendar.scope == CalendarScope.EMPLOYEE)
                    & Calendar.employee_id.in_(identifiers),
                    (Calendar.scope == CalendarScope.EMPLOYEE_LINE)
                    & (Calendar.line_id == query.line_id)
                    & Calendar.employee_id.in_(identifiers),
                )
            )
        )
    )
    # Include adjoining days so buffers and contiguous overnight shifts can span midnight.
    start, end = query.date_from - timedelta(days=1), query.date_until + timedelta(days=1)
    data = load_calendars(session, calendars, start, end)
    by_target = {(c.scope, c.employee_id): data[c.id] for c in calendars}
    lower = datetime.combine(start, datetime.min.time(), UTC) - timedelta(days=1)
    upper = datetime.combine(end, datetime.min.time(), UTC) + timedelta(days=1)
    bookings = list(
        session.scalars(
            select(Appointment)
            .where(
                Appointment.employee_id.in_(identifiers),
                occupying(now),
                Appointment.occupied_starts_at < upper,
                Appointment.occupied_ends_at > lower,
                Appointment.id != exclude_appointment_id if exclude_appointment_id else true(),
            )
            .limit(10001)
        )
    )
    if len(bookings) > 10000:
        raise AppError("availability_limit", "Select fewer days or a specific employee.", 422)
    occupied: dict[UUID, list[Interval]] = defaultdict(list)
    workload: dict[tuple[UUID, date], float] = defaultdict(float)
    for appointment in bookings:
        occupied[appointment.employee_id].append(
            Interval(appointment.occupied_starts_at, appointment.occupied_ends_at)
        )
        workload[(appointment.employee_id, appointment.starts_at.astimezone(zone).date())] += (
            appointment.occupied_ends_at - appointment.occupied_starts_at
        ).total_seconds()
    slots: list[Slot] = []
    notice = now + timedelta(minutes=policy.min_notice_minutes)
    for employee in employees:
        salon_data = by_target.get((CalendarScope.SALON, None))
        employee_data = by_target.get((CalendarScope.EMPLOYEE, employee.id))
        if salon_data is None or employee_data is None:
            continue
        levels = [salon_data, employee_data]
        for target in ((CalendarScope.LINE, None), (CalendarScope.EMPLOYEE_LINE, employee.id)):
            if target in by_target:
                levels.append(by_target[target])
        openings: list[Interval] = []
        for day in days(start, end):
            daily = levels[0].openings(day, zone)
            for level in levels[1:]:
                daily = intersect(daily, level.openings(day, zone))
            openings.extend(daily)
        free = subtract(merge(openings), occupied[employee.id])
        free_starts = [period.start for period in free]
        for day in days(query.date_from, query.date_until):
            local = at.astimezone(zone) if at else None
            minutes = (
                ([local.hour * 60 + local.minute] if local.date() == day else [])
                if local
                else range(0, 1440, policy.slot_step_minutes)
            )
            for minute in minutes:
                if minute % policy.slot_step_minutes:
                    continue
                try:
                    begins = local_instant(day, minute, zone)
                except ValueError:
                    continue
                if at is not None and begins != at:
                    continue
                ends = begins + timedelta(minutes=bundle.duration)
                reserved = Interval(
                    begins - timedelta(minutes=bundle.before),
                    ends + timedelta(minutes=bundle.after),
                )
                index = bisect_right(free_starts, reserved.start) - 1
                if reserved.start < notice or index < 0 or free[index].end < reserved.end:
                    continue
                slots.append(
                    Slot(
                        employee_id=employee.id,
                        employee_name=employee.public_name,
                        starts_at=begins,
                        ends_at=ends,
                        occupied_starts_at=reserved.start,
                        occupied_ends_at=reserved.end,
                    )
                )
    slots.sort(
        key=lambda s: (
            s.starts_at,
            workload[(s.employee_id, s.starts_at.astimezone(zone).date())],
            s.employee_id,
        )
    )
    if query.assignment == "auto":
        unique: dict[datetime, Slot] = {}
        for slot in slots:
            unique.setdefault(slot.starts_at, slot)
        slots = list(unique.values())
    return AvailabilityResponse(
        timezone=salon.timezone,
        calendar_version=control.version,
        generated_at=now,
        duration_minutes=bundle.duration,
        buffer_before_minutes=bundle.before,
        buffer_after_minutes=bundle.after,
        total_amount=sum(o.price_amount for o in ordered),
        items=slots[query.offset : query.offset + query.limit],
        limit=query.limit,
        offset=query.offset,
        has_more=len(slots) > query.offset + query.limit,
    )
