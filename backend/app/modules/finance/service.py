from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.access.service import Principal
from app.modules.appointments.models import Appointment
from app.modules.billing.models import Invoice, InvoiceItem
from app.modules.catalog.common import missing, page, scope_lines
from app.modules.catalog.schemas import Page
from app.modules.finance import queries
from app.modules.finance.schemas import (
    Breakdown,
    Daily,
    Dimension,
    Document,
    DocumentKind,
    InvoiceDocument,
    InvoiceLine,
    Report,
    Totals,
)
from app.modules.identity.context import AuthContext
from app.modules.identity.sessions import SessionService
from app.modules.tenancy.models import Salon


def parameters(
    session: Session,
    principal: Principal,
    start: date,
    end: date,
    is_test: bool,
    line: UUID | None,
) -> dict[str, object]:
    lines = scope_lines(principal, ("finance.read",))
    if end < start or (end - start).days >= 366:
        raise AppError("report_range", "Choose an inclusive range of at most 366 days.", 422)
    if line is not None and lines is not None and line not in lines:
        raise AppError("forbidden", "Access denied.", 403)
    zone = session.scalar(select(Salon.timezone))
    assert zone is not None
    return {
        "tenant": principal.tenant_id,
        "all_lines": lines is None,
        "lines": list(lines or []),
        "line": line,
        "is_test": is_test,
        "zone": zone,
        "since": datetime.combine(start, time.min, ZoneInfo(zone)).astimezone(UTC),
        "until": datetime.combine(end + timedelta(days=1), time.min, ZoneInfo(zone)).astimezone(
            UTC
        ),
    }


def totals(
    received: int, refunded: int, allocated_received: int, allocated_refunded: int
) -> Totals:
    return Totals(
        received=str(received),
        refunded=str(refunded),
        net=str(received - refunded),
        allocated_received=str(allocated_received),
        allocated_refunded=str(allocated_refunded),
        revenue=str(allocated_received - allocated_refunded),
        unallocated_net=str(received - refunded - allocated_received + allocated_refunded),
    )


class FinanceService:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions

    def report(
        self,
        context: AuthContext,
        raw: str,
        start: date,
        end: date,
        is_test: bool,
        line: UUID | None,
    ) -> Report:
        with self.sessions.authorized(context, raw) as (session, identity):
            params = parameters(session, identity.principal, start, end, is_test, line)
            rows = session.execute(text(queries.DAILY), params).mappings().all()
            by_day = {row["day"]: row for row in rows}
            sums = [0, 0, 0, 0]
            daily = []
            for n in range((end - start).days + 1):
                day = start + timedelta(days=n)
                row = by_day.get(day)
                values = [
                    int(row[k]) if row else 0
                    for k in (
                        "received",
                        "refunded",
                        "allocated_received",
                        "allocated_refunded",
                    )
                ]
                sums = [a + b for a, b in zip(sums, values, strict=True)]
                daily.append(Daily(day=day, **totals(*values).model_dump()))
            return Report(
                start=start,
                end=end,
                timezone=str(params["zone"]),
                is_test=is_test,
                generated_at=datetime.now(UTC),
                totals=totals(*sums),
                daily=daily,
            )

    def breakdown(
        self,
        context: AuthContext,
        raw: str,
        start: date,
        end: date,
        is_test: bool,
        line: UUID | None,
        dimension: Dimension,
        limit: int,
        offset: int,
    ) -> Page[Breakdown]:
        with self.sessions.authorized(context, raw) as (session, identity):
            params = parameters(session, identity.principal, start, end, is_test, line)
            identifier, name = queries.DIMENSIONS[dimension]
            query = (
                queries.ATTRIBUTED
                + f"""
                SELECT {identifier} AS id, max({name}) AS name,
                       sum(received) AS received, sum(refunded) AS refunded
                FROM attributed GROUP BY {identifier}
                ORDER BY sum(received) - sum(refunded) DESC, {identifier}
                LIMIT :limit OFFSET :offset
            """
            )
            rows = session.execute(
                text(query), {**params, "limit": limit + 1, "offset": offset}
            ).mappings()
            return page(
                [
                    Breakdown(
                        id=r["id"],
                        name=r["name"],
                        received=str(int(r["received"])),
                        refunded=str(int(r["refunded"])),
                        net=str(int(r["received"] - r["refunded"])),
                    )
                    for r in rows
                ],
                limit,
                offset,
            )

    def documents(
        self,
        context: AuthContext,
        raw: str,
        start: date,
        end: date,
        is_test: bool,
        line: UUID | None,
        kind: DocumentKind,
        limit: int,
        offset: int,
    ) -> Page[Document]:
        with self.sessions.authorized(context, raw) as (session, identity):
            params = parameters(session, identity.principal, start, end, is_test, line)
            query = (
                queries.SCOPED
                + queries.DOCUMENTS[kind]
                + " ORDER BY at DESC, id LIMIT :limit OFFSET :offset"
            )
            rows = session.execute(
                text(query), {**params, "limit": limit + 1, "offset": offset}
            ).mappings()
            return page(
                [
                    Document(
                        **{
                            **dict(r),
                            "amount": str(int(r["amount"])),
                            "refundable": str(int(r["refundable"]))
                            if r["refundable"] is not None
                            else None,
                        }
                    )
                    for r in rows
                ],
                limit,
                offset,
            )

    def invoice(self, context: AuthContext, raw: str, identifier: UUID) -> InvoiceDocument:
        with self.sessions.authorized(context, raw) as (session, identity):
            lines = scope_lines(identity.principal, ("finance.read",))
            query = (
                select(Invoice)
                .join(Appointment, Appointment.id == Invoice.appointment_id)
                .where(Invoice.id == identifier)
            )
            if lines is not None:
                query = query.where(Appointment.line_id.in_(lines))
            row = session.scalar(query)
            if row is None:
                raise missing()
            return InvoiceDocument(
                id=row.id,
                number=row.number,
                amount=str(row.total_amount),
                is_test=row.is_test,
                issued_at=row.issued_at,
                seller=str(row.seller_snapshot.get("name") or ""),
                buyer=str(row.buyer_snapshot.get("name") or ""),
                items=[
                    InvoiceLine(description=i.description, amount=str(i.amount))
                    for i in session.scalars(
                        select(InvoiceItem)
                        .where(InvoiceItem.invoice_id == row.id)
                        .order_by(InvoiceItem.position)
                    )
                ],
            )
