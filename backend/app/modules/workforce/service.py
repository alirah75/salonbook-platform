from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from app.modules.catalog import common
from app.modules.catalog.schemas import (
    AssignmentWrite,
    EmployeeLineResponse,
    EmployeeResponse,
    EmployeeServiceResponse,
    Page,
    PublicEmployee,
)
from app.modules.identity.context import AuthContext
from app.modules.identity.models import User
from app.modules.identity.sessions import SessionService
from app.modules.scheduling.coordination import require_no_upcoming_bookings
from app.modules.tenancy.management import record_change
from app.modules.workforce.models import EmployeeLine, EmployeeProfile, EmployeeService


class WorkforceService:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions

    def employees(
        self, context: AuthContext, raw: str, limit: int, offset: int
    ) -> Page[EmployeeResponse]:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            identity.principal.require("staff.manage")
            rows = session.execute(
                select(EmployeeProfile, User)
                .join(
                    User,
                    (User.id == EmployeeProfile.user_id)
                    & (User.tenant_id == EmployeeProfile.tenant_id),
                )
                .where(EmployeeProfile.deleted_at.is_(None))
                .order_by(EmployeeProfile.public_name, EmployeeProfile.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [
                    EmployeeResponse(
                        id=employee.id,
                        user_id=user.id,
                        public_name=employee.public_name,
                        is_active=employee.is_active,
                        effective_active=common.active(employee) and common.active(user),
                    )
                    for employee, user in rows
                ],
                limit,
                offset,
            )
        return result

    def candidates(
        self, context: AuthContext, raw: str, line_id: UUID, limit: int, offset: int
    ) -> Page[PublicEmployee]:
        """Names only: a line manager can choose an active shared employee without account access."""
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            identity.principal.require("staff.assign", line_id=line_id)
            common.line(session, line_id)
            rows = session.scalars(
                select(EmployeeProfile)
                .join(
                    User,
                    (User.id == EmployeeProfile.user_id)
                    & (User.tenant_id == EmployeeProfile.tenant_id),
                )
                .where(
                    EmployeeProfile.deleted_at.is_(None),
                    EmployeeProfile.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                )
                .order_by(EmployeeProfile.public_name, EmployeeProfile.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [PublicEmployee.model_validate(row) for row in rows], limit, offset
            )
        return result

    def line_employees(
        self, context: AuthContext, raw: str, line_id: UUID, limit: int, offset: int
    ) -> Page[EmployeeLineResponse]:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            identity.principal.require("staff.assign", line_id=line_id)
            parent = common.line(session, line_id)
            rows = session.execute(
                select(EmployeeLine, EmployeeProfile, User)
                .join(
                    EmployeeProfile,
                    (EmployeeProfile.id == EmployeeLine.employee_id)
                    & (EmployeeProfile.tenant_id == EmployeeLine.tenant_id),
                )
                .join(
                    User,
                    (User.id == EmployeeProfile.user_id)
                    & (User.tenant_id == EmployeeProfile.tenant_id),
                )
                .where(
                    EmployeeLine.line_id == line_id,
                    EmployeeLine.deleted_at.is_(None),
                    EmployeeProfile.deleted_at.is_(None),
                )
                .order_by(EmployeeProfile.public_name, EmployeeProfile.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [
                    EmployeeLineResponse(
                        id=item.id,
                        employee_id=employee.id,
                        line_id=line_id,
                        public_name=employee.public_name,
                        is_active=item.is_active,
                        effective_active=all(
                            common.active(row) for row in (item, employee, user, parent)
                        ),
                    )
                    for item, employee, user in rows
                ],
                limit,
                offset,
            )
        return result

    def put_line_employee(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        line_id: UUID,
        employee_id: UUID,
        payload: AssignmentWrite,
    ) -> EmployeeLineResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("staff.assign", line_id=line_id)
            parent = common.line(session, line_id)
            employee, user = common.employee(session, employee_id)
            if payload.is_active:
                common.require_active(parent, employee, user)
            row = session.scalar(
                select(EmployeeLine).where(
                    EmployeeLine.line_id == line_id, EmployeeLine.employee_id == employee_id
                )
            )
            previous = row.is_active if row else None
            if row is None:
                row = EmployeeLine(
                    tenant_id=context.tenant_id, line_id=line_id, employee_id=employee_id
                )
                session.add(row)
            elif not payload.is_active and row.is_active:
                require_no_upcoming_bookings(session, line_id=line_id, employee_id=employee_id)
            row.is_active, row.deleted_at = payload.is_active, None
            session.flush()
            record_change(
                session,
                context,
                identity.user.id,
                "employee_line.saved",
                "employee_line",
                row.id,
                {
                    "line_id": str(line_id),
                    "employee_id": str(employee_id),
                    "is_active": {"before": previous, "after": row.is_active},
                },
            )
            result = EmployeeLineResponse(
                id=row.id,
                line_id=line_id,
                employee_id=employee_id,
                public_name=employee.public_name,
                is_active=row.is_active,
                effective_active=all(common.active(item) for item in (row, parent, employee, user)),
            )
        return result

    def delete_line_employee(
        self, context: AuthContext, raw: str, csrf: str, line_id: UUID, employee_id: UUID
    ) -> None:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("staff.assign", line_id=line_id)
            common.line(session, line_id)
            row = common.employee_line(session, line_id, employee_id)
            require_no_upcoming_bookings(session, line_id=line_id, employee_id=employee_id)
            now = datetime.now(UTC)
            row.is_active, row.deleted_at = False, now
            session.execute(
                update(EmployeeService)
                .where(
                    EmployeeService.line_id == line_id,
                    EmployeeService.employee_id == employee_id,
                    EmployeeService.deleted_at.is_(None),
                )
                .values(is_active=False, deleted_at=now)
            )
            record_change(
                session,
                context,
                identity.user.id,
                "employee_line.deleted",
                "employee_line",
                row.id,
                {"line_id": str(line_id), "employee_id": str(employee_id)},
            )

    def employee_services(
        self,
        context: AuthContext,
        raw: str,
        line_id: UUID,
        employee_id: UUID,
        limit: int,
        offset: int,
    ) -> Page[EmployeeServiceResponse]:
        from app.modules.catalog.models import LineService, Service

        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            identity.principal.require("staff.assign", line_id=line_id)
            parent = common.line(session, line_id)
            employee, user = common.employee(session, employee_id)
            link = common.employee_line(session, line_id, employee_id)
            rows = session.execute(
                select(EmployeeService, LineService, Service)
                .join(
                    LineService,
                    (LineService.line_id == EmployeeService.line_id)
                    & (LineService.service_id == EmployeeService.service_id)
                    & (LineService.tenant_id == EmployeeService.tenant_id),
                )
                .join(
                    Service,
                    (Service.id == LineService.service_id)
                    & (Service.tenant_id == LineService.tenant_id),
                )
                .where(
                    EmployeeService.line_id == line_id,
                    EmployeeService.employee_id == employee_id,
                    EmployeeService.deleted_at.is_(None),
                    LineService.deleted_at.is_(None),
                    Service.deleted_at.is_(None),
                )
                .order_by(Service.name, Service.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [
                    EmployeeServiceResponse(
                        id=item.id,
                        employee_id=employee_id,
                        line_id=line_id,
                        service_id=item.service_id,
                        service_name=product.name,
                        is_active=item.is_active,
                        effective_active=all(
                            common.active(row)
                            for row in (item, offer, product, parent, employee, user, link)
                        ),
                    )
                    for item, offer, product in rows
                ],
                limit,
                offset,
            )
        return result

    def put_employee_service(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        line_id: UUID,
        employee_id: UUID,
        service_id: UUID,
        payload: AssignmentWrite,
    ) -> EmployeeServiceResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("staff.assign", line_id=line_id)
            parent, product = common.line(session, line_id), common.service(session, service_id)
            employee, user = common.employee(session, employee_id)
            link, offer = (
                common.employee_line(session, line_id, employee_id),
                common.offer(session, line_id, service_id),
            )
            if payload.is_active:
                common.require_active(parent, product, employee, user, link, offer)
            row = session.scalar(
                select(EmployeeService).where(
                    EmployeeService.line_id == line_id,
                    EmployeeService.employee_id == employee_id,
                    EmployeeService.service_id == service_id,
                )
            )
            previous = row.is_active if row else None
            if row is None:
                row = EmployeeService(
                    tenant_id=context.tenant_id,
                    line_id=line_id,
                    employee_id=employee_id,
                    service_id=service_id,
                )
                session.add(row)
            elif not payload.is_active and row.is_active:
                require_no_upcoming_bookings(
                    session, line_id=line_id, employee_id=employee_id, service_id=service_id
                )
            row.is_active, row.deleted_at = payload.is_active, None
            session.flush()
            record_change(
                session,
                context,
                identity.user.id,
                "employee_service.saved",
                "employee_service",
                row.id,
                {
                    "line_id": str(line_id),
                    "employee_id": str(employee_id),
                    "service_id": str(service_id),
                    "is_active": {"before": previous, "after": row.is_active},
                },
            )
            result = EmployeeServiceResponse(
                id=row.id,
                line_id=line_id,
                employee_id=employee_id,
                service_id=service_id,
                is_active=row.is_active,
                service_name=product.name,
                effective_active=all(
                    common.active(item)
                    for item in (row, parent, product, employee, user, link, offer)
                ),
            )
        return result

    def delete_employee_service(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        line_id: UUID,
        employee_id: UUID,
        service_id: UUID,
    ) -> None:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("staff.assign", line_id=line_id)
            common.line(session, line_id)
            row = session.scalar(
                select(EmployeeService).where(
                    EmployeeService.line_id == line_id,
                    EmployeeService.employee_id == employee_id,
                    EmployeeService.service_id == service_id,
                    EmployeeService.deleted_at.is_(None),
                )
            )
            if row is None:
                raise common.missing()
            require_no_upcoming_bookings(
                session, line_id=line_id, employee_id=employee_id, service_id=service_id
            )
            row.is_active, row.deleted_at = False, datetime.now(UTC)
            record_change(
                session,
                context,
                identity.user.id,
                "employee_service.deleted",
                "employee_service",
                row.id,
                {
                    "line_id": str(line_id),
                    "employee_id": str(employee_id),
                    "service_id": str(service_id),
                },
            )

    def public_employees(
        self, context: AuthContext, line_id: UUID, service_id: UUID, limit: int, offset: int
    ) -> Page[PublicEmployee]:
        with common.public_catalog(self.sessions.database, context) as session:
            parent, product = common.line(session, line_id), common.service(session, service_id)
            offer = common.offer(session, line_id, service_id)
            if not all(common.active(row) for row in (parent, product, offer)):
                raise common.missing()
            rows = session.scalars(
                select(EmployeeProfile)
                .join(
                    User,
                    (User.id == EmployeeProfile.user_id)
                    & (User.tenant_id == EmployeeProfile.tenant_id),
                )
                .join(
                    EmployeeLine,
                    (EmployeeLine.employee_id == EmployeeProfile.id)
                    & (EmployeeLine.tenant_id == EmployeeProfile.tenant_id),
                )
                .join(
                    EmployeeService,
                    (EmployeeService.employee_id == EmployeeLine.employee_id)
                    & (EmployeeService.line_id == EmployeeLine.line_id)
                    & (EmployeeService.tenant_id == EmployeeLine.tenant_id),
                )
                .where(
                    EmployeeLine.line_id == line_id,
                    EmployeeService.service_id == service_id,
                    EmployeeProfile.deleted_at.is_(None),
                    EmployeeProfile.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                    EmployeeLine.deleted_at.is_(None),
                    EmployeeLine.is_active.is_(True),
                    EmployeeService.deleted_at.is_(None),
                    EmployeeService.is_active.is_(True),
                )
                .order_by(EmployeeProfile.public_name, EmployeeProfile.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [PublicEmployee.model_validate(row) for row in rows], limit, offset
            )
        return result
