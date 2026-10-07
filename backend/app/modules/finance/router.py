from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.modules.appointments.router import Limit, Offset
from app.modules.catalog.schemas import Page
from app.modules.finance.schemas import (
    Breakdown,
    Dimension,
    Document,
    DocumentKind,
    InvoiceDocument,
    Report,
)
from app.modules.finance.service import FinanceService
from app.modules.identity.dependencies import AuthDependency, ContextDependency, session_token

router = APIRouter(prefix="/finance", tags=["Financial reports"])
Day = Annotated[date, Query(ge=date(2000, 1, 1), le=date(2100, 12, 31))]


def finance(auth: AuthDependency) -> FinanceService:
    return FinanceService(auth.sessions)


Service = Annotated[FinanceService, Depends(finance)]


@router.get("/report", response_model=Report)
def report(
    request: Request,
    context: ContextDependency,
    service: Service,
    start: Day,
    end: Day,
    is_test: bool = True,
    line_id: UUID | None = None,
) -> Report:
    return service.report(context, session_token(request), start, end, is_test, line_id)


@router.get("/breakdown", response_model=Page[Breakdown])
def breakdown(
    request: Request,
    context: ContextDependency,
    service: Service,
    start: Day,
    end: Day,
    dimension: Dimension,
    is_test: bool = True,
    line_id: UUID | None = None,
    limit: Limit = 24,
    offset: Offset = 0,
) -> Page[Breakdown]:
    return service.breakdown(
        context, session_token(request), start, end, is_test, line_id, dimension, limit, offset
    )


@router.get("/documents", response_model=Page[Document])
def documents(
    request: Request,
    context: ContextDependency,
    service: Service,
    start: Day,
    end: Day,
    kind: DocumentKind,
    is_test: bool = True,
    line_id: UUID | None = None,
    limit: Limit = 24,
    offset: Offset = 0,
) -> Page[Document]:
    return service.documents(
        context, session_token(request), start, end, is_test, line_id, kind, limit, offset
    )


@router.get("/invoices/{identifier}", response_model=InvoiceDocument)
def invoice(
    identifier: UUID, request: Request, context: ContextDependency, service: Service
) -> InvoiceDocument:
    return service.invoice(context, session_token(request), identifier)
