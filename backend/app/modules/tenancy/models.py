from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Mutable, Record, TenantRecord


class Salon(Record, Mutable, Base):
    __tablename__ = "salons"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')", name="status"),
    )
    name: Mapped[str] = mapped_column(String(160))
    timezone: Mapped[str] = mapped_column(String(80), server_default="Asia/Tehran")
    status: Mapped[str] = mapped_column(String(16), server_default="ACTIVE")


class TenantDomain(Record, Mutable, Base):
    """Control-plane registry: contains no customer or authentication data."""

    __tablename__ = "tenant_domains"
    __table_args__ = (
        UniqueConstraint("hostname"),
        CheckConstraint(
            "hostname = lower(hostname) AND hostname !~ '[/ :]' AND length(hostname) > 0",
            name="canonical_hostname",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("salons.id", ondelete="RESTRICT"))
    hostname: Mapped[str] = mapped_column(String(253))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class SalonSettings(TenantRecord, Mutable, Base):
    __tablename__ = "salon_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        CheckConstraint("hold_minutes BETWEEN 1 AND 60", name="hold_minutes"),
        CheckConstraint("slot_step_minutes BETWEEN 1 AND 120", name="slot_step"),
        CheckConstraint("no_show_grace_minutes BETWEEN 0 AND 240", name="no_show_grace"),
        CheckConstraint(
            "min_notice_minutes >= 0 AND booking_horizon_days BETWEEN 1 AND 366",
            name="booking_window",
        ),
        CheckConstraint(
            "cancel_before_minutes >= 0 AND max_services BETWEEN 1 AND 20 AND max_duration_minutes BETWEEN 1 AND 1440",
            name="booking_limits",
        ),
        CheckConstraint("currency = 'IRR'", name="currency"),
        CheckConstraint("policy_version > 0", name="policy_version"),
    )
    currency: Mapped[str] = mapped_column(String(3), server_default="IRR")
    hold_minutes: Mapped[int] = mapped_column(Integer, server_default="10")
    slot_step_minutes: Mapped[int] = mapped_column(Integer, server_default="15")
    min_notice_minutes: Mapped[int] = mapped_column(Integer, server_default="60")
    booking_horizon_days: Mapped[int] = mapped_column(Integer, server_default="90")
    cancel_before_minutes: Mapped[int] = mapped_column(Integer, server_default="1440")
    max_services: Mapped[int] = mapped_column(Integer, server_default="10")
    max_duration_minutes: Mapped[int] = mapped_column(Integer, server_default="720")
    policy_version: Mapped[int] = mapped_column(Integer, server_default="1")
    no_show_grace_minutes: Mapped[int] = mapped_column(Integer, server_default="15")


class CalendarControl(TenantRecord, Mutable, Base):
    """Stable row shared-lockable by bookings and exclusively locked by schedule edits."""

    __tablename__ = "calendar_controls"
    __table_args__ = (UniqueConstraint("tenant_id"), CheckConstraint("version > 0", name="version"))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
