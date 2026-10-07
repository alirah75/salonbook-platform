from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.modules.identity.dependencies import (
    AuthDependency,
    ContextDependency,
    private_mutation,
    session_token,
)
from app.modules.tenancy.management import ManagementService
from app.modules.tenancy.schemas import (
    AssignmentCreate,
    AssignmentResponse,
    EmployeeUpdate,
    ManagedUser,
    PermissionResponse,
    ProfileUpdate,
    RoleCreate,
    RoleResponse,
    RoleWrite,
    SalonResponse,
    SalonUpdate,
    UserCreate,
    UserPage,
    UserUpdate,
)

router = APIRouter(tags=["Salon and user management"])
PRIVATE = [Depends(private_mutation)]


def management(auth: AuthDependency) -> ManagementService:
    return ManagementService(auth.sessions)


ManagementDependency = Annotated[ManagementService, Depends(management)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]


@router.get("/salon", response_model=SalonResponse)
def salon(
    request: Request, context: ContextDependency, service: ManagementDependency
) -> SalonResponse:
    return service.salon(context, session_token(request))


@router.patch("/salon", response_model=SalonResponse, dependencies=PRIVATE)
def rename_salon(
    payload: SalonUpdate,
    request: Request,
    context: ContextDependency,
    service: ManagementDependency,
) -> SalonResponse:
    return service.rename_salon(
        context, session_token(request), request.headers["x-csrf-token"], payload
    )


@router.patch("/profile", response_model=ManagedUser, dependencies=PRIVATE)
def profile(
    payload: ProfileUpdate,
    request: Request,
    context: ContextDependency,
    service: ManagementDependency,
) -> ManagedUser:
    return service.profile(
        context, session_token(request), request.headers["x-csrf-token"], payload
    )


@router.get("/users", response_model=UserPage)
def users(
    request: Request,
    context: ContextDependency,
    service: ManagementDependency,
    limit: Limit = 25,
    offset: Offset = 0,
    kind: Literal["customer", "employee", "manager"] | None = None,
) -> UserPage:
    return service.users(context, session_token(request), limit=limit, offset=offset, kind=kind)


@router.get("/users/{identifier}", response_model=ManagedUser)
def user(
    identifier: UUID, request: Request, context: ContextDependency, service: ManagementDependency
) -> ManagedUser:
    return service.user(context, session_token(request), identifier)


@router.post("/users", response_model=ManagedUser, status_code=201, dependencies=PRIVATE)
def create_user(
    payload: UserCreate, request: Request, context: ContextDependency, service: ManagementDependency
) -> ManagedUser:
    return service.create_user(
        context, session_token(request), request.headers["x-csrf-token"], payload
    )


@router.patch("/users/{identifier}", response_model=ManagedUser, dependencies=PRIVATE)
def update_user(
    identifier: UUID,
    payload: UserUpdate,
    request: Request,
    context: ContextDependency,
    service: ManagementDependency,
) -> ManagedUser:
    return service.update_user(
        context, session_token(request), request.headers["x-csrf-token"], identifier, payload
    )


@router.put("/users/{identifier}/employee", response_model=ManagedUser, dependencies=PRIVATE)
def employee(
    identifier: UUID,
    payload: EmployeeUpdate,
    request: Request,
    context: ContextDependency,
    service: ManagementDependency,
) -> ManagedUser:
    return service.employee(
        context, session_token(request), request.headers["x-csrf-token"], identifier, payload
    )


@router.get("/permissions", response_model=list[PermissionResponse])
def permissions(
    request: Request, context: ContextDependency, service: ManagementDependency
) -> list[PermissionResponse]:
    return service.permissions(context, session_token(request))


@router.get("/roles", response_model=list[RoleResponse])
def roles(
    request: Request,
    context: ContextDependency,
    service: ManagementDependency,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[RoleResponse]:
    return service.roles(context, session_token(request), limit=limit, offset=offset)


@router.post("/roles", response_model=RoleResponse, status_code=201, dependencies=PRIVATE)
def create_role(
    payload: RoleCreate, request: Request, context: ContextDependency, service: ManagementDependency
) -> RoleResponse:
    return service.create_role(
        context, session_token(request), request.headers["x-csrf-token"], payload
    )


@router.put("/roles/{identifier}", response_model=RoleResponse, dependencies=PRIVATE)
def update_role(
    identifier: UUID,
    payload: RoleWrite,
    request: Request,
    context: ContextDependency,
    service: ManagementDependency,
) -> RoleResponse:
    return service.update_role(
        context, session_token(request), request.headers["x-csrf-token"], identifier, payload
    )


@router.delete("/roles/{identifier}", status_code=204, dependencies=PRIVATE)
def delete_role(
    identifier: UUID, request: Request, context: ContextDependency, service: ManagementDependency
) -> None:
    service.delete_role(
        context, session_token(request), request.headers["x-csrf-token"], identifier
    )


@router.post(
    "/users/{identifier}/roles",
    response_model=AssignmentResponse,
    status_code=201,
    dependencies=PRIVATE,
)
def assign_role(
    identifier: UUID,
    payload: AssignmentCreate,
    request: Request,
    context: ContextDependency,
    service: ManagementDependency,
) -> AssignmentResponse:
    return service.assign_role(
        context, session_token(request), request.headers["x-csrf-token"], identifier, payload
    )


@router.delete("/role-assignments/{identifier}", status_code=204, dependencies=PRIVATE)
def revoke_assignment(
    identifier: UUID, request: Request, context: ContextDependency, service: ManagementDependency
) -> None:
    service.revoke_assignment(
        context, session_token(request), request.headers["x-csrf-token"], identifier
    )
