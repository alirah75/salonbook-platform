from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.modules.access.service import Principal
from app.modules.appointments.models import Appointment
from app.modules.appointments.schemas import AppointmentResponse
from app.modules.appointments.service import view, visibility
from app.modules.catalog import common
from app.modules.catalog.models import Line
from app.modules.catalog.schemas import Page
from app.modules.identity.context import AuthContext
from app.modules.identity.sessions import SessionService
from app.modules.tenancy.models import Salon
from app.modules.workforce.models import EmployeeLine, EmployeeProfile

WORK_PERMISSIONS = {
    "appointment.read",
    "appointment.read_assigned",
    "catalog.manage",
    "staff.assign",
    "staff.manage",
    "schedule.read",
    "schedule.read_own",
    "users.read",
    "roles.read",
    "salon.manage",
    "finance.read",
}


class GrantView(BaseModel):
    permission: str
    scope: str
    line_id: str | None


class Named(BaseModel):
    id: UUID
    name: str


class Workspace(BaseModel):
    salon_name: str
    timezone: str
    today: date
    grants: list[GrantView]
    roles: list[str]
    employee_id: UUID | None
    lines: list[Named]


class Overview(BaseModel):
    day: date
    timezone: str
    generated_at: datetime
    counts: dict[str, int]
    appointments: Page[AppointmentResponse]


def require_workspace(principal: Principal) -> None:
    if not any(grant.permission in WORK_PERMISSIONS for grant in principal.grants):
        raise AppError("forbidden", "Staff workspace access is required.", 403)


def work_visibility(session: Session, principal: Principal) -> ColumnElement[bool]:
    # Customer permissions never widen the employee/manager workspace.
    restricted = Principal(
        principal.tenant_id,
        principal.user_id,
        frozenset(
            g
            for g in principal.grants
            if g.permission in {"appointment.read", "appointment.read_assigned"}
        ),
        principal.roles,
        principal.verified,
    )
    return visibility(session, restricted)


class DashboardService:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions

    def context(self, context: AuthContext, raw: str) -> Workspace:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            principal = identity.principal
            require_workspace(principal)
            salon = session.scalar(select(Salon))
            assert salon is not None
            employee = session.scalar(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.user_id == principal.user_id,
                    EmployeeProfile.is_active.is_(True),
                    EmployeeProfile.deleted_at.is_(None),
                )
            )
            grants = [
                g
                for g in principal.grants
                if g.permission in WORK_PERMISSIONS
                and not g.permission.endswith("_own")
                and not g.permission.endswith("_assigned")
            ]
            query = select(Line).where(Line.deleted_at.is_(None))
            if not any(g.scope == "TENANT" for g in grants):
                lines = {UUID(g.line_id) for g in grants if g.scope == "LINE"}
                if employee:
                    lines.update(
                        session.scalars(
                            select(EmployeeLine.line_id).where(
                                EmployeeLine.employee_id == employee,
                                EmployeeLine.is_active.is_(True),
                                EmployeeLine.deleted_at.is_(None),
                            )
                        )
                    )
                query = query.where(Line.id.in_(lines))
            # This is a bounded navigation list, never an aggregate of sensitive data.
            rows = session.scalars(query.order_by(Line.name, Line.id).limit(501)).all()
            if len(rows) > 500:
                raise AppError(
                    "workspace_limit", "This workspace needs a narrower navigation scope.", 422
                )
            return Workspace(
                salon_name=salon.name,
                timezone=salon.timezone,
                today=datetime.now(ZoneInfo(salon.timezone)).date(),
                grants=[
                    GrantView(permission=g.permission, scope=g.scope, line_id=g.line_id or None)
                    for g in sorted(principal.grants)
                ],
                roles=sorted(principal.roles),
                employee_id=employee,
                lines=[Named(id=row.id, name=row.name) for row in rows],
            )

    def overview(
        self,
        context: AuthContext,
        raw: str,
        day: date | None,
        line_id: UUID | None,
        limit: int,
        offset: int,
    ) -> Overview:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            require_workspace(identity.principal)
            salon = session.scalar(select(Salon))
            assert salon is not None
            zone = ZoneInfo(salon.timezone)
            selected = day or datetime.now(zone).date()
            start = datetime.combine(selected, time.min, zone).astimezone(UTC)
            end = datetime.combine(selected + timedelta(days=1), time.min, zone).astimezone(UTC)
            filters = [
                work_visibility(session, identity.principal),
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
            ]
            if line_id:
                filters.append(Appointment.line_id == line_id)
            counts = {
                status.value: int(count)
                for status, count in session.execute(
                    select(Appointment.status, func.count())
                    .where(*filters)
                    .group_by(Appointment.status)
                )
            }
            rows = session.scalars(
                select(Appointment)
                .where(*filters)
                .order_by(Appointment.starts_at, Appointment.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            return Overview(
                day=selected,
                timezone=salon.timezone,
                generated_at=datetime.now(UTC),
                counts=counts,
                appointments=common.page(
                    [view(session, identity.principal, row) for row in rows], limit, offset
                ),
            )
