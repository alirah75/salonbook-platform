from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.modules.catalog.schemas import Page
from app.modules.identity.dependencies import (
    AuthDependency,
    ContextDependency,
    private_mutation,
    session_token,
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
    SettingsResponse,
    SettingsWrite,
    WeeklyResponse,
    WeeklyWrite,
)
from app.modules.scheduling.service import SchedulingService

router = APIRouter(prefix="/scheduling", tags=["Scheduling"])
PRIVATE = [Depends(private_mutation)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]


def scheduling(auth: AuthDependency) -> SchedulingService:
    return SchedulingService(auth.sessions)


SchedulingDependency = Annotated[SchedulingService, Depends(scheduling)]


@router.get("/availability", response_model=AvailabilityResponse)
def available(
    context: ContextDependency,
    service: SchedulingDependency,
    query: Annotated[AvailabilityQuery, Query()],
) -> AvailabilityResponse:
    return service.available(context, query)


@router.get("/settings", response_model=SettingsResponse)
def settings(
    request: Request, context: ContextDependency, service: SchedulingDependency
) -> SettingsResponse:
    return service.get_settings(context, session_token(request))


@router.put("/settings", response_model=SettingsResponse, dependencies=PRIVATE)
def save_settings(
    payload: SettingsWrite,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
) -> SettingsResponse:
    return service.save_settings(
        context, session_token(request), request.headers["x-csrf-token"], payload
    )


@router.get("/calendars", response_model=Page[CalendarResponse])
def calendars(
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[CalendarResponse]:
    return service.calendars(context, session_token(request), limit, offset)


@router.post("/calendars", response_model=CalendarResponse, status_code=201, dependencies=PRIVATE)
def create_calendar(
    payload: CalendarCreate,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
) -> CalendarResponse:
    return service.create_calendar(
        context, session_token(request), request.headers["x-csrf-token"], payload
    )


@router.get("/calendars/{identifier}/weekly", response_model=list[WeeklyResponse])
def weekly(
    identifier: UUID, request: Request, context: ContextDependency, service: SchedulingDependency
) -> list[WeeklyResponse]:
    return service.weekly(context, session_token(request), identifier)


@router.put(
    "/calendars/{identifier}/weekly", response_model=list[WeeklyResponse], dependencies=PRIVATE
)
def save_weekly(
    identifier: UUID,
    payload: WeeklyWrite,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
) -> list[WeeklyResponse]:
    return service.save_weekly(
        context, session_token(request), request.headers["x-csrf-token"], identifier, payload
    )


@router.get("/calendars/{identifier}/overrides", response_model=list[OverrideResponse])
def overrides(
    identifier: UUID,
    date_from: date,
    date_until: date,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
) -> list[OverrideResponse]:
    return service.overrides(context, session_token(request), identifier, date_from, date_until)


@router.put(
    "/calendars/{identifier}/overrides/{day}", response_model=OverrideResponse, dependencies=PRIVATE
)
def save_override(
    identifier: UUID,
    day: date,
    payload: OverrideWrite,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
) -> OverrideResponse:
    result = service.save_override(
        context, session_token(request), request.headers["x-csrf-token"], identifier, day, payload
    )
    assert result is not None
    return result


@router.delete("/calendars/{identifier}/overrides/{day}", status_code=204, dependencies=PRIVATE)
def remove_override(
    identifier: UUID,
    day: date,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
) -> None:
    service.save_override(
        context, session_token(request), request.headers["x-csrf-token"], identifier, day, None
    )


@router.get("/calendars/{identifier}/blocks", response_model=Page[BlockResponse])
def blocks(
    identifier: UUID,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[BlockResponse]:
    return service.blocks(context, session_token(request), identifier, limit, offset)


@router.post(
    "/calendars/{identifier}/blocks",
    response_model=BlockResponse,
    status_code=201,
    dependencies=PRIVATE,
)
def create_block(
    identifier: UUID,
    payload: BlockCreate,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
) -> BlockResponse:
    return service.create_block(
        context, session_token(request), request.headers["x-csrf-token"], identifier, payload
    )


@router.post(
    "/calendars/{identifier}/leave-requests",
    response_model=BlockResponse,
    status_code=201,
    dependencies=PRIVATE,
)
def request_leave(
    identifier: UUID,
    payload: BlockCreate,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
) -> BlockResponse:
    return service.create_block(
        context,
        session_token(request),
        request.headers["x-csrf-token"],
        identifier,
        payload,
        own=True,
    )


@router.patch("/blocks/{identifier}", response_model=BlockResponse, dependencies=PRIVATE)
def transition_block(
    identifier: UUID,
    payload: BlockTransition,
    request: Request,
    context: ContextDependency,
    service: SchedulingDependency,
) -> BlockResponse:
    return service.transition_block(
        context, session_token(request), request.headers["x-csrf-token"], identifier, payload
    )
