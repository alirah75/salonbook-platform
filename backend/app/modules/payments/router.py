from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.modules.appointments.router import PRIVATE, Key, Limit, Offset
from app.modules.identity.dependencies import AuthDependency, ContextDependency, session_token
from app.modules.payments.schemas import (
    CreatePayment,
    CreditNoteView,
    Input,
    InvoiceView,
    PaymentView,
    RefundInput,
    RefundView,
    Simulation,
)
from app.modules.payments.service import PaymentService

router = APIRouter(prefix="/payments", tags=["Payments (test provider)"])


def payments(auth: AuthDependency) -> PaymentService:
    return PaymentService(auth.sessions)


PaymentDependency = Annotated[PaymentService, Depends(payments)]


@router.post("/mock-account", dependencies=PRIVATE)
def enable_mock(
    payload: Input, request: Request, context: ContextDependency, service: PaymentDependency
) -> dict[str, object]:
    return service.enable_mock(context, session_token(request), request.headers["x-csrf-token"])


@router.post("", response_model=PaymentView, status_code=201, dependencies=PRIVATE)
def create(
    payload: CreatePayment,
    key: Key,
    request: Request,
    context: ContextDependency,
    service: PaymentDependency,
) -> PaymentView:
    return service.create(
        context,
        session_token(request),
        request.headers["x-csrf-token"],
        payload.appointment_id,
        key,
    )


@router.get("", response_model=list[PaymentView])
def listing(
    appointment_id: UUID,
    request: Request,
    context: ContextDependency,
    service: PaymentDependency,
    limit: Limit = 25,
    offset: Offset = 0,
    newest_first: bool = False,
) -> list[PaymentView]:
    return service.list(
        context, session_token(request), appointment_id, limit, offset, newest_first=newest_first
    )


@router.get("/invoices/{appointment_id}", response_model=InvoiceView)
def invoice(
    appointment_id: UUID, request: Request, context: ContextDependency, service: PaymentDependency
) -> InvoiceView:
    return service.invoice(context, session_token(request), appointment_id)


@router.post(
    "/transactions/{identifier}/refunds",
    response_model=RefundView,
    status_code=201,
    dependencies=PRIVATE,
)
def refund(
    identifier: UUID,
    payload: RefundInput,
    key: Key,
    request: Request,
    context: ContextDependency,
    service: PaymentDependency,
) -> RefundView:
    return service.request_refund(
        context, session_token(request), request.headers["x-csrf-token"], identifier, key, payload
    )


@router.get("/refunds/{identifier}", response_model=RefundView)
def get_refund(
    identifier: UUID, request: Request, context: ContextDependency, service: PaymentDependency
) -> RefundView:
    return service.get_refund(context, session_token(request), identifier)


@router.get("/refunds/{identifier}/credit-note", response_model=CreditNoteView)
def credit_note(
    identifier: UUID, request: Request, context: ContextDependency, service: PaymentDependency
) -> CreditNoteView:
    return service.credit_note(context, session_token(request), identifier)


@router.post("/refunds/{identifier}/approve", response_model=RefundView, dependencies=PRIVATE)
def approve_refund(
    identifier: UUID,
    payload: Input,
    request: Request,
    context: ContextDependency,
    service: PaymentDependency,
) -> RefundView:
    return service.refund_action(
        context, session_token(request), request.headers["x-csrf-token"], identifier, "approve"
    )


@router.post("/refunds/{identifier}/cancel", response_model=RefundView, dependencies=PRIVATE)
def cancel_refund(
    identifier: UUID,
    payload: Input,
    request: Request,
    context: ContextDependency,
    service: PaymentDependency,
) -> RefundView:
    return service.refund_action(
        context, session_token(request), request.headers["x-csrf-token"], identifier, "cancel"
    )


@router.get("/{identifier}", response_model=PaymentView)
def get(
    identifier: UUID, request: Request, context: ContextDependency, service: PaymentDependency
) -> PaymentView:
    return service.get(context, session_token(request), identifier)


@router.get("/{identifier}/mock-checkout", response_model=PaymentView)
def checkout(
    identifier: UUID, request: Request, context: ContextDependency, service: PaymentDependency
) -> PaymentView:
    return service.get(context, session_token(request), identifier)


@router.post("/{identifier}/mock-checkout", response_model=PaymentView, dependencies=PRIVATE)
def simulate(
    identifier: UUID,
    payload: Simulation,
    request: Request,
    context: ContextDependency,
    service: PaymentDependency,
) -> PaymentView:
    return service.verify(
        context,
        session_token(request),
        request.headers["x-csrf-token"],
        identifier,
        payload.scenario,
    )


@router.post("/{identifier}/verify", response_model=PaymentView, dependencies=PRIVATE)
def verify(
    identifier: UUID,
    payload: Input,
    request: Request,
    context: ContextDependency,
    service: PaymentDependency,
) -> PaymentView:
    return service.verify(
        context, session_token(request), request.headers["x-csrf-token"], identifier
    )


@router.post("/{identifier}/callback", status_code=202)
def callback(
    identifier: UUID, context: ContextDependency, service: PaymentDependency
) -> dict[str, bool]:
    """Unsigned return only schedules a server-side inquiry; request success flags are ignored."""
    service.callback(context, identifier)
    return {"accepted": True}
