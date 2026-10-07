from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonObject, Mutable, Record, TenantRecord, enum_type, tenant_fk
from app.db.enums import JobStatus


class AuditLog(TenantRecord, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        tenant_fk("actor_id", "users"),
        CheckConstraint(
            "(actor_kind = 'USER' AND actor_id IS NOT NULL AND platform_actor_id IS NULL) OR (actor_kind = 'PLATFORM' AND actor_id IS NULL AND platform_actor_id IS NOT NULL) OR (actor_kind = 'SYSTEM' AND actor_id IS NULL AND platform_actor_id IS NULL)",
            name="actor",
        ),
        Index("ix_audit_logs_entity", "tenant_id", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_logs_actor", "tenant_id", "actor_id", "created_at"),
    )
    actor_kind: Mapped[str] = mapped_column(String(10))
    actor_id: Mapped[UUID | None]
    platform_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_users.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[UUID | None]
    request_id: Mapped[UUID | None]
    ip_address: Mapped[str | None] = mapped_column(INET)
    reason: Mapped[str | None] = mapped_column(Text)
    event_data: Mapped[JsonObject] = mapped_column(JSONB)


class PlatformAuditLog(Record, Base):
    __tablename__ = "platform_audit_logs"
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_users.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[UUID | None]
    event_data: Mapped[JsonObject] = mapped_column(JSONB)


class Notification(TenantRecord, Mutable, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        tenant_fk("user_id", "users"),
        UniqueConstraint("tenant_id", "user_id", "deduplication_key"),
        Index(
            "ix_notifications_unread",
            "tenant_id",
            "user_id",
            "created_at",
            postgresql_where=text("read_at IS NULL"),
        ),
    )
    user_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    deduplication_key: Mapped[str] = mapped_column(String(180))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(TenantRecord, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (UniqueConstraint("tenant_id", "deduplication_key"),)
    event_type: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[UUID]
    deduplication_key: Mapped[str] = mapped_column(String(180))
    payload: Mapped[JsonObject] = mapped_column(JSONB)


class BackgroundJob(TenantRecord, Mutable, Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        tenant_fk("outbox_event_id", "outbox_events"),
        UniqueConstraint("tenant_id", "deduplication_key"),
        CheckConstraint("attempts >= 0 AND max_attempts > 0", name="attempts"),
        CheckConstraint(
            "(status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_until IS NOT NULL) OR (status <> 'RUNNING' AND lease_owner IS NULL AND lease_until IS NULL)",
            name="lease",
        ),
        Index("ix_jobs_due", "tenant_id", "run_after", postgresql_where=text("status = 'PENDING'")),
        Index(
            "ix_jobs_expired_lease",
            "tenant_id",
            "lease_until",
            postgresql_where=text("status = 'RUNNING'"),
        ),
    )
    outbox_event_id: Mapped[UUID | None]
    kind: Mapped[str] = mapped_column(String(100))
    deduplication_key: Mapped[str] = mapped_column(String(180))
    payload: Mapped[JsonObject] = mapped_column(JSONB)
    status: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus, "job_status"), server_default="PENDING"
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="10")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
