from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

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
from app.modules.catalog.service import CatalogService
from app.modules.identity.dependencies import (
    AuthDependency,
    ContextDependency,
    private_mutation,
    session_token,
)

router = APIRouter(tags=["Lines and services"])
PRIVATE = [Depends(private_mutation)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]


def catalog(auth: AuthDependency) -> CatalogService:
    return CatalogService(auth.sessions)


CatalogDependency = Annotated[CatalogService, Depends(catalog)]


@router.get("/catalog/booking-settings", response_model=BookingSettings, tags=["Public catalog"])
def booking_settings(context: ContextDependency, service: CatalogDependency) -> BookingSettings:
    return service.booking_settings(context)


@router.get("/catalog/services", response_model=Page[ServiceResponse], tags=["Public catalog"])
def public_services(
    context: ContextDependency, service: CatalogDependency, limit: Limit = 25, offset: Offset = 0
) -> Page[ServiceResponse]:
    return service.public_services(context, limit, offset)


@router.get(
    "/catalog/services/{service_id}/lines",
    response_model=Page[PublicOfferResponse],
    tags=["Public catalog"],
)
def public_service_lines(
    service_id: UUID,
    context: ContextDependency,
    service: CatalogDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[PublicOfferResponse]:
    return service.public_service_lines(context, service_id, limit, offset)


@router.get("/lines", response_model=Page[LineResponse])
def lines(
    request: Request,
    context: ContextDependency,
    service: CatalogDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[LineResponse]:
    return service.lines(context, session_token(request), limit, offset)


@router.get("/lines/{identifier}", response_model=LineResponse)
def line(
    identifier: UUID, request: Request, context: ContextDependency, service: CatalogDependency
) -> LineResponse:
    return service.get_line(context, session_token(request), identifier)


@router.post("/lines", response_model=LineResponse, status_code=201, dependencies=PRIVATE)
def create_line(
    payload: LineCreate, request: Request, context: ContextDependency, service: CatalogDependency
) -> LineResponse:
    return service.create_line(
        context, session_token(request), request.headers["x-csrf-token"], payload
    )


@router.patch("/lines/{identifier}", response_model=LineResponse, dependencies=PRIVATE)
def update_line(
    identifier: UUID,
    payload: LineUpdate,
    request: Request,
    context: ContextDependency,
    service: CatalogDependency,
) -> LineResponse:
    return service.update_line(
        context, session_token(request), request.headers["x-csrf-token"], identifier, payload
    )


@router.delete("/lines/{identifier}", status_code=204, dependencies=PRIVATE)
def delete_line(
    identifier: UUID, request: Request, context: ContextDependency, service: CatalogDependency
) -> None:
    service.delete_line(
        context, session_token(request), request.headers["x-csrf-token"], identifier
    )


@router.get("/services", response_model=Page[ServiceResponse])
def services(
    request: Request,
    context: ContextDependency,
    service: CatalogDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[ServiceResponse]:
    return service.services(context, session_token(request), limit, offset)


@router.get("/services/{identifier}", response_model=ServiceResponse)
def get_service(
    identifier: UUID, request: Request, context: ContextDependency, service: CatalogDependency
) -> ServiceResponse:
    return service.get_service(context, session_token(request), identifier)


@router.post("/services", response_model=ServiceResponse, status_code=201, dependencies=PRIVATE)
def create_service(
    payload: ServiceCreate, request: Request, context: ContextDependency, service: CatalogDependency
) -> ServiceResponse:
    return service.create_service(
        context, session_token(request), request.headers["x-csrf-token"], payload
    )


@router.patch("/services/{identifier}", response_model=ServiceResponse, dependencies=PRIVATE)
def update_service(
    identifier: UUID,
    payload: ServiceUpdate,
    request: Request,
    context: ContextDependency,
    service: CatalogDependency,
) -> ServiceResponse:
    return service.update_service(
        context, session_token(request), request.headers["x-csrf-token"], identifier, payload
    )


@router.delete("/services/{identifier}", status_code=204, dependencies=PRIVATE)
def delete_service(
    identifier: UUID, request: Request, context: ContextDependency, service: CatalogDependency
) -> None:
    service.delete_service(
        context, session_token(request), request.headers["x-csrf-token"], identifier
    )


@router.get("/lines/{line_id}/services", response_model=Page[OfferResponse])
def offers(
    line_id: UUID,
    request: Request,
    context: ContextDependency,
    service: CatalogDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[OfferResponse]:
    return service.offers(context, session_token(request), line_id, limit, offset)


@router.put(
    "/lines/{line_id}/services/{service_id}", response_model=OfferResponse, dependencies=PRIVATE
)
def put_offer(
    line_id: UUID,
    service_id: UUID,
    payload: OfferWrite,
    request: Request,
    context: ContextDependency,
    service: CatalogDependency,
) -> OfferResponse:
    return service.put_offer(
        context,
        session_token(request),
        request.headers["x-csrf-token"],
        line_id,
        service_id,
        payload,
    )


@router.delete("/lines/{line_id}/services/{service_id}", status_code=204, dependencies=PRIVATE)
def delete_offer(
    line_id: UUID,
    service_id: UUID,
    request: Request,
    context: ContextDependency,
    service: CatalogDependency,
) -> None:
    service.delete_offer(
        context, session_token(request), request.headers["x-csrf-token"], line_id, service_id
    )


@router.get("/catalog/lines", response_model=Page[LineResponse], tags=["Public catalog"])
def public_lines(
    context: ContextDependency, service: CatalogDependency, limit: Limit = 25, offset: Offset = 0
) -> Page[LineResponse]:
    return service.public_lines(context, limit, offset)


@router.get(
    "/catalog/lines/{line_id}/services", response_model=Page[OfferResponse], tags=["Public catalog"]
)
def public_offers(
    line_id: UUID,
    context: ContextDependency,
    service: CatalogDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[OfferResponse]:
    return service.public_offers(context, line_id, limit, offset)
