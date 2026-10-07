from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.modules.catalog.schemas import (
    AssignmentWrite,
    EmployeeLineResponse,
    EmployeeResponse,
    EmployeeServiceResponse,
    Page,
    PublicEmployee,
)
from app.modules.identity.dependencies import (
    AuthDependency,
    ContextDependency,
    private_mutation,
    session_token,
)
from app.modules.tenancy.management import ManagementService
from app.modules.workforce.service import WorkforceService

router = APIRouter(tags=["Employees and assignments"])
PRIVATE = [Depends(private_mutation)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]


def workforce(auth: AuthDependency) -> WorkforceService:
    return WorkforceService(auth.sessions)


WorkforceDependency = Annotated[WorkforceService, Depends(workforce)]


@router.get("/employees", response_model=Page[EmployeeResponse])
def employees(
    request: Request,
    context: ContextDependency,
    service: WorkforceDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[EmployeeResponse]:
    return service.employees(context, session_token(request), limit, offset)


@router.delete("/employees/{identifier}", status_code=204, dependencies=PRIVATE)
def delete_employee(
    identifier: UUID, request: Request, context: ContextDependency, auth: AuthDependency
) -> None:
    ManagementService(auth.sessions).delete_employee(
        context, session_token(request), request.headers["x-csrf-token"], identifier
    )


@router.get("/lines/{line_id}/employee-candidates", response_model=Page[PublicEmployee])
def candidates(
    line_id: UUID,
    request: Request,
    context: ContextDependency,
    service: WorkforceDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[PublicEmployee]:
    return service.candidates(context, session_token(request), line_id, limit, offset)


@router.get("/lines/{line_id}/employees", response_model=Page[EmployeeLineResponse])
def line_employees(
    line_id: UUID,
    request: Request,
    context: ContextDependency,
    service: WorkforceDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[EmployeeLineResponse]:
    return service.line_employees(context, session_token(request), line_id, limit, offset)


@router.put(
    "/lines/{line_id}/employees/{employee_id}",
    response_model=EmployeeLineResponse,
    dependencies=PRIVATE,
)
def put_line_employee(
    line_id: UUID,
    employee_id: UUID,
    payload: AssignmentWrite,
    request: Request,
    context: ContextDependency,
    service: WorkforceDependency,
) -> EmployeeLineResponse:
    return service.put_line_employee(
        context,
        session_token(request),
        request.headers["x-csrf-token"],
        line_id,
        employee_id,
        payload,
    )


@router.delete("/lines/{line_id}/employees/{employee_id}", status_code=204, dependencies=PRIVATE)
def delete_line_employee(
    line_id: UUID,
    employee_id: UUID,
    request: Request,
    context: ContextDependency,
    service: WorkforceDependency,
) -> None:
    service.delete_line_employee(
        context, session_token(request), request.headers["x-csrf-token"], line_id, employee_id
    )


@router.get(
    "/lines/{line_id}/employees/{employee_id}/services",
    response_model=Page[EmployeeServiceResponse],
)
def employee_services(
    line_id: UUID,
    employee_id: UUID,
    request: Request,
    context: ContextDependency,
    service: WorkforceDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[EmployeeServiceResponse]:
    return service.employee_services(
        context, session_token(request), line_id, employee_id, limit, offset
    )


@router.put(
    "/lines/{line_id}/employees/{employee_id}/services/{service_id}",
    response_model=EmployeeServiceResponse,
    dependencies=PRIVATE,
)
def put_employee_service(
    line_id: UUID,
    employee_id: UUID,
    service_id: UUID,
    payload: AssignmentWrite,
    request: Request,
    context: ContextDependency,
    service: WorkforceDependency,
) -> EmployeeServiceResponse:
    return service.put_employee_service(
        context,
        session_token(request),
        request.headers["x-csrf-token"],
        line_id,
        employee_id,
        service_id,
        payload,
    )


@router.delete(
    "/lines/{line_id}/employees/{employee_id}/services/{service_id}",
    status_code=204,
    dependencies=PRIVATE,
)
def delete_employee_service(
    line_id: UUID,
    employee_id: UUID,
    service_id: UUID,
    request: Request,
    context: ContextDependency,
    service: WorkforceDependency,
) -> None:
    service.delete_employee_service(
        context,
        session_token(request),
        request.headers["x-csrf-token"],
        line_id,
        employee_id,
        service_id,
    )


@router.get(
    "/catalog/lines/{line_id}/services/{service_id}/employees",
    response_model=Page[PublicEmployee],
    tags=["Public catalog"],
)
def public_employees(
    line_id: UUID,
    service_id: UUID,
    context: ContextDependency,
    service: WorkforceDependency,
    limit: Limit = 25,
    offset: Offset = 0,
) -> Page[PublicEmployee]:
    return service.public_employees(context, line_id, service_id, limit, offset)
