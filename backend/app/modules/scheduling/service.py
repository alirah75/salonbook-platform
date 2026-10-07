from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, false, or_, select, true
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.enums import BlockKind, BlockStatus, CalendarScope
from app.modules.access.service import Principal
from app.modules.catalog import common
from app.modules.catalog.models import Line
from app.modules.catalog.schemas import Page
from app.modules.identity.context import AuthContext
from app.modules.identity.sessions import SessionService
from app.modules.scheduling import engine
from app.modules.scheduling.intervals import local_interval
from app.modules.scheduling.models import (
    Calendar,
    DayOverride,
    ScheduleBlock,
    SpecialPeriod,
    WeeklyPeriod,
)
from app.modules.scheduling.schemas import (
    AvailabilityQuery,
    AvailabilityResponse,
    BlockCreate,
    BlockResponse,
    BlockTransition,
    CalendarCreate,
    CalendarResponse,
    OverrideResponse,
    OverrideWrite,
    Period,
    SettingsResponse,
    SettingsWrite,
    WeeklyResponse,
    WeeklyWrite,
)
from app.modules.tenancy.management import record_change
from app.modules.workforce.models import EmployeeProfile


def get_calendar(session: Session, identifier: UUID) -> Calendar:
    row = session.scalar(select(Calendar).where(Calendar.id == identifier))
    if row is None:
        raise common.missing()
    return row


def own_employee(session: Session, principal: Principal) -> EmployeeProfile | None:
    return session.scalar(
        select(EmployeeProfile).where(
            EmployeeProfile.user_id == principal.user_id,
            EmployeeProfile.is_active.is_(True),
            EmployeeProfile.deleted_at.is_(None),
        )
    )


def authorize(
    session: Session, principal: Principal, calendar: Calendar, *, write: bool = False
) -> None:
    permission = "schedule.manage" if write else "schedule.read"
    if not write:
        own = own_employee(session, principal)
        if (
            own is not None
            and calendar.employee_id == own.id
            and any(
                g.permission == "schedule.read_own"
                and (
                    g.scope == "TENANT"
                    or (calendar.line_id is not None and g.line_id == str(calendar.line_id))
                )
                for g in principal.grants
            )
        ):
            principal.require(
                "schedule.read_own", owner_id=principal.user_id, line_id=calendar.line_id
            )
            return
    principal.require(permission, line_id=calendar.line_id)


def override_view(session: Session, row: DayOverride) -> OverrideResponse:
    periods = session.scalars(
        select(SpecialPeriod)
        .where(SpecialPeriod.override_id == row.id)
        .order_by(SpecialPeriod.start_minute)
    ).all()
    return OverrideResponse(
        id=row.id,
        local_date=row.local_date,
        mode=row.mode,
        reason=row.reason,
        periods=[Period(start_minute=p.start_minute, end_minute=p.end_minute) for p in periods],
    )


