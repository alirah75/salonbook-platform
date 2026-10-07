from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Mutable, TenantRecord, enum_type, tenant_fk
from app.db.enums import BlockKind, BlockStatus, CalendarScope, DayOverrideMode


class Calendar(TenantRecord, Mutable, Base):
    __tablename__ = "calendars"
    __table_args__ = (
        tenant_fk("line_id", "lines"),
        tenant_fk("employee_id", "employee_profiles"),
        tenant_fk(("employee_id", "line_id"), "employee_lines", ("employee_id", "line_id")),
        UniqueConstraint(
            "tenant_id", "scope", "line_id", "employee_id", postgresql_nulls_not_distinct=True
        ),
        CheckConstraint(
            "(scope = 'SALON' AND line_id IS NULL AND employee_id IS NULL) OR (scope = 'LINE' AND line_id IS NOT NULL AND employee_id IS NULL) OR (scope = 'EMPLOYEE' AND line_id IS NULL AND employee_id IS NOT NULL) OR (scope = 'EMPLOYEE_LINE' AND line_id IS NOT NULL AND employee_id IS NOT NULL)",
            name="scope_target",
        ),
    )
    scope: Mapped[CalendarScope] = mapped_column(enum_type(CalendarScope, "calendar_scope"))
    line_id: Mapped[UUID | None]
    employee_id: Mapped[UUID | None]


class WeeklyPeriod(TenantRecord, Mutable, Base):
    """Open period or recurring break. Overnight shifts are split at midnight."""

    __tablename__ = "weekly_periods"
    __table_args__ = (
        tenant_fk("calendar_id", "calendars"),
        CheckConstraint("kind IN ('OPEN', 'BREAK')", name="kind"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),
        CheckConstraint(
            "start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440", name="minutes"
        ),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="effective_dates"),
        UniqueConstraint(
            "tenant_id",
            "calendar_id",
            "kind",
            "weekday",
            "start_minute",
            "end_minute",
            "valid_from",
        ),
    )
    calendar_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(8), server_default="OPEN")
    weekday: Mapped[int] = mapped_column(Integer)
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)


class DayOverride(TenantRecord, Mutable, Base):
    __tablename__ = "day_overrides"
    __table_args__ = (
        tenant_fk("calendar_id", "calendars"),
        UniqueConstraint("tenant_id", "calendar_id", "local_date"),
        UniqueConstraint("tenant_id", "id", "mode"),
    )
    calendar_id: Mapped[UUID]
    local_date: Mapped[date] = mapped_column(Date)
    mode: Mapped[DayOverrideMode] = mapped_column(enum_type(DayOverrideMode, "day_override_mode"))
    reason: Mapped[str | None] = mapped_column(String(300))


class SpecialPeriod(TenantRecord, Mutable, Base):
    __tablename__ = "special_periods"
    __table_args__ = (
        tenant_fk(("override_id", "override_mode"), "day_overrides", ("id", "mode")),
        CheckConstraint("override_mode = 'REPLACE'", name="replace_only"),
        CheckConstraint(
            "start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440", name="minutes"
        ),
        UniqueConstraint("tenant_id", "override_id", "start_minute", "end_minute"),
    )
    override_id: Mapped[UUID]
    override_mode: Mapped[str] = mapped_column(String(7), server_default="REPLACE")
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)


class ScheduleBlock(TenantRecord, Mutable, Base):
    __tablename__ = "schedule_blocks"
    __table_args__ = (
        tenant_fk("calendar_id", "calendars"),
        tenant_fk("requested_by_id", "users"),
        tenant_fk("approved_by_id", "users"),
        CheckConstraint("ends_at > starts_at", name="interval"),
        Index("ix_schedule_blocks_calendar_start", "tenant_id", "calendar_id", "starts_at"),
    )
    calendar_id: Mapped[UUID]
    kind: Mapped[BlockKind] = mapped_column(enum_type(BlockKind, "block_kind"))
    status: Mapped[BlockStatus] = mapped_column(
        enum_type(BlockStatus, "block_status"), server_default="REQUESTED"
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_by_id: Mapped[UUID | None]
    approved_by_id: Mapped[UUID | None]
    reason: Mapped[str | None] = mapped_column(Text)
