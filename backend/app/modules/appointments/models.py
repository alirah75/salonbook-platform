from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonObject, Mutable, TenantRecord, enum_type, tenant_fk
from app.db.enums import AppointmentStatus


class Appointment(TenantRecord, Mutable, Base):
    """The occupancy and reservation share a row: there is no second mutable status."""

    __tablename__ = "appointments"
    __table_args__ = (
        tenant_fk("customer_id", "customer_profiles"),
        tenant_fk(("employee_id", "line_id"), "employee_lines", ("employee_id", "line_id")),
        UniqueConstraint("tenant_id", "id", "line_id"),
        UniqueConstraint("tenant_id", "id", "total_amount", "currency", "is_test"),
        CheckConstraint(
            "ends_at > starts_at AND occupied_starts_at <= starts_at AND occupied_ends_at >= ends_at",
            name="interval",
        ),
        CheckConstraint(
            "duration_minutes > 0 AND ends_at = starts_at + duration_minutes * interval '1 minute'",
            name="duration",
        ),
        CheckConstraint(
            "buffer_before_minutes >= 0 AND buffer_after_minutes >= 0 AND occupied_starts_at = starts_at - buffer_before_minutes * interval '1 minute' AND occupied_ends_at = ends_at + buffer_after_minutes * interval '1 minute'",
            name="buffers",
        ),
        CheckConstraint(
            "total_amount >= 0 AND currency = 'IRR' AND version > 0", name="amount_currency_version"
        ),
        CheckConstraint(
            "status <> 'AWAITING_PAYMENT' OR (hold_expires_at IS NOT NULL AND hold_expires_at > created_at AND hold_expires_at <= starts_at AND confirmed_at IS NULL)",
            name="hold",
        ),
        CheckConstraint(
            "status NOT IN ('CONFIRMED', 'COMPLETED', 'NO_SHOW') OR confirmed_at IS NOT NULL",
            name="confirmation",
        ),
        ExcludeConstraint(
            ("tenant_id", "="),
            ("employee_id", "="),
            ("occupied_period", "&&"),
            name="ex_appointments_employee_period",
            using="gist",
            where=text("status IN ('AWAITING_PAYMENT', 'CONFIRMED', 'COMPLETED', 'NO_SHOW')"),
        ),
        Index(
            "uq_appointments_customer_hold",
            "tenant_id",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'AWAITING_PAYMENT'"),
        ),
        Index("ix_appointments_line_start", "tenant_id", "line_id", "starts_at"),
        Index("ix_appointments_customer_start", "tenant_id", "customer_id", "starts_at"),
        Index(
            "ix_appointments_expiring",
            "tenant_id",
            "hold_expires_at",
            postgresql_where=text("status = 'AWAITING_PAYMENT'"),
        ),
    )
    customer_id: Mapped[UUID]
    employee_id: Mapped[UUID]
    line_id: Mapped[UUID]
    status: Mapped[AppointmentStatus] = mapped_column(
        enum_type(AppointmentStatus, "appointment_status"), server_default="AWAITING_PAYMENT"
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occupied_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occupied_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occupied_period: Mapped[Range[datetime]] = mapped_column(
        TSTZRANGE,
        Computed("tstzrange(occupied_starts_at, occupied_ends_at, '[)'::text)", persisted=True),
    )
    duration_minutes: Mapped[int] = mapped_column(Integer)
    buffer_before_minutes: Mapped[int] = mapped_column(Integer, server_default="0")
    buffer_after_minutes: Mapped[int] = mapped_column(Integer, server_default="0")
    total_amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default="IRR")
    is_test: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    policy_snapshot: Mapped[JsonObject] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class AppointmentItem(TenantRecord, Base):
    """Immutable offer and original employee snapshot; rescheduling preserves it."""

    __tablename__ = "appointment_items"
    __table_args__ = (
        tenant_fk(("appointment_id", "line_id"), "appointments", ("id", "line_id")),
        tenant_fk(
            ("original_employee_id", "line_id", "service_id"),
            "employee_services",
            ("employee_id", "line_id", "service_id"),
        ),
        UniqueConstraint("tenant_id", "appointment_id", "position"),
        UniqueConstraint("tenant_id", "id", "appointment_id"),
        CheckConstraint(
            "position > 0 AND duration_minutes > 0 AND amount >= 0 AND buffer_before_minutes >= 0 AND buffer_after_minutes >= 0",
            name="values",
        ),
    )
    appointment_id: Mapped[UUID]
    original_employee_id: Mapped[UUID]
    line_id: Mapped[UUID]
    service_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    service_name: Mapped[str] = mapped_column(String(160))
    line_name: Mapped[str] = mapped_column(String(120))
    employee_name: Mapped[str] = mapped_column(String(160))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    buffer_before_minutes: Mapped[int] = mapped_column(Integer, server_default="0")
    buffer_after_minutes: Mapped[int] = mapped_column(Integer, server_default="0")
    amount: Mapped[int] = mapped_column(BigInteger)


class AppointmentHistory(TenantRecord, Base):
    __tablename__ = "appointment_history"
    __table_args__ = (tenant_fk("appointment_id", "appointments"), tenant_fk("actor_id", "users"))
    appointment_id: Mapped[UUID]
    actor_id: Mapped[UUID | None]
    action: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(Text)
    event_data: Mapped[JsonObject] = mapped_column(JSONB)


class IdempotencyRecord(TenantRecord, Mutable, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        tenant_fk("actor_id", "users"),
        UniqueConstraint("tenant_id", "actor_id", "operation", "key"),
        CheckConstraint("octet_length(request_hash) = 32", name="hash_length"),
        CheckConstraint(
            "state IN ('PROCESSING', 'COMPLETED') AND expires_at > created_at", name="state_expiry"
        ),
        CheckConstraint(
            "state <> 'COMPLETED' OR (response_status BETWEEN 200 AND 599 AND response_body IS NOT NULL)",
            name="completed_response",
        ),
        Index("ix_idempotency_expiry", "tenant_id", "expires_at"),
    )
    actor_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    state: Mapped[str] = mapped_column(String(16), server_default="PROCESSING")
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[JsonObject | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
