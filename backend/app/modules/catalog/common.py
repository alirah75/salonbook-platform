from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.database import Database
from app.modules.access.service import Principal
from app.modules.catalog.models import Line, LineService, Service
from app.modules.catalog.schemas import OfferResponse, Page
from app.modules.identity.context import AuthContext, require_active_context
from app.modules.identity.models import User
from app.modules.scheduling.coordination import lock_calendar
from app.modules.workforce.models import EmployeeLine, EmployeeProfile, EmployeeService

CATALOG_ACCESS = ("catalog.manage", "staff.assign")


def missing() -> AppError:
    return AppError("not_found", "Record unavailable in this salon.", 404)


def active(
    row: Line | Service | LineService | EmployeeProfile | EmployeeLine | EmployeeService | User,
) -> bool:
    return row.is_active and row.deleted_at is None


def require_active(
    *rows: Line | Service | LineService | EmployeeProfile | EmployeeLine | EmployeeService | User,
) -> None:
    if not all(active(row) for row in rows):
        raise AppError("inactive_parent", "Activate the associated resources first.", 409)


def scope_lines(principal: Principal, permissions: tuple[str, ...]) -> set[UUID] | None:
    grants = [g for g in principal.grants if g.permission in permissions]
    if not grants:
        raise AppError("forbidden", "Access denied.", 403)
    if any(g.scope == "TENANT" for g in grants):
        return None
    return {UUID(g.line_id) for g in grants if g.scope == "LINE"}


def require_any(principal: Principal, permissions: tuple[str, ...], line_id: UUID) -> None:
    lines = scope_lines(principal, permissions)
    if lines is not None and line_id not in lines:
        raise AppError("forbidden", "Access denied.", 403)


def line(session: Session, identifier: UUID) -> Line:
    row = session.scalar(select(Line).where(Line.id == identifier, Line.deleted_at.is_(None)))
    if row is None:
        raise missing()
    return row


def service(session: Session, identifier: UUID) -> Service:
    row = session.scalar(
        select(Service).where(Service.id == identifier, Service.deleted_at.is_(None))
    )
    if row is None:
        raise missing()
    return row


def employee(session: Session, identifier: UUID) -> tuple[EmployeeProfile, User]:
    row = session.execute(
        select(EmployeeProfile, User)
        .join(
            User,
            (User.id == EmployeeProfile.user_id) & (User.tenant_id == EmployeeProfile.tenant_id),
        )
        .where(EmployeeProfile.id == identifier, EmployeeProfile.deleted_at.is_(None))
    ).one_or_none()
    if row is None:
        raise missing()
    return row[0], row[1]


def offer(session: Session, line_id: UUID, service_id: UUID) -> LineService:
    row = session.scalar(
        select(LineService).where(
            LineService.line_id == line_id,
            LineService.service_id == service_id,
            LineService.deleted_at.is_(None),
        )
    )
    if row is None:
        raise missing()
    return row


def employee_line(session: Session, line_id: UUID, employee_id: UUID) -> EmployeeLine:
    row = session.scalar(
        select(EmployeeLine).where(
            EmployeeLine.line_id == line_id,
            EmployeeLine.employee_id == employee_id,
            EmployeeLine.deleted_at.is_(None),
        )
    )
    if row is None:
        raise missing()
    return row


def offer_view(item: LineService, parent: Line, product: Service) -> OfferResponse:
    return OfferResponse(
        id=item.id,
        line_id=item.line_id,
        service_id=item.service_id,
        service_name=product.name,
        description=product.description,
        price_amount=item.price_amount,
        currency=item.currency,
        duration_minutes=item.duration_minutes,
        buffer_before_minutes=item.buffer_before_minutes,
        buffer_after_minutes=item.buffer_after_minutes,
        is_free=item.is_free,
        is_active=item.is_active,
        effective_active=all(active(row) for row in (item, parent, product)),
    )


def page[T](items: Sequence[T], limit: int, offset: int) -> Page[T]:
    return Page(items=list(items[:limit]), limit=limit, offset=offset, has_more=len(items) > limit)


@contextmanager
def public_catalog(database: Database, context: AuthContext) -> Iterator[Session]:
    with database.transaction(context.tenant_id) as session:
        require_active_context(session, context)
        lock_calendar(session, context.tenant_id, shared=True)
        yield session
