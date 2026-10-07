from datetime import date, datetime, timedelta
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.db.enums import BlockKind, BlockStatus, CalendarScope, DayOverrideMode
from app.modules.identity.schemas import InputModel


class Period(InputModel):
    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(gt=0, le=1440)

    @model_validator(mode="after")
    def increasing(self) -> Self:
        if self.end_minute <= self.start_minute:
            raise ValueError("Split overnight periods at midnight.")
        return self


class WeeklyInput(Period):
    weekday: int = Field(ge=0, le=6, description="Monday=0, Sunday=6")
    kind: Literal["OPEN", "BREAK"] = "OPEN"
    valid_from: date
    valid_until: date | None = None

    @model_validator(mode="after")
    def effective_dates(self) -> Self:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until is exclusive and must follow valid_from.")
        return self


class WeeklyWrite(InputModel):
    periods: list[WeeklyInput] = Field(max_length=112)

    @model_validator(mode="after")
    def unique(self) -> Self:
        keys = [
            (p.weekday, p.kind, p.start_minute, p.end_minute, p.valid_from) for p in self.periods
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate weekly period.")
        return self


class CalendarCreate(InputModel):
    scope: CalendarScope
    line_id: UUID | None = None
    employee_id: UUID | None = None

    @model_validator(mode="after")
    def target(self) -> Self:
        if (self.line_id is not None) != (
            self.scope in (CalendarScope.LINE, CalendarScope.EMPLOYEE_LINE)
        ):
            raise ValueError("Invalid line target.")
        if (self.employee_id is not None) != (
            self.scope in (CalendarScope.EMPLOYEE, CalendarScope.EMPLOYEE_LINE)
        ):
            raise ValueError("Invalid employee target.")
        return self


class Record(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CalendarResponse(Record):
    id: UUID
    scope: CalendarScope
    line_id: UUID | None
    employee_id: UUID | None
    employee_name: str | None = None
    line_name: str | None = None


class WeeklyResponse(WeeklyInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class OverrideWrite(InputModel):
    mode: DayOverrideMode
    periods: list[Period] = Field(default_factory=list, max_length=16)
    reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def mode_periods(self) -> Self:
        if (self.mode == DayOverrideMode.CLOSED and self.periods) or (
            self.mode == DayOverrideMode.REPLACE and not self.periods
        ):
            raise ValueError("CLOSED has no periods; REPLACE needs openings.")
        keys = [(p.start_minute, p.end_minute) for p in self.periods]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate period.")
        return self


class OverrideResponse(OverrideWrite):
    id: UUID
    local_date: date


class BlockCreate(InputModel):
    kind: BlockKind
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.ends_at <= self.starts_at or self.ends_at - self.starts_at > timedelta(days=366):
            raise ValueError("Block must last between zero and 366 days.")
        if not self.reason.strip():
            raise ValueError("A reason is required.")
        return self


class BlockTransition(InputModel):
    status: Literal[BlockStatus.APPROVED, BlockStatus.REJECTED, BlockStatus.CANCELLED]


class BlockResponse(Record):
    id: UUID
    calendar_id: UUID
    kind: BlockKind
    status: BlockStatus
    starts_at: datetime
    ends_at: datetime
    reason: str | None


class SettingsWrite(InputModel):
    hold_minutes: int = Field(default=10, ge=1, le=60)
    cancel_before_minutes: int = Field(default=1440, ge=0, le=525600)
    no_show_grace_minutes: int = Field(default=15, ge=0, le=240)
    slot_step_minutes: int = Field(default=15, ge=1, le=120)
    min_notice_minutes: int = Field(default=60, ge=0, le=525600)
    booking_horizon_days: int = Field(default=90, ge=1, le=366)
    max_services: int = Field(default=10, ge=1, le=20)
    max_duration_minutes: int = Field(default=720, ge=1, le=1440)


class SettingsResponse(SettingsWrite):
    model_config = ConfigDict(from_attributes=True)
    timezone: str
    calendar_version: int


class AvailabilityQuery(InputModel):
    line_id: UUID
    service_ids: list[UUID] = Field(min_length=1, max_length=20)
    date_from: date
    date_until: date = Field(description="Exclusive; at most 7 days after date_from")
    employee_id: UUID | None = None
    assignment: Literal["all", "auto"] = "all"
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if not 1 <= (self.date_until - self.date_from).days <= 7:
            raise ValueError("Select one to seven days.")
        if len(self.service_ids) != len(set(self.service_ids)):
            raise ValueError("Services must be unique and ordered.")
        return self


class Slot(BaseModel):
    employee_id: UUID
    employee_name: str
    starts_at: datetime
    ends_at: datetime
    occupied_starts_at: datetime
    occupied_ends_at: datetime


class AvailabilityResponse(BaseModel):
    timezone: str
    calendar_version: int
    generated_at: datetime
    duration_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int
    total_amount: int
    currency: Literal["IRR"] = "IRR"
    items: list[Slot]
    limit: int
    offset: int
    has_more: bool