class SchedulingService:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions

    def available(self, context: AuthContext, payload: AvailabilityQuery) -> AvailabilityResponse:
        with common.public_catalog(self.sessions.database, context) as session:
            result = engine.availability(session, payload)
        return result

    def get_settings(self, context: AuthContext, raw: str) -> SettingsResponse:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            identity.principal.require("salon.read")
            salon, policy, control = engine.settings(session)
            result = SettingsResponse(
                **{key: getattr(policy, key) for key in SettingsWrite.model_fields},
                timezone=salon.timezone,
                calendar_version=control.version,
            )
        return result

    def save_settings(
        self, context: AuthContext, raw: str, csrf: str, payload: SettingsWrite
    ) -> SettingsResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("schedule.manage")
            salon, policy, control = engine.settings(session)
            before = {key: getattr(policy, key) for key in SettingsWrite.model_fields}
            for key, value in payload.model_dump().items():
                setattr(policy, key, value)
            policy.policy_version += 1
            record_change(
                session,
                context,
                identity.user.id,
                "schedule.settings_saved",
                "salon_settings",
                policy.id,
                {"before": before, "after": payload.model_dump(mode="json")},
            )
            result = SettingsResponse(
                **payload.model_dump(),
                timezone=salon.timezone,
                calendar_version=control.version + 1,
            )
        return result

    def calendars(
        self, context: AuthContext, raw: str, limit: int, offset: int
    ) -> Page[CalendarResponse]:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            principal = identity.principal
            grants = [g for g in principal.grants if g.permission == "schedule.read"]
            query = select(Calendar)
            if not any(g.scope == "TENANT" for g in grants):
                own = own_employee(session, principal)
                own_grants = [g for g in principal.grants if g.permission == "schedule.read_own"]
                owned = own.id if own and own_grants else None
                own_scope = (
                    true()
                    if any(g.scope == "TENANT" for g in own_grants)
                    else Calendar.line_id.in_(
                        [UUID(g.line_id) for g in own_grants if g.scope == "LINE"]
                    )
                )
                allowed = [UUID(g.line_id) for g in grants if g.scope == "LINE"]
                if not allowed and owned is None:
                    raise AppError("forbidden", "Access denied.", 403)
                query = query.where(
                    or_(
                        Calendar.line_id.in_(allowed),
                        (Calendar.employee_id == owned) & own_scope if owned else false(),
                    )
                )
            rows = session.scalars(
                query.order_by(Calendar.scope, Calendar.id).offset(offset).limit(limit + 1)
            ).all()
            employees = {
                identifier: name
                for identifier, name in session.execute(
                    select(EmployeeProfile.id, EmployeeProfile.public_name).where(
                        EmployeeProfile.id.in_([r.employee_id for r in rows if r.employee_id])
                    )
                ).all()
            }
            lines = {
                identifier: name
                for identifier, name in session.execute(
                    select(Line.id, Line.name).where(
                        Line.id.in_([r.line_id for r in rows if r.line_id])
                    )
                ).all()
            }
            result = common.page(
                [
                    CalendarResponse.model_validate(r).model_copy(
                        update={
                            "employee_name": employees.get(r.employee_id)
                            if r.employee_id
                            else None,
                            "line_name": lines.get(r.line_id) if r.line_id else None,
                        }
                    )
                    for r in rows
                ],
                limit,
                offset,
            )
        return result

    def create_calendar(
        self, context: AuthContext, raw: str, csrf: str, payload: CalendarCreate
    ) -> CalendarResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("schedule.manage", line_id=payload.line_id)
            if payload.line_id:
                common.require_active(common.line(session, payload.line_id))
            if payload.employee_id:
                common.require_active(*common.employee(session, payload.employee_id))
            if payload.line_id and payload.employee_id:
                common.require_active(
                    common.employee_line(session, payload.line_id, payload.employee_id)
                )
            row = Calendar(tenant_id=context.tenant_id, **payload.model_dump())
            session.add(row)
            session.flush()
            salon, _, _ = engine.settings(session)
            engine.require_no_conflicts(session, row, ZoneInfo(salon.timezone))
            record_change(
                session,
                context,
                identity.user.id,
                "calendar.created",
                "calendar",
                row.id,
                payload.model_dump(mode="json"),
            )
            result = CalendarResponse.model_validate(row)
        return result

    def weekly(self, context: AuthContext, raw: str, identifier: UUID) -> list[WeeklyResponse]:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            authorize(session, identity.principal, get_calendar(session, identifier))
            result = [
                WeeklyResponse.model_validate(p)
                for p in session.scalars(
                    select(WeeklyPeriod)
                    .where(WeeklyPeriod.calendar_id == identifier)
                    .order_by(WeeklyPeriod.weekday, WeeklyPeriod.start_minute, WeeklyPeriod.id)
                )
            ]
        return result

    def save_weekly(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, payload: WeeklyWrite
    ) -> list[WeeklyResponse]:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            row = get_calendar(session, identifier)
            authorize(session, identity.principal, row, write=True)
            before = [
                WeeklyResponse.model_validate(p).model_dump(mode="json")
                for p in session.scalars(
                    select(WeeklyPeriod).where(WeeklyPeriod.calendar_id == identifier)
                )
            ]
            session.execute(delete(WeeklyPeriod).where(WeeklyPeriod.calendar_id == identifier))
            periods = [
                WeeklyPeriod(tenant_id=context.tenant_id, calendar_id=identifier, **p.model_dump())
                for p in payload.periods
            ]
            session.add_all(periods)
            session.flush()
            salon, _, _ = engine.settings(session)
            engine.require_no_conflicts(session, row, ZoneInfo(salon.timezone))
            record_change(
                session,
                context,
                identity.user.id,
                "schedule.weekly_saved",
                "calendar",
                identifier,
                {"before": before, "after": payload.model_dump(mode="json")},
            )
            result = [WeeklyResponse.model_validate(p) for p in periods]
        return result

    def overrides(
        self, context: AuthContext, raw: str, identifier: UUID, start: date, end: date
    ) -> list[OverrideResponse]:
        if not 1 <= (end - start).days <= 366:
            raise AppError("date_range", "Select one to 366 days.", 422)
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            authorize(session, identity.principal, get_calendar(session, identifier))
            rows = session.scalars(
                select(DayOverride)
                .where(
                    DayOverride.calendar_id == identifier,
                    DayOverride.local_date >= start,
                    DayOverride.local_date < end,
                )
                .order_by(DayOverride.local_date)
            ).all()
            result = [override_view(session, row) for row in rows]
        return result

    def save_override(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        identifier: UUID,
        day: date,
        payload: OverrideWrite | None,
    ) -> OverrideResponse | None:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            calendar = get_calendar(session, identifier)
            authorize(session, identity.principal, calendar, write=True)
            salon, _, _ = engine.settings(session)
            zone = ZoneInfo(salon.timezone)
            if payload:
                try:
                    for p in payload.periods:
                        local_interval(day, p.start_minute, p.end_minute, zone)
                except ValueError as exc:
                    raise AppError(
                        "nonexistent_local_time",
                        "An opening endpoint does not exist in the salon timezone.",
                        422,
                    ) from exc
            row = session.scalar(
                select(DayOverride).where(
                    DayOverride.calendar_id == identifier, DayOverride.local_date == day
                )
            )
            before = override_view(session, row).model_dump(mode="json") if row else None
            if row:
                session.execute(delete(SpecialPeriod).where(SpecialPeriod.override_id == row.id))
                session.delete(row)
                session.flush()
            result = None
            if payload:
                row = DayOverride(
                    tenant_id=context.tenant_id,
                    calendar_id=identifier,
                    local_date=day,
                    mode=payload.mode,
                    reason=payload.reason,
                )
                session.add(row)
                session.flush()
                session.add_all(
                    SpecialPeriod(tenant_id=context.tenant_id, override_id=row.id, **p.model_dump())
                    for p in payload.periods
                )
                session.flush()
                result = override_view(session, row)
            engine.require_no_conflicts(session, calendar, zone)
            record_change(
                session,
                context,
                identity.user.id,
                "schedule.override_saved",
                "calendar",
                identifier,
                {
                    "local_date": day.isoformat(),
                    "before": before,
                    "after": result.model_dump(mode="json") if result else None,
                },
            )
        return result

    def blocks(
        self, context: AuthContext, raw: str, identifier: UUID, limit: int, offset: int
    ) -> Page[BlockResponse]:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            authorize(session, identity.principal, get_calendar(session, identifier))
            rows = session.scalars(
                select(ScheduleBlock)
                .where(ScheduleBlock.calendar_id == identifier)
                .order_by(ScheduleBlock.starts_at.desc(), ScheduleBlock.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page([BlockResponse.model_validate(r) for r in rows], limit, offset)
        return result

    def create_block(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        identifier: UUID,
        payload: BlockCreate,
        *,
        own: bool = False,
    ) -> BlockResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            calendar = get_calendar(session, identifier)
            if own:
                profile = own_employee(session, identity.principal)
                identity.principal.require("leave.request_own", owner_id=identity.user.id)
                if (
                    profile is None
                    or calendar.employee_id != profile.id
                    or calendar.scope != CalendarScope.EMPLOYEE
                    or payload.kind != BlockKind.LEAVE
                ):
                    raise AppError(
                        "forbidden", "Leave requests must target your personal calendar.", 403
                    )
            else:
                authorize(session, identity.principal, calendar, write=True)
            if payload.ends_at <= datetime.now(UTC):
                raise AppError("past_block", "Choose a future block.", 422)
            row = ScheduleBlock(
                tenant_id=context.tenant_id,
                calendar_id=identifier,
                requested_by_id=identity.user.id,
                approved_by_id=None if own else identity.user.id,
                status=BlockStatus.REQUESTED if own else BlockStatus.APPROVED,
                **payload.model_dump(),
            )
            session.add(row)
            session.flush()
            if not own:
                salon, _, _ = engine.settings(session)
                engine.require_no_conflicts(session, calendar, ZoneInfo(salon.timezone))
            record_change(
                session,
                context,
                identity.user.id,
                "schedule.block_created",
                "schedule_block",
                row.id,
                {
                    "calendar_id": str(identifier),
                    "status": row.status.value,
                    "kind": row.kind.value,
                },
            )
            result = BlockResponse.model_validate(row)
        return result

    def transition_block(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, payload: BlockTransition
    ) -> BlockResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            row = session.scalar(select(ScheduleBlock).where(ScheduleBlock.id == identifier))
            if row is None:
                raise common.missing()
            calendar = get_calendar(session, row.calendar_id)
            own = own_employee(session, identity.principal)
            own_cancel = (
                payload.status == BlockStatus.CANCELLED
                and row.status == BlockStatus.REQUESTED
                and row.requested_by_id == identity.user.id
                and own is not None
                and calendar.employee_id == own.id
            )
            if own_cancel:
                identity.principal.require("leave.request_own", owner_id=identity.user.id)
            else:
                authorize(session, identity.principal, calendar, write=True)
            permitted = {
                BlockStatus.REQUESTED: {
                    BlockStatus.APPROVED,
                    BlockStatus.REJECTED,
                    BlockStatus.CANCELLED,
                },
                BlockStatus.APPROVED: {BlockStatus.CANCELLED},
            }
            if payload.status not in permitted.get(row.status, set()):
                raise AppError(
                    "invalid_transition", "This block can no longer make that transition.", 409
                )
            previous, row.status = row.status, payload.status
            if row.status == BlockStatus.APPROVED:
                row.approved_by_id = identity.user.id
            session.flush()
            if row.status == BlockStatus.APPROVED:
                salon, _, _ = engine.settings(session)
                engine.require_no_conflicts(session, calendar, ZoneInfo(salon.timezone))
            record_change(
                session,
                context,
                identity.user.id,
                "schedule.block_transition",
                "schedule_block",
                row.id,
                {"before": previous.value, "after": row.status.value},
            )
            result = BlockResponse.model_validate(row)
        return result
