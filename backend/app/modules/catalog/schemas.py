from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.identity.schemas import InputModel

LineName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ServiceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Slug = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
]
Code = Annotated[
    str, StringConstraints(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")
]
IntegerAmount = Annotated[int, Field(strict=True, ge=0, le=9_223_372_036_854_775_807)]


class LineCreate(InputModel):
    name: LineName
    slug: Slug
    is_active: bool = True


class PatchInput(InputModel):
    @model_validator(mode="after")
    def nonempty(self) -> PatchInput:
        if not self.model_fields_set:
            raise ValueError("Provide at least one change.")
        for key in self.model_fields_set - {"description"}:
            if getattr(self, key) is None:
                raise ValueError("Null is not a valid change.")
        return self


class LineUpdate(PatchInput):
    name: LineName | None = None
    slug: Slug | None = None
    is_active: bool | None = None


class ServiceCreate(InputModel):
    name: ServiceName
    code: Code
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool = True


class ServiceUpdate(PatchInput):
    name: ServiceName | None = None
    code: Code | None = None
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None


class OfferWrite(InputModel):
    price_amount: IntegerAmount
    currency: Literal["IRR"] = "IRR"
    duration_minutes: int = Field(strict=True, ge=1, le=1440)
    buffer_before_minutes: int = Field(default=0, strict=True, ge=0, le=240)
    buffer_after_minutes: int = Field(default=0, strict=True, ge=0, le=240)
    is_free: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def consistent_price(self) -> OfferWrite:
        if (self.price_amount == 0) != self.is_free:
            raise ValueError("Only an explicitly free service may have zero price.")
        return self


class AssignmentWrite(InputModel):
    is_active: bool = True


class RecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LineResponse(RecordResponse):
    id: UUID
    name: str
    slug: str
    is_active: bool


class ServiceResponse(RecordResponse):
    id: UUID
    name: str
    code: str
    description: str | None
    is_active: bool


class OfferResponse(RecordResponse):
    id: UUID
    line_id: UUID
    service_id: UUID
    service_name: str
    description: str | None
    price_amount: int
    currency: str
    duration_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int
    is_free: bool
    is_active: bool
    effective_active: bool


class PublicEmployee(RecordResponse):
    id: UUID
    public_name: str


class PublicOfferResponse(OfferResponse):
    line_name: str


class BookingSettings(BaseModel):
    timezone: str
    today: str
    booking_horizon_days: int
    cancel_before_minutes: int


class EmployeeResponse(PublicEmployee):
    user_id: UUID
    is_active: bool
    effective_active: bool


class EmployeeLineResponse(RecordResponse):
    id: UUID
    employee_id: UUID
    line_id: UUID
    public_name: str
    is_active: bool
    effective_active: bool


class EmployeeServiceResponse(RecordResponse):
    id: UUID
    employee_id: UUID
    line_id: UUID
    service_id: UUID
    service_name: str
    is_active: bool
    effective_active: bool


class Page[Item](BaseModel):
    items: list[Item]
    limit: int
    offset: int
    has_more: bool
