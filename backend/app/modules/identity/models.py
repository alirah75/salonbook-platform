from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Mutable, SoftDelete, TenantRecord, enum_type, tenant_fk
from app.db.enums import TokenPurpose


class User(TenantRecord, Mutable, SoftDelete, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email_normalized"),
        UniqueConstraint("tenant_id", "phone_normalized"),
        CheckConstraint(
            "phone_normalized IS NULL OR phone_normalized ~ '^\\+989[0-9]{9}$'",
            name="phone_normalized",
        ),
        CheckConstraint(
            "phone_verified_at IS NULL OR phone_normalized IS NOT NULL", name="phone_verification"
        ),
        CheckConstraint(
            "email_normalized = lower(trim(email_normalized)) AND position('@' in email_normalized) > 1",
            name="email_normalized",
        ),
        CheckConstraint("auth_version > 0", name="auth_version"),
    )
    email_normalized: Mapped[str | None] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(512))
    mfa_secret_ref: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(24))
    # Legacy phone is contact data only; never silently promote it to a login credential.
    phone_normalized: Mapped[str | None] = mapped_column(String(16))
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    auth_version: Mapped[int] = mapped_column(Integer, server_default="1")


class CustomerProfile(TenantRecord, Mutable, Base):
    __tablename__ = "customer_profiles"
    __table_args__ = (tenant_fk("user_id", "users"), UniqueConstraint("tenant_id", "user_id"))
    user_id: Mapped[UUID]
    contact_preference: Mapped[str] = mapped_column(String(32), server_default="NONE")


class Session(TenantRecord, Mutable, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        tenant_fk("user_id", "users"),
        UniqueConstraint("tenant_id", "token_hash"),
        CheckConstraint(
            "octet_length(token_hash) = 32 AND octet_length(csrf_hash) = 32", name="hash_lengths"
        ),
        CheckConstraint("expires_at > created_at AND idle_expires_at <= expires_at", name="expiry"),
        CheckConstraint("auth_version > 0", name="auth_version"),
        Index(
            "ix_sessions_expiry",
            "tenant_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )
    user_id: Mapped[UUID]
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_version: Mapped[int] = mapped_column(Integer)
    grants_fingerprint: Mapped[str] = mapped_column(String(64), server_default="")
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))


class AuthToken(TenantRecord, Base):
    __tablename__ = "auth_tokens"
    __table_args__ = (
        tenant_fk("user_id", "users"),
        UniqueConstraint("tenant_id", "token_hash"),
        CheckConstraint("octet_length(token_hash) = 32", name="hash_length"),
        CheckConstraint("expires_at > created_at", name="expiry"),
        CheckConstraint("subject_version > 0", name="subject_version"),
    )
    user_id: Mapped[UUID]
    purpose: Mapped[TokenPurpose] = mapped_column(enum_type(TokenPurpose, "token_purpose"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    subject_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthThrottle(TenantRecord, Mutable, Base):
    __tablename__ = "auth_throttles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "bucket_hash", "purpose"),
        CheckConstraint("attempts >= 0 AND octet_length(bucket_hash) = 32", name="bucket"),
        Index("ix_auth_throttles_expiry", "tenant_id", "expires_at"),
    )
    bucket_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    purpose: Mapped[str] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
