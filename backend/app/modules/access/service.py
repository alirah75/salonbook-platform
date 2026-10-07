"""Deny by default: permissions carry tenant, line or explicit ownership scope."""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.access.models import Role, RoleAssignment, RolePermission

DEFAULT_ROLES: dict[str, tuple[str, ...]] = {
    "customer": (
        "profile.read",
        "profile.update",
        "salon.read",
        "session.manage",
        "appointment.create",
        "appointment.read_own",
        "appointment.cancel_own",
        "appointment.reschedule_own",
    ),
    "employee": (
        "profile.read",
        "profile.update",
        "salon.read",
        "session.manage",
        "schedule.read_own",
        "leave.request_own",
        "appointment.read_assigned",
        "appointment.finish_assigned",
    ),
    "line_manager": (
        "profile.read",
        "profile.update",
        "salon.read",
        "session.manage",
        "appointment.read",
        "appointment.manage",
        "catalog.manage",
        "staff.assign",
        "schedule.read",
        "schedule.manage",
        "finance.read",
        "audit.read",
    ),
    "salon_manager": (
        "profile.read",
        "profile.update",
        "salon.read",
        "salon.manage",
        "users.read",
        "users.manage",
        "roles.read",
        "session.manage",
        "appointment.create",
        "appointment.read_own",
        "appointment.cancel_own",
        "appointment.reschedule_own",
        "appointment.override",
        "appointment.read_assigned",
        "appointment.finish_assigned",
        "appointment.read",
        "appointment.manage",
        "catalog.manage",
        "staff.manage",
        "staff.assign",
        "schedule.read",
        "schedule.manage",
        "schedule.read_own",
        "leave.request_own",
        "finance.read",
        "payment.refund",
        "roles.manage",
        "audit.read",
    ),
}


@dataclass(frozen=True, order=True)
class Grant:
    permission: str
    scope: str
    line_id: str = ""


@dataclass(frozen=True)
class Principal:
    tenant_id: UUID
    user_id: UUID
    grants: frozenset[Grant]
    roles: frozenset[str]
    verified: bool

    @property
    def fingerprint(self) -> str:
        value = [(g.permission, g.scope, g.line_id) for g in sorted(self.grants)]
        return hashlib.sha256(json.dumps([sorted(self.roles), value]).encode()).hexdigest()

    @property
    def staff(self) -> bool:
        return bool(self.roles - {"customer"})

    def require(
        self, permission: str, *, line_id: UUID | None = None, owner_id: UUID | None = None
    ) -> None:
        if permission.endswith("_own") and owner_id != self.user_id:
            raise AppError("forbidden", "Access denied.", 403)
        if not any(
            g.permission == permission
            and (g.scope == "TENANT" or (line_id is not None and g.line_id == str(line_id)))
            for g in self.grants
        ):
            raise AppError("forbidden", "Access denied.", 403)

    def require_verified(self) -> None:
        if not self.verified:
            raise AppError("phone_verification_required", "Verify your mobile number first.", 403)


def load_principal(session: Session, tenant: UUID, user: UUID, verified: bool) -> Principal:
    assignments = session.execute(
        select(
            Role.code, RoleAssignment.scope, RoleAssignment.line_id, RolePermission.permission_code
        )
        .join(
            RoleAssignment,
            (RoleAssignment.tenant_id == Role.tenant_id) & (RoleAssignment.role_id == Role.id),
        )
        .outerjoin(
            RolePermission,
            (RolePermission.tenant_id == Role.tenant_id) & (RolePermission.role_id == Role.id),
        )
        .where(
            RoleAssignment.tenant_id == tenant,
            RoleAssignment.user_id == user,
            RoleAssignment.revoked_at.is_(None),
            Role.deleted_at.is_(None),
        )
    ).all()
    return Principal(
        tenant,
        user,
        frozenset(
            Grant(code, scope, str(line) if line else "")
            for _, scope, line, code in assignments
            if code
        ),
        frozenset(role for role, _, _, _ in assignments),
        verified,
    )


def provision_roles(session: Session, tenant: UUID) -> None:
    """Called only during trusted tenant provisioning, never by public registration."""
    for code, permissions in DEFAULT_ROLES.items():
        role = session.scalar(select(Role).where(Role.tenant_id == tenant, Role.code == code))
        if role is not None:
            continue
        role = Role(tenant_id=tenant, code=code, name=code, is_system=True)
        session.add(role)
        session.flush()
        session.add_all(
            RolePermission(tenant_id=tenant, role_id=role.id, permission_code=permission)
            for permission in permissions
        )
