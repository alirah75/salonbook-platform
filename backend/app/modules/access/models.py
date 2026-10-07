from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Mutable, Record, SoftDelete, TenantRecord, tenant_fk


class Permission(Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(100), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint("code ~ '^[a-z][a-z0-9_.]+$'", name="code"),)


class Role(TenantRecord, Mutable, SoftDelete, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class RolePermission(TenantRecord, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        tenant_fk("role_id", "roles"),
        UniqueConstraint("tenant_id", "role_id", "permission_code"),
    )
    role_id: Mapped[UUID]
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="RESTRICT")
    )


class RoleAssignment(TenantRecord, Mutable, Base):
    __tablename__ = "role_assignments"
    __table_args__ = (
        tenant_fk("role_id", "roles"),
        tenant_fk("user_id", "users"),
        tenant_fk("line_id", "lines"),
        tenant_fk("granted_by_id", "users"),
        CheckConstraint(
            "(scope = 'TENANT' AND line_id IS NULL) OR (scope = 'LINE' AND line_id IS NOT NULL)",
            name="scope",
        ),
        Index(
            "uq_role_assignments_active",
            "tenant_id",
            "user_id",
            "role_id",
            "scope",
            "line_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )
    user_id: Mapped[UUID]
    role_id: Mapped[UUID]
    scope: Mapped[str] = mapped_column(String(10))
    line_id: Mapped[UUID | None]
    granted_by_id: Mapped[UUID | None]
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformUser(Record, Mutable, Base):
    __tablename__ = "platform_users"
    __table_args__ = (
        UniqueConstraint("email_normalized"),
        UniqueConstraint("phone_normalized"),
        CheckConstraint(
            "phone_normalized IS NULL OR phone_normalized ~ '^\\+989[0-9]{9}$'",
            name="phone_normalized",
        ),
        CheckConstraint(
            "email_normalized = lower(trim(email_normalized))", name="email_normalized"
        ),
    )
    email_normalized: Mapped[str | None] = mapped_column(String(254))
    phone_normalized: Mapped[str | None] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(160), server_default="Platform administrator")
    password_hash: Mapped[str] = mapped_column(String(512))
    mfa_secret_ref: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class PlatformSession(Record, Mutable, Base):
    __tablename__ = "platform_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint(
            "octet_length(token_hash) = 32 AND octet_length(csrf_hash) = 32", name="hash_length"
        ),
        CheckConstraint("expires_at > created_at AND idle_expires_at <= expires_at", name="expiry"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformRole(Record, Mutable, Base):
    __tablename__ = "platform_roles"
    code: Mapped[str] = mapped_column(String(80), unique=True)


class PlatformRolePermission(Record, Base):
    __tablename__ = "platform_role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_code"),)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("platform_roles.id", ondelete="RESTRICT"))
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="RESTRICT")
    )


class PlatformRoleAssignment(Record, Base):
    __tablename__ = "platform_role_assignments"
    __table_args__ = (UniqueConstraint("role_id", "user_id"),)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("platform_roles.id", ondelete="RESTRICT"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"))


class PlatformAuthThrottle(Base):
    __tablename__ = "platform_auth_throttles"
    key: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (CheckConstraint("attempts > 0 AND octet_length(key) = 32", name="values"),)


class SupportGrant(TenantRecord, Base):
    """Control-plane-only, time-limited authorization; not an RLS bypass flag."""

    __tablename__ = "support_grants"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at AND length(trim(reason)) > 0", name="expiry_reason"
        ),
    )
    platform_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_users.id", ondelete="RESTRICT")
    )
    reason: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
