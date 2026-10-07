import hmac
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session as UnitOfWork

from app.core.config import Settings
from app.core.errors import AppError
from app.db.database import Database
from app.modules.access.service import Principal, load_principal
from app.modules.identity.audit import audit
from app.modules.identity.context import AuthContext, require_active_context
from app.modules.identity.models import AuthToken, Session, User
from app.modules.identity.schemas import SessionItem, SessionResponse, UserResponse
from app.modules.identity.security import Security, new_token, token_hash
from app.modules.scheduling.coordination import lock_calendar
from app.modules.tenancy.locks import tenant_lock


def unauthorized() -> AppError:
    return AppError("unauthenticated", "Please sign in.", 401)


@dataclass(frozen=True)
class Identity:
    user: User
    record: Session
    principal: Principal


class SessionService:
    def __init__(self, database: Database, settings: Settings, security: Security) -> None:
        self.database, self.settings, self.security = database, settings, security

    def create(
        self, session: UnitOfWork, context: AuthContext, user: User
    ) -> tuple[str, SessionResponse]:
        now = datetime.now(UTC)
        principal = load_principal(
            session, context.tenant_id, user.id, user.phone_verified_at is not None
        )
        hours = (
            self.settings.auth_staff_session_hours
            if principal.staff
            else self.settings.auth_session_hours
        )
        idle = (
            self.settings.auth_staff_idle_minutes
            if principal.staff
            else self.settings.auth_idle_minutes
        )
        raw = new_token()
        expires = now + timedelta(hours=hours)
        csrf = self.security.session_csrf(context.tenant_id, raw)
        record = Session(
            tenant_id=context.tenant_id,
            user_id=user.id,
            token_hash=token_hash(raw),
            csrf_hash=token_hash(csrf),
            expires_at=expires,
            idle_expires_at=min(expires, now + timedelta(minutes=idle)),
            last_seen_at=now,
            auth_version=user.auth_version,
            grants_fingerprint=principal.fingerprint,
            ip_address=context.ip,
        )
        session.add(record)
        # Bound retained active sessions. Lock order is always User -> Session.
        old = session.scalars(
            select(Session)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
            .order_by(Session.created_at.desc())
            .offset(9)
        ).all()
        for item in old:
            item.revoked_at = now
        audit(session, context, "auth.login", user)
        return raw, self.response(context, raw, Identity(user, record, principal))

    @contextmanager
    def authorized(
        self,
        context: AuthContext,
        raw: str,
        csrf: str | None = None,
        *,
        management: bool = False,
        calendar: bool = False,
        calendar_read: bool = False,
    ) -> Iterator[tuple[UnitOfWork, Identity]]:
        if len(raw) != 43:
            raise unauthorized()
        changed_permissions = False
        with self.database.transaction(context.tenant_id) as session:
            require_active_context(session, context)
            if management:
                tenant_lock(session, context.tenant_id, "management")
            control = (
                lock_calendar(session, context.tenant_id, shared=not calendar)
                if calendar or calendar_read
                else None
            )
            identifier = session.scalar(
                select(Session.user_id).where(Session.token_hash == token_hash(raw))
            )
            if identifier is None:
                raise unauthorized()
            user = session.scalar(select(User).where(User.id == identifier).with_for_update())
            record = session.scalar(
                select(Session).where(Session.token_hash == token_hash(raw)).with_for_update()
            )
            now = datetime.now(UTC)
            if (
                user is None
                or record is None
                or not user.is_active
                or user.deleted_at is not None
                or record.revoked_at is not None
                or record.expires_at <= now
                or record.idle_expires_at <= now
                or record.auth_version != user.auth_version
            ):
                raise unauthorized()
            principal = load_principal(
                session, context.tenant_id, user.id, user.phone_verified_at is not None
            )
            if not hmac.compare_digest(record.grants_fingerprint, principal.fingerprint):
                record.revoked_at = now
                changed_permissions = True
            else:
                if csrf is not None and not hmac.compare_digest(record.csrf_hash, token_hash(csrf)):
                    raise AppError("csrf_failed", "Request verification failed.", 403)
                minutes = (
                    self.settings.auth_staff_idle_minutes
                    if principal.staff
                    else self.settings.auth_idle_minutes
                )
                record.last_seen_at = now
                record.idle_expires_at = min(record.expires_at, now + timedelta(minutes=minutes))
                yield session, Identity(user, record, principal)
                if control is not None and calendar:
                    control.version += 1
        # Commit revocation before raising; restoring a permission cannot resurrect this session.
        if changed_permissions:
            raise unauthorized()

    def response(self, context: AuthContext, raw: str, identity: Identity) -> SessionResponse:
        user = identity.user
        return SessionResponse(
            user=UserResponse(
                id=user.id,
                tenant_id=context.tenant_id,
                phone=user.phone_normalized,
                phone_verified=user.phone_verified_at is not None,
                display_name=user.display_name,
                roles=sorted(identity.principal.roles),
            ),
            csrf_token=self.security.session_csrf(context.tenant_id, raw),
            expires_at=identity.record.expires_at,
        )

    def current(self, context: AuthContext, raw: str) -> SessionResponse:
        with self.authorized(context, raw) as (_, identity):
            result = self.response(context, raw, identity)
        return result

    @staticmethod
    def revoke_credentials(session: UnitOfWork, user: User, now: datetime) -> None:
        """Invalidate sessions and any historical capabilities after credential changes."""
        user.auth_version += 1
        session.execute(
            update(Session)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        session.execute(
            update(AuthToken)
            .where(AuthToken.user_id == user.id, AuthToken.consumed_at.is_(None))
            .values(consumed_at=now)
        )

    def principal(self, context: AuthContext, raw: str) -> Principal:
        with self.authorized(context, raw) as (_, identity):
            result = identity.principal
        return result

    def list_sessions(self, context: AuthContext, raw: str) -> list[SessionItem]:
        with self.authorized(context, raw) as (session, identity):
            identity.principal.require("session.manage")
            now = datetime.now(UTC)
            rows = session.scalars(
                select(Session)
                .where(
                    Session.user_id == identity.user.id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > now,
                    Session.idle_expires_at > now,
                    Session.auth_version == identity.user.auth_version,
                    Session.grants_fingerprint == identity.principal.fingerprint,
                )
                .order_by(Session.created_at.desc())
                .limit(100)
            ).all()
            result = [
                SessionItem(
                    id=row.id,
                    created_at=row.created_at,
                    last_seen_at=row.last_seen_at,
                    expires_at=row.expires_at,
                    current=row.id == identity.record.id,
                )
                for row in rows
            ]
        return result

    def revoke(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        target: UUID | None = None,
        all_sessions: bool = False,
    ) -> None:
        with self.authorized(context, raw, csrf) as (session, identity):
            if target is not None:
                identity.principal.require("session.manage")
            statement = update(Session).where(
                Session.user_id == identity.user.id, Session.revoked_at.is_(None)
            )
            if not all_sessions:
                statement = statement.where(Session.id == (target or identity.record.id))
            session.execute(statement.values(revoked_at=datetime.now(UTC)))
            audit(
                session,
                context,
                "auth.logout_all" if all_sessions else "auth.logout",
                identity.user,
            )
