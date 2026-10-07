from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.modules.access.models import RoleAssignment
from app.modules.catalog import common
from app.modules.catalog.models import Line, LineService, Service
from app.modules.catalog.schemas import (
    BookingSettings,
    LineCreate,
    LineResponse,
    LineUpdate,
    OfferResponse,
    OfferWrite,
    Page,
    PublicOfferResponse,
    ServiceCreate,
    ServiceResponse,
    ServiceUpdate,
)
from app.modules.identity.context import AuthContext
from app.modules.identity.models import User
from app.modules.identity.sessions import SessionService
from app.modules.scheduling.coordination import require_no_upcoming_bookings
from app.modules.scheduling.engine import settings as calendar_settings
from app.modules.tenancy.management import record_change
from app.modules.workforce.models import EmployeeLine, EmployeeService


class CatalogService:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions

    def booking_settings(self, context: AuthContext) -> BookingSettings:
        with common.public_catalog(self.sessions.database, context) as session:
            salon, policy, _ = calendar_settings(session)
            return BookingSettings(
                timezone=salon.timezone,
                today=datetime.now(ZoneInfo(salon.timezone)).date().isoformat(),
                booking_horizon_days=policy.booking_horizon_days,
                cancel_before_minutes=policy.cancel_before_minutes,
            )

    def public_services(
        self, context: AuthContext, limit: int, offset: int
    ) -> Page[ServiceResponse]:
        with common.public_catalog(self.sessions.database, context) as session:
            offered = (
                select(LineService.service_id)
                .join(
                    Line,
                    (Line.id == LineService.line_id) & (Line.tenant_id == LineService.tenant_id),
                )
                .where(
                    Line.is_active.is_(True),
                    Line.deleted_at.is_(None),
                    LineService.is_active.is_(True),
                    LineService.deleted_at.is_(None),
                )
            )
            rows = session.scalars(
                select(Service)
                .where(
                    Service.is_active.is_(True),
                    Service.deleted_at.is_(None),
                    Service.id.in_(offered),
                )
                .order_by(Service.name, Service.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            return common.page([ServiceResponse.model_validate(row) for row in rows], limit, offset)

    def public_service_lines(
        self, context: AuthContext, service_id: UUID, limit: int, offset: int
    ) -> Page[PublicOfferResponse]:
        with common.public_catalog(self.sessions.database, context) as session:
            product = common.service(session, service_id)
            if not common.active(product):
                raise common.missing()
            rows = session.execute(
                select(LineService, Line)
                .join(
                    Line,
                    (Line.id == LineService.line_id) & (Line.tenant_id == LineService.tenant_id),
                )
                .where(
                    LineService.service_id == service_id,
                    LineService.is_active.is_(True),
                    LineService.deleted_at.is_(None),
                    Line.is_active.is_(True),
                    Line.deleted_at.is_(None),
                )
                .order_by(Line.name, Line.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            return common.page(
                [
                    PublicOfferResponse(
                        **common.offer_view(offer, line, product).model_dump(), line_name=line.name
                    )
                    for offer, line in rows
                ],
                limit,
                offset,
            )

    def lines(self, context: AuthContext, raw: str, limit: int, offset: int) -> Page[LineResponse]:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            allowed = common.scope_lines(identity.principal, common.CATALOG_ACCESS)
            statement = select(Line).where(Line.deleted_at.is_(None))
            if allowed is not None:
                statement = statement.where(Line.id.in_(allowed))
            rows = session.scalars(
                statement.order_by(Line.name, Line.id).offset(offset).limit(limit + 1)
            ).all()
            result = common.page([LineResponse.model_validate(row) for row in rows], limit, offset)
        return result

    def get_line(self, context: AuthContext, raw: str, identifier: UUID) -> LineResponse:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            common.require_any(identity.principal, common.CATALOG_ACCESS, identifier)
            result = LineResponse.model_validate(common.line(session, identifier))
        return result

    def create_line(
        self, context: AuthContext, raw: str, csrf: str, payload: LineCreate
    ) -> LineResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("catalog.manage")
            row = Line(tenant_id=context.tenant_id, **payload.model_dump())
            session.add(row)
            session.flush()
            record_change(
                session,
                context,
                identity.user.id,
                "line.created",
                "line",
                row.id,
                payload.model_dump(mode="json"),
            )
            result = LineResponse.model_validate(row)
        return result

    def update_line(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, payload: LineUpdate
    ) -> LineResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("catalog.manage", line_id=identifier)
            row = common.line(session, identifier)
            if payload.is_active is False and row.is_active:
                require_no_upcoming_bookings(session, line_id=row.id)
            before = LineResponse.model_validate(row).model_dump(mode="json")
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(row, key, value)
            result = LineResponse.model_validate(row)
            record_change(
                session,
                context,
                identity.user.id,
                "line.updated",
                "line",
                row.id,
                {"before": before, "after": result.model_dump(mode="json")},
            )
        return result

    def delete_line(self, context: AuthContext, raw: str, csrf: str, identifier: UUID) -> None:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("catalog.manage")
            row = common.line(session, identifier)
            require_no_upcoming_bookings(session, line_id=row.id)
            now = datetime.now(UTC)
            row.is_active, row.deleted_at = False, now
            for model in (LineService, EmployeeLine, EmployeeService):
                session.execute(
                    update(model)
                    .where(model.line_id == row.id, model.deleted_at.is_(None))
                    .values(is_active=False, deleted_at=now)
                )
            assigned = select(RoleAssignment.user_id).where(
                RoleAssignment.line_id == row.id, RoleAssignment.revoked_at.is_(None)
            )
            for user in session.scalars(
                select(User).where(User.id.in_(assigned)).order_by(User.id).with_for_update()
            ):
                self.sessions.revoke_credentials(session, user, now)
            session.execute(
                update(RoleAssignment)
                .where(RoleAssignment.line_id == row.id, RoleAssignment.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            record_change(session, context, identity.user.id, "line.deleted", "line", row.id)

    def services(
        self, context: AuthContext, raw: str, limit: int, offset: int
    ) -> Page[ServiceResponse]:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            common.scope_lines(identity.principal, common.CATALOG_ACCESS)
            rows = session.scalars(
                select(Service)
                .where(Service.deleted_at.is_(None))
                .order_by(Service.name, Service.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [ServiceResponse.model_validate(row) for row in rows], limit, offset
            )
        return result

    def get_service(self, context: AuthContext, raw: str, identifier: UUID) -> ServiceResponse:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            common.scope_lines(identity.principal, common.CATALOG_ACCESS)
            result = ServiceResponse.model_validate(common.service(session, identifier))
        return result

    def create_service(
        self, context: AuthContext, raw: str, csrf: str, payload: ServiceCreate
    ) -> ServiceResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("catalog.manage")
            row = Service(tenant_id=context.tenant_id, **payload.model_dump())
            session.add(row)
            session.flush()
            record_change(
                session,
                context,
                identity.user.id,
                "service.created",
                "service",
                row.id,
                payload.model_dump(mode="json"),
            )
            result = ServiceResponse.model_validate(row)
        return result

    def update_service(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, payload: ServiceUpdate
    ) -> ServiceResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("catalog.manage")
            row = common.service(session, identifier)
            if payload.is_active is False and row.is_active:
                require_no_upcoming_bookings(session, service_id=row.id)
            before = ServiceResponse.model_validate(row).model_dump(mode="json")
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(row, key, value)
            result = ServiceResponse.model_validate(row)
            record_change(
                session,
                context,
                identity.user.id,
                "service.updated",
                "service",
                row.id,
                {"before": before, "after": result.model_dump(mode="json")},
            )
        return result

    def delete_service(self, context: AuthContext, raw: str, csrf: str, identifier: UUID) -> None:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("catalog.manage")
            row = common.service(session, identifier)
            require_no_upcoming_bookings(session, service_id=row.id)
            now = datetime.now(UTC)
            row.is_active, row.deleted_at = False, now
            for model in (LineService, EmployeeService):
                session.execute(
                    update(model)
                    .where(model.service_id == row.id, model.deleted_at.is_(None))
                    .values(is_active=False, deleted_at=now)
                )
            record_change(session, context, identity.user.id, "service.deleted", "service", row.id)

    def offers(
        self, context: AuthContext, raw: str, line_id: UUID, limit: int, offset: int
    ) -> Page[OfferResponse]:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            common.require_any(identity.principal, common.CATALOG_ACCESS, line_id)
            parent = common.line(session, line_id)
            rows = session.execute(
                select(LineService, Service)
                .join(
                    Service,
                    (Service.id == LineService.service_id)
                    & (Service.tenant_id == LineService.tenant_id),
                )
                .where(
                    LineService.line_id == line_id,
                    LineService.deleted_at.is_(None),
                    Service.deleted_at.is_(None),
                )
                .order_by(Service.name, Service.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [common.offer_view(offer, parent, product) for offer, product in rows],
                limit,
                offset,
            )
        return result

    def put_offer(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        line_id: UUID,
        service_id: UUID,
        payload: OfferWrite,
    ) -> OfferResponse:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("catalog.manage", line_id=line_id)
            parent, product = common.line(session, line_id), common.service(session, service_id)
            if payload.is_active:
                common.require_active(parent, product)
            row = session.scalar(
                select(LineService).where(
                    LineService.line_id == line_id, LineService.service_id == service_id
                )
            )
            before = (
                common.offer_view(row, parent, product).model_dump(mode="json") if row else None
            )
            if row is None:
                row = LineService(
                    tenant_id=context.tenant_id, line_id=line_id, service_id=service_id
                )
                session.add(row)
            elif not payload.is_active and row.is_active:
                require_no_upcoming_bookings(session, line_id=line_id, service_id=service_id)
            for key, value in payload.model_dump().items():
                setattr(row, key, value)
            row.deleted_at = None
            session.flush()
            result = common.offer_view(row, parent, product)
            record_change(
                session,
                context,
                identity.user.id,
                "line_service.saved",
                "line_service",
                row.id,
                {"before": before, "after": result.model_dump(mode="json")},
            )
        return result

    def delete_offer(
        self, context: AuthContext, raw: str, csrf: str, line_id: UUID, service_id: UUID
    ) -> None:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("catalog.manage", line_id=line_id)
            common.line(session, line_id)
            row = common.offer(session, line_id, service_id)
            require_no_upcoming_bookings(session, line_id=line_id, service_id=service_id)
            now = datetime.now(UTC)
            row.is_active, row.deleted_at = False, now
            session.execute(
                update(EmployeeService)
                .where(
                    EmployeeService.line_id == line_id,
                    EmployeeService.service_id == service_id,
                    EmployeeService.deleted_at.is_(None),
                )
                .values(is_active=False, deleted_at=now)
            )
            record_change(
                session, context, identity.user.id, "line_service.deleted", "line_service", row.id
            )

    def public_lines(self, context: AuthContext, limit: int, offset: int) -> Page[LineResponse]:
        with common.public_catalog(self.sessions.database, context) as session:
            rows = session.scalars(
                select(Line)
                .where(Line.deleted_at.is_(None), Line.is_active.is_(True))
                .order_by(Line.name, Line.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page([LineResponse.model_validate(row) for row in rows], limit, offset)
        return result

    def public_offers(
        self, context: AuthContext, line_id: UUID, limit: int, offset: int
    ) -> Page[OfferResponse]:
        with common.public_catalog(self.sessions.database, context) as session:
            parent = common.line(session, line_id)
            if not common.active(parent):
                raise common.missing()
            rows = session.execute(
                select(LineService, Service)
                .join(
                    Service,
                    (Service.id == LineService.service_id)
                    & (Service.tenant_id == LineService.tenant_id),
                )
                .where(
                    LineService.line_id == line_id,
                    LineService.deleted_at.is_(None),
                    LineService.is_active.is_(True),
                    Service.deleted_at.is_(None),
                    Service.is_active.is_(True),
                )
                .order_by(Service.name, Service.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [common.offer_view(offer, parent, product) for offer, product in rows],
                limit,
                offset,
            )
        return result
