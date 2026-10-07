from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import AwareDatetime
from starlette.responses import JSONResponse

from app.db.enums import AppointmentStatus
from app.modules.appointments.idempotency import Outcome
from app.modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentResponse,
    CancelInput,
    HistoryResponse,
    ReasonInput,
    RescheduleInput,
    VersionInput,
)
from app.modules.appointments.service import AppointmentService
from app.modules.catalog.schemas import Page
from app.modules.identity.dependencies import (
    AuthDependency,
    ContextDependency,
    private_mutation,
    session_token,
)

router = APIRouter(prefix="/appointments", tags=["Appointments"])
PRIVATE = [Depends(private_mutation)]
Key = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]


def appointments(auth: AuthDependency) -> AppointmentService:
    return AppointmentService(auth.sessions)


AppointmentDependency = Annotated[AppointmentService, Depends(appointments)]


def response(outcome: Outcome) -> JSONResponse:
    return JSONResponse(
        outcome.body,
        status_code=outcome.status,
        headers={"Idempotency-Replayed": str(outcome.replayed).lower()},
    )


@router.get("", response_model=Page[AppointmentResponse])
def listing(
    request: Request,
    context: ContextDependency,
    service: AppointmentDependency,
    starts_from: AwareDatetime | None = None,
    starts_until: AwareDatetime | None = None,
    status: AppointmentStatus | None = None,
    line_id: UUID | None = None,
    employee_id: UUID | None = None,
    mine: bool = False,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[AppointmentResponse]:
    now = datetime.now(UTC)
    return service.list(
        context,
        session_token(request),
        starts_from or now - timedelta(days=30),
        starts_until or now + timedelta(days=90),
        limit,
        offset,
        status=status,
        line_id=line_id,
        employee_id=employee_id,
        mine=mine,
    )


@router.post("", response_model=AppointmentResponse, status_code=201, dependencies=PRIVATE)
def create(
    payload: AppointmentCreate,
    key: Key,
    request: Request,
    context: ContextDependency,
    service: AppointmentDependency,
) -> JSONResponse:
    return response(
        service.create(
            context, session_token(request), request.headers["x-csrf-token"], key, payload
        )
    )


@router.get("/{identifier}", response_model=AppointmentResponse)
def get(
    identifier: UUID, request: Request, context: ContextDependency, service: AppointmentDependency
) -> AppointmentResponse:
    return service.get(context, session_token(request), identifier)


@router.get("/{identifier}/history", response_model=Page[HistoryResponse])
def history(
    identifier: UUID,
    request: Request,
    context: ContextDependency,
    service: AppointmentDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[HistoryResponse]:
    return service.history(context, session_token(request), identifier, limit, offset)


@router.post("/{identifier}/confirm", response_model=AppointmentResponse, dependencies=PRIVATE)
def confirm(
    identifier: UUID,
    payload: VersionInput,
    key: Key,
    request: Request,
    context: ContextDependency,
    service: AppointmentDependency,
) -> JSONResponse:
    return response(
        service.change(
            context,
            session_token(request),
            request.headers["x-csrf-token"],
            key,
            identifier,
            "confirm",
            payload,
        )
    )


@router.post("/{identifier}/cancel", response_model=AppointmentResponse, dependencies=PRIVATE)
def cancel(
    identifier: UUID,
    payload: CancelInput,
    key: Key,
    request: Request,
    context: ContextDependency,
    service: AppointmentDependency,
) -> JSONResponse:
    return response(
        service.change(
            context,
            session_token(request),
            request.headers["x-csrf-token"],
            key,
            identifier,
            "cancel",
            payload,
        )
    )


@router.post("/{identifier}/reschedule", response_model=AppointmentResponse, dependencies=PRIVATE)
def reschedule(
    identifier: UUID,
    payload: RescheduleInput,
    key: Key,
    request: Request,
    context: ContextDependency,
    service: AppointmentDependency,
) -> JSONResponse:
    return response(
        service.change(
            context,
            session_token(request),
            request.headers["x-csrf-token"],
            key,
            identifier,
            "reschedule",
            payload,
        )
    )


@router.post("/{identifier}/complete", response_model=AppointmentResponse, dependencies=PRIVATE)
def complete(
    identifier: UUID,
    payload: ReasonInput,
    key: Key,
    request: Request,
    context: ContextDependency,
    service: AppointmentDependency,
) -> JSONResponse:
    return response(
        service.change(
            context,
            session_token(request),
            request.headers["x-csrf-token"],
            key,
            identifier,
            "complete",
            payload,
        )
    )


@router.post("/{identifier}/no-show", response_model=AppointmentResponse, dependencies=PRIVATE)
def no_show(
    identifier: UUID,
    payload: ReasonInput,
    key: Key,
    request: Request,
    context: ContextDependency,
    service: AppointmentDependency,
) -> JSONResponse:
    return response(
        service.change(
            context,
            session_token(request),
            request.headers["x-csrf-token"],
            key,
            identifier,
            "no_show",
            payload,
        )
    )
