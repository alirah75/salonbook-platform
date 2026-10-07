"""Trusted, offline control plane. Never constructed with API runtime credentials."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.base import JsonObject
from app.db.schema import REQUIRED_SCHEMA_REVISION
from app.modules.access.models import Role, RoleAssignment
from app.modules.access.service import provision_roles
from app.modules.identity.models import CustomerProfile, User
from app.modules.identity.schemas import InputModel, RegisterInput
from app.modules.identity.security import Security
from app.modules.identity.sessions import SessionService
from app.modules.operations.models import PlatformAuditLog
from app.modules.tenancy.locks import tenant_lock
from app.modules.tenancy.models import CalendarControl, Salon, SalonSettings, TenantDomain
from app.modules.tenancy.schemas import Name, SalonResponse


def canonical_hostname(value: str) -> str:
    hostname = value.strip().lower().rstrip(".")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("Invalid hostname.") from None
    if len(hostname) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in hostname.split(".")
    ):
        raise ValueError("Use a hostname without scheme, port, path or wildcard.")
    return hostname


class TenantCreate(InputModel):
    name: Name
    hostname: str
    manager: RegisterInput
    timezone: Literal["Asia/Tehran"] = "Asia/Tehran"

    @field_validator("hostname")
    @classmethod
    def hostname_valid(cls, value: str) -> str:
        return canonical_hostname(value)


class OperationReason(InputModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("An operator reason is required.")
        return value.strip()


class TenantAdministration:
    def __init__(self, engine: Engine, security: Security, actor_id: UUID | None = None) -> None:
        self.engine, self.security = engine, security
        self.actor_id = actor_id

    @contextmanager
    def transaction(self, tenant: UUID) -> Iterator[Session]:
        with (
            Session(self.engine, autoflush=False, expire_on_commit=False) as session,
            session.begin(),
        ):
            if (
                session.scalar(text("SELECT version_num FROM public.app_schema_revision"))
                != REQUIRED_SCHEMA_REVISION
            ):
                raise AppError(
                    "schema_revision_mismatch", "Upgrade the database before administration.", 503
                )
            # An explicit privileged connection is required; the API role fails closed here.
            if not session.scalar(
                text(
                    "SELECT has_table_privilege(current_user, 'tenant_domains', 'INSERT') AND has_table_privilege(current_user, 'platform_audit_logs', 'INSERT')"
                )
            ):
                raise AppError(
                    "control_plane_required", "Use dedicated control-plane credentials.", 403
                )
            session.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
            )
            tenant_lock(session, tenant, "lifecycle")
            tenant_lock(session, tenant, "management")
            yield session

    def audit(
        self,
        session: Session,
        tenant: UUID,
        action: str,
        reason: str,
        changes: JsonObject | None = None,
    ) -> None:
        checked = OperationReason(reason=reason)
        session.add(
            PlatformAuditLog(
                actor_id=self.actor_id,
                action=action,
                entity_id=tenant,
                event_data={
                    "reason": checked.reason,
                    "source": "platform_console" if self.actor_id else "trusted_operator",
                    "database_actor": str(session.scalar(text("SELECT session_user"))),
                    "changes": changes or {},
                },
            )
        )

    def create(self, payload: TenantCreate, reason: str, *, verified_local: bool = False) -> UUID:
        if verified_local and payload.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("Automatic verification is limited to a loopback preview.")
        encoded = self.security.hash_password(payload.manager.password.get_secret_value())
        tenant = uuid4()
        with self.transaction(tenant) as session:
            salon = Salon(id=tenant, name=payload.name, timezone=payload.timezone)
            session.add(salon)
            session.flush()
            session.add_all([SalonSettings(tenant_id=tenant), CalendarControl(tenant_id=tenant)])
            session.add(
                TenantDomain(
                    tenant_id=tenant,
                    hostname=payload.hostname,
                    is_active=verified_local,
                    verified_at=datetime.now(UTC) if verified_local else None,
                )
            )
            provision_roles(session, tenant)
            user = User(
                tenant_id=tenant,
                phone_normalized=payload.manager.phone,
                display_name=payload.manager.display_name,
                password_hash=encoded,
            )
            session.add(user)
            session.flush()
            session.add(
                CustomerProfile(tenant_id=tenant, user_id=user.id, contact_preference="NONE")
            )
            for role in session.scalars(
                select(Role).where(Role.code.in_(("customer", "salon_manager")))
            ):
                session.add(
                    RoleAssignment(
                        tenant_id=tenant, user_id=user.id, role_id=role.id, scope="TENANT"
                    )
                )
            self.audit(
                session,
                tenant,
                "tenant.created",
                reason,
                {"manager_id": str(user.id), "hostname": payload.hostname},
            )
        return tenant

    def show(self, tenant: UUID) -> SalonResponse:
        with self.transaction(tenant) as session:
            salon = session.get(Salon, tenant)
            if salon is None:
                raise AppError("not_found", "Salon unavailable.", 404)
            result = SalonResponse(
                id=salon.id, name=salon.name, timezone=salon.timezone, status=salon.status
            )
        return result

    def bootstrap_manager(self, tenant: UUID, user_id: UUID, reason: str) -> None:
        """Establish a first manager for an existing salon after operator identity review."""
        with self.transaction(tenant) as session:
            if session.get(Salon, tenant) is None:
                raise AppError("not_found", "Salon unavailable.", 404)
            available = session.scalar(
                select(User.id)
                .join(
                    RoleAssignment,
                    (RoleAssignment.user_id == User.id)
                    & (RoleAssignment.tenant_id == User.tenant_id),
                )
                .join(
                    Role,
                    (Role.id == RoleAssignment.role_id)
                    & (Role.tenant_id == RoleAssignment.tenant_id),
                )
                .where(
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.phone_normalized.is_not(None),
                    RoleAssignment.revoked_at.is_(None),
                    RoleAssignment.scope == "TENANT",
                    Role.is_system.is_(True),
                    Role.code == "salon_manager",
                    Role.deleted_at.is_(None),
                )
                .limit(1)
            )
            if available is not None:
                raise AppError(
                    "manager_exists",
                    "Use the salon's role-management API to appoint additional managers.",
                    409,
                )
            user = session.scalar(
                select(User).where(User.id == user_id, User.deleted_at.is_(None)).with_for_update()
            )
            if user is None or not user.is_active or user.phone_normalized is None:
                raise AppError("not_found", "Active mobile account unavailable in this salon.", 404)
            provision_roles(session, tenant)
            session.flush()
            role = session.scalar(
                select(Role).where(
                    Role.code == "salon_manager",
                    Role.is_system.is_(True),
                    Role.deleted_at.is_(None),
                )
            )
            if role is None:
                raise AppError("roles_unavailable", "System roles are not configured.", 409)
            session.add(
                RoleAssignment(tenant_id=tenant, user_id=user.id, role_id=role.id, scope="TENANT")
            )
            SessionService.revoke_credentials(session, user, datetime.now(UTC))
            self.audit(
                session, tenant, "tenant.manager_bootstrapped", reason, {"user_id": str(user.id)}
            )

    def status(
        self, tenant: UUID, status: Literal["ACTIVE", "SUSPENDED", "CLOSED"], reason: str
    ) -> None:
        if status not in ("ACTIVE", "SUSPENDED", "CLOSED"):
            raise ValueError("Invalid salon status.")
        with self.transaction(tenant) as session:
            salon = session.get(Salon, tenant)
            if salon is None:
                raise AppError("not_found", "Salon unavailable.", 404)
            if salon.status == "CLOSED" and status != "CLOSED":
                raise AppError("salon_closed", "A closed salon cannot be reactivated.", 409)
            if salon.status != status:
                previous_status = salon.status
                salon.status = status
                if status != "ACTIVE":
                    for user in session.scalars(select(User).order_by(User.id).with_for_update()):
                        SessionService.revoke_credentials(session, user, datetime.now(UTC))
                self.audit(
                    session,
                    tenant,
                    f"tenant.{status.lower()}",
                    reason,
                    {"status": {"before": previous_status, "after": status}},
                )

    def domain(
        self,
        tenant: UUID,
        hostname: str,
        operation: Literal["add", "activate", "disable"],
        reason: str,
    ) -> None:
        hostname = canonical_hostname(hostname)
        if operation not in ("add", "activate", "disable"):
            raise ValueError("Invalid domain operation.")
        with self.transaction(tenant) as session:
            if session.get(Salon, tenant) is None:
                raise AppError("not_found", "Salon unavailable.", 404)
            domain = session.scalar(
                select(TenantDomain)
                .where(TenantDomain.tenant_id == tenant, TenantDomain.hostname == hostname)
                .with_for_update()
            )
            if operation == "add":
                if domain is not None:
                    raise AppError("domain_exists", "Domain is already registered.", 409)
                session.add(TenantDomain(tenant_id=tenant, hostname=hostname, is_active=False))
            else:
                if domain is None:
                    raise AppError("not_found", "Domain unavailable.", 404)
                domain.is_active = operation == "activate"
                if domain.is_active:
                    # Trusted operator attests ownership/routing; this is not a DNS verifier.
                    domain.verified_at = datetime.now(UTC)
            self.audit(
                session, tenant, f"tenant.domain_{operation}", reason, {"hostname": hostname}
            )
