"""Tenant management. Every authorization check and mutation shares one transaction."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.base import JsonObject
from app.modules.access.models import Permission, Role, RoleAssignment, RolePermission
from app.modules.access.service import DEFAULT_ROLES, Grant, Principal, load_principal
from app.modules.catalog.models import Line
from app.modules.identity.context import AuthContext
from app.modules.identity.models import CustomerProfile, User
from app.modules.identity.sessions import Identity, SessionService
from app.modules.operations.models import AuditLog
from app.modules.scheduling.coordination import require_no_upcoming_bookings
from app.modules.tenancy.models import Salon
from app.modules.tenancy.schemas import (
    AssignmentCreate,
    AssignmentResponse,
    EmployeeResponse,
    EmployeeUpdate,
    ManagedUser,
    PermissionResponse,
    ProfileUpdate,
    RoleCreate,
    RoleResponse,
    RoleWrite,
    SalonResponse,
    SalonUpdate,
    UserCreate,
    UserPage,
    UserUpdate,
)
from app.modules.workforce.models import EmployeeLine, EmployeeProfile, EmployeeService


def missing() -> AppError:
    return AppError("not_found", "Record unavailable in this salon.", 404)


def delegation_ceiling(principal: Principal, grants: Sequence[Grant] | frozenset[Grant]) -> None:
    for grant in grants:
        if not any(
            own.permission == grant.permission
            and (own.scope == "TENANT" or (grant.scope == "LINE" and own.line_id == grant.line_id))
            for own in principal.grants
        ):
            raise AppError("delegation_denied", "Cannot delegate or manage higher privileges.", 403)


def record_change(
    session: Session,
    context: AuthContext,
    actor: UUID,
    action: str,
    entity: str,
    identifier: UUID,
    changes: JsonObject | None = None,
) -> None:
    session.add(
        AuditLog(
            tenant_id=context.tenant_id,
            actor_kind="USER",
            actor_id=actor,
            action=action,
            entity_type=entity,
            entity_id=identifier,
            request_id=context.request_id,
            ip_address=context.ip,
            event_data=changes or {},
        )
    )


def get_user(session: Session, identifier: UUID) -> User:
    user = session.scalar(
        select(User).where(User.id == identifier, User.deleted_at.is_(None)).with_for_update()
    )
    if user is None:
        raise missing()
    return user


def get_role(session: Session, identifier: UUID) -> Role:
    role = session.scalar(select(Role).where(Role.id == identifier, Role.deleted_at.is_(None)))
    if role is None:
        raise missing()
    return role


def role_codes(session: Session, role: Role) -> list[str]:
    return list(
        session.scalars(
            select(RolePermission.permission_code)
            .where(RolePermission.role_id == role.id)
            .order_by(RolePermission.permission_code)
        )
    )


def system_role(session: Session, code: str) -> Role:
    role = session.scalar(
        select(Role).where(Role.code == code, Role.is_system.is_(True), Role.deleted_at.is_(None))
    )
    if role is None:
        raise AppError("roles_unavailable", "System roles are not configured.", 503)
    return role


def retain_manager(session: Session) -> None:
    session.flush()
    available = session.scalar(
        select(User.id)
        .join(
            RoleAssignment,
            (RoleAssignment.user_id == User.id) & (RoleAssignment.tenant_id == User.tenant_id),
        )
        .join(
            Role, (Role.id == RoleAssignment.role_id) & (Role.tenant_id == RoleAssignment.tenant_id)
        )
        .where(
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            User.phone_normalized.is_not(None),
            RoleAssignment.revoked_at.is_(None),
            RoleAssignment.scope == "TENANT",
            Role.code == "salon_manager",
            Role.is_system.is_(True),
            Role.deleted_at.is_(None),
        )
        .limit(1)
    )
    if available is None:
        raise AppError("last_manager", "Keep at least one active salon manager.", 409)


def users_view(session: Session, users: Sequence[User]) -> list[ManagedUser]:
    if not users:
        return []
    ids = [user.id for user in users]
    customers = {
        user_id: identifier
        for user_id, identifier in session.execute(
            select(CustomerProfile.user_id, CustomerProfile.id).where(
                CustomerProfile.user_id.in_(ids)
            )
        ).all()
    }
    employees = {
        item.user_id: item
        for item in session.scalars(
            select(EmployeeProfile).where(
                EmployeeProfile.user_id.in_(ids), EmployeeProfile.deleted_at.is_(None)
            )
        )
    }
    assignments: dict[UUID, list[AssignmentResponse]] = {identifier: [] for identifier in ids}
    for assignment, code in session.execute(
        select(RoleAssignment, Role.code)
        .join(
            Role, (Role.id == RoleAssignment.role_id) & (Role.tenant_id == RoleAssignment.tenant_id)
        )
        .where(
            RoleAssignment.user_id.in_(ids),
            RoleAssignment.revoked_at.is_(None),
            Role.deleted_at.is_(None),
        )
        .order_by(Role.code, RoleAssignment.id)
    ):
        assignments[assignment.user_id].append(
            AssignmentResponse(
                id=assignment.id,
                role_id=assignment.role_id,
                code=code,
                scope=assignment.scope,
                line_id=assignment.line_id,
            )
        )
    result = []
    for user in users:
        employee = employees.get(user.id)
        result.append(
            ManagedUser(
                id=user.id,
                phone=user.phone_normalized,
                phone_verified=user.phone_verified_at is not None,
                display_name=user.display_name,
                is_active=user.is_active,
                created_at=user.created_at,
                customer_id=customers.get(user.id),
                assignments=assignments[user.id],
                employee=EmployeeResponse(
                    id=employee.id, public_name=employee.public_name, is_active=employee.is_active
                )
                if employee
                else None,
            )
        )
    return result


class ManagementService:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions

    def salon(self, context: AuthContext, raw: str) -> SalonResponse:
        with self.sessions.authorized(context, raw) as (session, identity):
            identity.principal.require("salon.read")
            row = session.get(Salon, context.tenant_id)
            assert row is not None
            result = SalonResponse(
                id=row.id, name=row.name, timezone=row.timezone, status=row.status
            )
        return result

    def rename_salon(
        self, context: AuthContext, raw: str, csrf: str, payload: SalonUpdate
    ) -> SalonResponse:
        with self.sessions.authorized(context, raw, csrf, management=True) as (session, identity):
            identity.principal.require("salon.manage")
            row = session.get(Salon, context.tenant_id)
            assert row is not None
            previous_name = row.name
            row.name = payload.name
            record_change(
                session,
                context,
                identity.user.id,
                "salon.updated",
                "salon",
                row.id,
                {"name": {"before": previous_name, "after": row.name}},
            )
            result = SalonResponse(
                id=row.id, name=row.name, timezone=row.timezone, status=row.status
            )
        return result

    def profile(
        self, context: AuthContext, raw: str, csrf: str, payload: ProfileUpdate
    ) -> ManagedUser:
        with self.sessions.authorized(context, raw, csrf) as (session, identity):
            identity.principal.require("profile.update")
            identity.user.display_name = payload.display_name
            record_change(
                session,
                context,
                identity.user.id,
                "profile.updated",
                "user",
                identity.user.id,
                {"changed_fields": ["display_name"]},
            )
            result = users_view(session, [identity.user])[0]
        return result

    def users(
        self,
        context: AuthContext,
        raw: str,
        *,
        limit: int = 25,
        offset: int = 0,
        kind: str | None = None,
    ) -> UserPage:
        if (
            not 1 <= limit <= 100
            or not 0 <= offset <= 10000
            or kind not in (None, "customer", "employee", "manager")
        ):
            raise AppError("invalid_page", "Invalid page or user kind.", 422)
        with self.sessions.authorized(context, raw) as (session, identity):
            identity.principal.require("users.read")
            statement = select(User).where(User.deleted_at.is_(None))
            if kind == "customer":
                statement = statement.where(
                    select(CustomerProfile.id).where(CustomerProfile.user_id == User.id).exists()
                )
            elif kind == "employee":
                statement = statement.where(
                    select(EmployeeProfile.id)
                    .where(EmployeeProfile.user_id == User.id, EmployeeProfile.deleted_at.is_(None))
                    .exists()
                )
            elif kind == "manager":
                statement = statement.where(
                    select(RoleAssignment.id)
                    .join(
                        Role,
                        (Role.id == RoleAssignment.role_id)
                        & (Role.tenant_id == RoleAssignment.tenant_id),
                    )
                    .where(
                        RoleAssignment.user_id == User.id,
                        RoleAssignment.revoked_at.is_(None),
                        Role.deleted_at.is_(None),
                        Role.is_system.is_(True),
                        Role.code.in_(("salon_manager", "line_manager")),
                    )
                    .exists()
                )
            rows = session.scalars(
                statement.order_by(User.created_at, User.id).offset(offset).limit(limit + 1)
            ).all()
            result = UserPage(
                items=users_view(session, rows[:limit]),
                limit=limit,
                offset=offset,
                has_more=len(rows) > limit,
            )
        return result

    def user(self, context: AuthContext, raw: str, identifier: UUID) -> ManagedUser:
        with self.sessions.authorized(context, raw) as (session, identity):
            identity.principal.require("users.read")
            # Reads do not lock another User after the actor (no multi-user lock cycle).
            row = session.scalar(
                select(User).where(User.id == identifier, User.deleted_at.is_(None))
            )
            if row is None:
                raise missing()
            result = users_view(session, [row])[0]
        return result

    def create_user(
        self, context: AuthContext, raw: str, csrf: str, payload: UserCreate
    ) -> ManagedUser:
        with self.sessions.authorized(
            context, raw, csrf, management=True, calendar=payload.kind == "employee"
        ) as (session, identity):
            identity.principal.require("users.manage")
            if payload.kind == "employee":
                identity.principal.require("staff.manage")
            roles = [system_role(session, "customer")]
            if payload.kind == "employee":
                roles.append(system_role(session, "employee"))
            for role in roles:
                delegation_ceiling(
                    identity.principal,
                    [Grant(code, "TENANT") for code in role_codes(session, role)],
                )
            if (
                session.scalar(select(User.id).where(User.phone_normalized == payload.phone))
                is not None
            ):
                raise AppError(
                    "phone_in_use", "Mobile number is already registered in this salon.", 409
                )
            user = User(
                tenant_id=context.tenant_id,
                phone_normalized=payload.phone,
                display_name=payload.display_name,
                password_hash=self.sessions.security.hash_password(
                    payload.password.get_secret_value()
                ),
            )
            session.add(user)
            session.flush()
            session.add(
                CustomerProfile(
                    tenant_id=context.tenant_id, user_id=user.id, contact_preference="NONE"
                )
            )
            if payload.kind == "employee":
                session.add(
                    EmployeeProfile(
                        tenant_id=context.tenant_id, user_id=user.id, public_name=user.display_name
                    )
                )
            for role in roles:
                session.add(
                    RoleAssignment(
                        tenant_id=context.tenant_id,
                        user_id=user.id,
                        role_id=role.id,
                        scope="TENANT",
                        granted_by_id=identity.user.id,
                    )
                )
            record_change(
                session,
                context,
                identity.user.id,
                "user.created",
                "user",
                user.id,
                {"kind": payload.kind},
            )
            session.flush()
            result = users_view(session, [user])[0]
        return result

    def update_user(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, payload: UserUpdate
    ) -> ManagedUser:
        with self.sessions.authorized(
            context, raw, csrf, management=True, calendar=payload.is_active is not None
        ) as (session, identity):
            identity.principal.require("users.manage")
            user = get_user(session, identifier)
            target = load_principal(
                session, context.tenant_id, user.id, user.phone_verified_at is not None
            )
            delegation_ceiling(identity.principal, target.grants)
            previous_active = user.is_active
            if payload.display_name is not None:
                user.display_name = payload.display_name
            if payload.is_active is not None and user.is_active != payload.is_active:
                if not payload.is_active:
                    employee_id = session.scalar(
                        select(EmployeeProfile.id).where(EmployeeProfile.user_id == user.id)
                    )
                    if employee_id is not None:
                        require_no_upcoming_bookings(session, employee_id=employee_id)
                user.is_active = payload.is_active
                self.sessions.revoke_credentials(session, user, datetime.now(UTC))
                if not user.is_active and "salon_manager" in target.roles:
                    retain_manager(session)
            record_change(
                session,
                context,
                identity.user.id,
                "user.updated",
                "user",
                user.id,
                {
                    "changed_fields": sorted(payload.model_fields_set),
                    "is_active": {"before": previous_active, "after": user.is_active},
                },
            )
            result = users_view(session, [user])[0]
        return result

    def employee(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, payload: EmployeeUpdate
    ) -> ManagedUser:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("users.manage")
            identity.principal.require("staff.manage")
            user = get_user(session, identifier)
            target = load_principal(
                session, context.tenant_id, user.id, user.phone_verified_at is not None
            )
            delegation_ceiling(identity.principal, target.grants)
            profile = session.scalar(
                select(EmployeeProfile).where(EmployeeProfile.user_id == user.id)
            )
            if profile is None:
                profile = EmployeeProfile(
                    tenant_id=context.tenant_id, user_id=user.id, public_name=payload.public_name
                )
                session.add(profile)
            previous_active = profile.is_active
            if not payload.is_active and previous_active:
                require_no_upcoming_bookings(session, employee_id=profile.id)
            profile.public_name = payload.public_name
            profile.is_active = payload.is_active
            profile.deleted_at = None
            record_change(
                session,
                context,
                identity.user.id,
                "employee.updated",
                "user",
                user.id,
                {
                    "changed_fields": ["public_name", "is_active"],
                    "is_active": {"before": previous_active, "after": profile.is_active},
                },
            )
            session.flush()
            result = users_view(session, [user])[0]
        return result

    def delete_employee(self, context: AuthContext, raw: str, csrf: str, identifier: UUID) -> None:
        with self.sessions.authorized(context, raw, csrf, management=True, calendar=True) as (
            session,
            identity,
        ):
            identity.principal.require("users.manage")
            identity.principal.require("staff.manage")
            profile = session.scalar(
                select(EmployeeProfile).where(
                    EmployeeProfile.id == identifier, EmployeeProfile.deleted_at.is_(None)
                )
            )
            if profile is None:
                raise missing()
            user = get_user(session, profile.user_id)
            target = load_principal(
                session, context.tenant_id, user.id, user.phone_verified_at is not None
            )
            delegation_ceiling(identity.principal, target.grants)
            require_no_upcoming_bookings(session, employee_id=identifier)
            now = datetime.now(UTC)
            profile.is_active, profile.deleted_at = False, now
            for model in (EmployeeLine, EmployeeService):
                session.execute(
                    update(model)
                    .where(model.employee_id == identifier, model.deleted_at.is_(None))
                    .values(is_active=False, deleted_at=now)
                )
            employee_roles = select(Role.id).where(
                Role.code == "employee", Role.is_system.is_(True)
            )
            session.execute(
                update(RoleAssignment)
                .where(
                    RoleAssignment.user_id == user.id,
                    RoleAssignment.role_id.in_(employee_roles),
                    RoleAssignment.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            self.sessions.revoke_credentials(session, user, now)
            record_change(
                session,
                context,
                identity.user.id,
                "employee.deleted",
                "employee",
                profile.id,
                {"user_id": str(user.id)},
            )

    def permissions(self, context: AuthContext, raw: str) -> list[PermissionResponse]:
        with self.sessions.authorized(context, raw) as (session, identity):
            identity.principal.require("roles.read")
            result = [
                PermissionResponse(code=p.code, description=p.description)
                for p in session.scalars(select(Permission).order_by(Permission.code))
            ]
        return result

    def roles(
        self, context: AuthContext, raw: str, *, limit: int = 100, offset: int = 0
    ) -> list[RoleResponse]:
        with self.sessions.authorized(context, raw) as (session, identity):
            identity.principal.require("roles.read")
            rows = session.scalars(
                select(Role)
                .where(Role.deleted_at.is_(None))
                .order_by(Role.code)
                .offset(offset)
                .limit(limit)
            ).all()
            codes: dict[UUID, list[str]] = {role.id: [] for role in rows}
            for identifier, code in session.execute(
                select(RolePermission.role_id, RolePermission.permission_code)
                .where(RolePermission.role_id.in_(codes))
                .order_by(RolePermission.permission_code)
            ):
                codes[identifier].append(code)
            result = [
                RoleResponse(
                    id=r.id,
                    code=r.code,
                    name=r.name,
                    is_system=r.is_system,
                    permissions=codes[r.id],
                )
                for r in rows
            ]
        return result

    @staticmethod
    def validate_permissions(session: Session, principal: Principal, codes: list[str]) -> None:
        existing = set(session.scalars(select(Permission.code).where(Permission.code.in_(codes))))
        if existing != set(codes):
            raise AppError("unknown_permission", "Unknown permission.", 422)
        delegation_ceiling(principal, [Grant(code, "TENANT") for code in codes])

    def create_role(
        self, context: AuthContext, raw: str, csrf: str, payload: RoleCreate
    ) -> RoleResponse:
        with self.sessions.authorized(context, raw, csrf, management=True) as (session, identity):
            identity.principal.require("roles.manage")
            if payload.code in DEFAULT_ROLES or payload.code.startswith(("platform_", "super_")):
                raise AppError("reserved_role", "This role code is reserved.", 422)
            self.validate_permissions(session, identity.principal, payload.permissions)
            role = Role(
                tenant_id=context.tenant_id, code=payload.code, name=payload.name, is_system=False
            )
            session.add(role)
            session.flush()
            session.add_all(
                RolePermission(tenant_id=context.tenant_id, role_id=role.id, permission_code=code)
                for code in payload.permissions
            )
            record_change(
                session,
                context,
                identity.user.id,
                "role.created",
                "role",
                role.id,
                {"permissions": sorted(payload.permissions)},
            )
            result = RoleResponse(
                id=role.id,
                code=role.code,
                name=role.name,
                is_system=False,
                permissions=sorted(payload.permissions),
            )
        return result

    @staticmethod
    def editable_role(session: Session, identity: Identity, identifier: UUID) -> Role:
        identity.principal.require("roles.manage")
        role = get_role(session, identifier)
        if role.is_system:
            raise AppError("system_role", "System roles cannot be changed.", 409)
        delegation_ceiling(
            identity.principal, [Grant(code, "TENANT") for code in role_codes(session, role)]
        )
        return role

    def invalidate_role_users(self, session: Session, role: Role) -> None:
        ids = select(RoleAssignment.user_id).where(
            RoleAssignment.role_id == role.id, RoleAssignment.revoked_at.is_(None)
        )
        for user in session.scalars(
            select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update()
        ):
            self.sessions.revoke_credentials(session, user, datetime.now(UTC))

    def update_role(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, payload: RoleWrite
    ) -> RoleResponse:
        with self.sessions.authorized(context, raw, csrf, management=True) as (session, identity):
            role = self.editable_role(session, identity, identifier)
            self.validate_permissions(session, identity.principal, payload.permissions)
            self.invalidate_role_users(session, role)
            previous_permissions = role_codes(session, role)
            role.name = payload.name
            session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
            session.add_all(
                RolePermission(tenant_id=context.tenant_id, role_id=role.id, permission_code=code)
                for code in payload.permissions
            )
            record_change(
                session,
                context,
                identity.user.id,
                "role.updated",
                "role",
                role.id,
                {
                    "permissions": {
                        "before": previous_permissions,
                        "after": sorted(payload.permissions),
                    }
                },
            )
            result = RoleResponse(
                id=role.id,
                code=role.code,
                name=role.name,
                is_system=False,
                permissions=sorted(payload.permissions),
            )
        return result

    def delete_role(self, context: AuthContext, raw: str, csrf: str, identifier: UUID) -> None:
        with self.sessions.authorized(context, raw, csrf, management=True) as (session, identity):
            role = self.editable_role(session, identity, identifier)
            self.invalidate_role_users(session, role)
            now = datetime.now(UTC)
            for assignment in session.scalars(
                select(RoleAssignment).where(
                    RoleAssignment.role_id == role.id, RoleAssignment.revoked_at.is_(None)
                )
            ):
                assignment.revoked_at = now
            role.deleted_at = now
            record_change(
                session,
                context,
                identity.user.id,
                "role.deleted",
                "role",
                role.id,
                {"permissions": role_codes(session, role)},
            )

    def assign_role(
        self, context: AuthContext, raw: str, csrf: str, user_id: UUID, payload: AssignmentCreate
    ) -> AssignmentResponse:
        with self.sessions.authorized(context, raw, csrf, management=True) as (session, identity):
            identity.principal.require("roles.manage", line_id=payload.line_id)
            role = get_role(session, payload.role_id)
            if role.is_system and ((role.code == "line_manager") != (payload.scope == "LINE")):
                raise AppError("invalid_scope", "Use the required scope for this system role.", 422)
            if (
                payload.line_id is not None
                and session.scalar(
                    select(Line.id).where(
                        Line.id == payload.line_id,
                        Line.deleted_at.is_(None),
                        Line.is_active.is_(True),
                    )
                )
                is None
            ):
                raise missing()
            delegation_ceiling(
                identity.principal,
                [
                    Grant(code, payload.scope, str(payload.line_id) if payload.line_id else "")
                    for code in role_codes(session, role)
                ],
            )
            user = get_user(session, user_id)
            if not user.is_active or user.phone_normalized is None:
                raise AppError("inactive_user", "An active mobile account is required.", 409)
            if (
                role.is_system
                and role.code == "customer"
                and session.scalar(
                    select(CustomerProfile.id).where(CustomerProfile.user_id == user.id)
                )
                is None
            ):
                session.add(
                    CustomerProfile(
                        tenant_id=context.tenant_id, user_id=user.id, contact_preference="NONE"
                    )
                )
            if (
                role.code == "employee"
                and role.is_system
                and session.scalar(
                    select(EmployeeProfile.id).where(
                        EmployeeProfile.user_id == user.id, EmployeeProfile.deleted_at.is_(None)
                    )
                )
                is None
            ):
                raise AppError(
                    "employee_profile_required", "Create the employee profile first.", 409
                )
            existing = session.scalar(
                select(RoleAssignment).where(
                    RoleAssignment.user_id == user.id,
                    RoleAssignment.role_id == role.id,
                    RoleAssignment.scope == payload.scope,
                    RoleAssignment.line_id == payload.line_id,
                    RoleAssignment.revoked_at.is_(None),
                )
            )
            if existing is not None:
                raise AppError("assignment_exists", "This role is already assigned.", 409)
            assignment = RoleAssignment(
                tenant_id=context.tenant_id,
                user_id=user.id,
                role_id=role.id,
                scope=payload.scope,
                line_id=payload.line_id,
                granted_by_id=identity.user.id,
            )
            session.add(assignment)
            self.sessions.revoke_credentials(session, user, datetime.now(UTC))
            session.flush()
            record_change(
                session,
                context,
                identity.user.id,
                "role.assigned",
                "role_assignment",
                assignment.id,
                {
                    "user_id": str(user.id),
                    "role_id": str(role.id),
                    "scope": assignment.scope,
                    "line_id": str(assignment.line_id) if assignment.line_id else None,
                },
            )
            result = AssignmentResponse(
                id=assignment.id,
                role_id=role.id,
                code=role.code,
                scope=assignment.scope,
                line_id=assignment.line_id,
            )
        return result

    def revoke_assignment(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID
    ) -> None:
        with self.sessions.authorized(context, raw, csrf, management=True) as (session, identity):
            assignment = session.scalar(
                select(RoleAssignment).where(
                    RoleAssignment.id == identifier, RoleAssignment.revoked_at.is_(None)
                )
            )
            if assignment is None:
                raise missing()
            identity.principal.require("roles.manage", line_id=assignment.line_id)
            role = get_role(session, assignment.role_id)
            delegation_ceiling(
                identity.principal,
                [
                    Grant(
                        code,
                        assignment.scope,
                        str(assignment.line_id) if assignment.line_id else "",
                    )
                    for code in role_codes(session, role)
                ],
            )
            user = get_user(session, assignment.user_id)
            assignment.revoked_at = datetime.now(UTC)
            self.sessions.revoke_credentials(session, user, datetime.now(UTC))
            if role.is_system and role.code == "salon_manager":
                retain_manager(session)
            record_change(
                session,
                context,
                identity.user.id,
                "role.revoked",
                "role_assignment",
                assignment.id,
                {
                    "user_id": str(user.id),
                    "role_id": str(role.id),
                    "scope": assignment.scope,
                    "line_id": str(assignment.line_id) if assignment.line_id else None,
                },
            )
