from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.modules.identity.schemas import InputModel, RegisterInput

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
RoleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
RoleCode = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,79}$")]


class SalonUpdate(InputModel):
    name: Name


class SalonResponse(BaseModel):
    id: UUID
    name: str
    timezone: str
    status: str


class ProfileUpdate(InputModel):
    display_name: Name


class UserCreate(RegisterInput):
    kind: Literal["customer", "employee"] = "customer"


class UserUpdate(InputModel):
    display_name: Name | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def nonempty(self) -> UserUpdate:
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("Provide at least one non-null change.")
        return self


class EmployeeUpdate(InputModel):
    public_name: Name
    is_active: bool = True


class EmployeeResponse(BaseModel):
    id: UUID
    public_name: str
    is_active: bool


class AssignmentResponse(BaseModel):
    id: UUID
    role_id: UUID
    code: str
    scope: str
    line_id: UUID | None


class ManagedUser(BaseModel):
    id: UUID
    phone: str | None
    phone_verified: bool
    display_name: str
    is_active: bool
    created_at: datetime
    customer_id: UUID | None
    employee: EmployeeResponse | None
    assignments: list[AssignmentResponse]


class UserPage(BaseModel):
    items: list[ManagedUser]
    limit: int
    offset: int
    has_more: bool


class RoleWrite(InputModel):
    name: RoleName
    permissions: list[str] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_permissions(self) -> RoleWrite:
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("Permissions must be unique.")
        return self


class RoleCreate(RoleWrite):
    code: RoleCode


class RoleResponse(BaseModel):
    id: UUID
    code: str
    name: str
    is_system: bool
    permissions: list[str]


class PermissionResponse(BaseModel):
    code: str
    description: str


class AssignmentCreate(InputModel):
    role_id: UUID
    scope: Literal["TENANT", "LINE"] = "TENANT"
    line_id: UUID | None = None

    @model_validator(mode="after")
    def correct_scope(self) -> AssignmentCreate:
        if (self.scope == "LINE") != (self.line_id is not None):
            raise ValueError("Only a LINE assignment requires line_id.")
        return self
