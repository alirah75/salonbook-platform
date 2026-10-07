from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.enums import AppointmentStatus
from app.modules.identity.schemas import InputModel


class StartInput(InputModel):
    starts_at: AwareDatetime
    employee_id: UUID | None = None

    @field_validator("starts_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        try:
            result = value.astimezone(UTC)
        except (ValueError, OverflowError) as exc:
            raise ValueError("Unsupported instant.") from exc
        if result.year >= 9999:
            raise ValueError("Unsupported booking year.")
        return result


class AppointmentCreate(StartInput):
    line_id: UUID
    service_ids: list[UUID] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len(self.service_ids) != len(set(self.service_ids)):
            raise ValueError("Services must be unique and ordered.")
        return self


class VersionInput(InputModel):
    expected_version: int = Field(ge=1)


class ReasonInput(VersionInput):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A reason is required.")
        return value.strip()


class CancelInput(ReasonInput):
    override_policy: bool = False


class RescheduleInput(StartInput, CancelInput):
    pass


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    service_id: UUID
    position: int
    service_name: str
    line_name: str
    employee_name: str
    original_employee_id: UUID
    duration_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int
    amount: int | None


class AppointmentResponse(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str
    employee_id: UUID
    employee_name: str
    line_id: UUID
    status: AppointmentStatus
    starts_at: datetime
    ends_at: datetime
    occupied_starts_at: datetime
    occupied_ends_at: datetime
    duration_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int
    total_amount: int | None
    currency: Literal["IRR"] = "IRR"
    is_test: bool
    hold_expires_at: datetime | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    version: int
    items: list[ItemResponse]


class HistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    action: str
    reason: str | None
    created_at: datetime
