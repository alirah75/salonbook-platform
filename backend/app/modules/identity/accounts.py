from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.db.database import Database
from app.modules.access.models import Role, RoleAssignment
from app.modules.identity.audit import audit
from app.modules.identity.context import AuthContext, require_active_context
from app.modules.identity.models import CustomerProfile, Session, User
from app.modules.identity.schemas import RegisterInput, SessionResponse
from app.modules.identity.security import Security, token_hash
from app.modules.identity.sessions import SessionService, unauthorized


class AccountService:
    def __init__(self, database: Database, security: Security, sessions: SessionService) -> None:
        self.database, self.security, self.sessions = (
            database,
            security,
            sessions,
        )

    def register(self, context: AuthContext, payload: RegisterInput) -> None:
        # Hash for both existing and new accounts; public responses never reveal existence.
        encoded = self.security.hash_password(payload.password.get_secret_value())
        with self.database.transaction(context.tenant_id) as session:
            require_active_context(session, context)
            role = session.scalar(
                select(Role).where(
                    Role.code == "customer", Role.is_system.is_(True), Role.deleted_at.is_(None)
                )
            )
            if role is None:
                raise AppError("registration_unavailable", "Registration is unavailable.", 503)
            identifier = session.scalar(
                insert(User)
                .values(
                    tenant_id=context.tenant_id,
                    phone_normalized=payload.phone,
                    display_name=payload.display_name,
                    password_hash=encoded,
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "phone_normalized"])
                .returning(User.id)
            )
            if identifier is not None:
                user = session.scalar(select(User).where(User.id == identifier).with_for_update())
                assert user is not None
                session.add(
                    CustomerProfile(
                        tenant_id=context.tenant_id, user_id=user.id, contact_preference="NONE"
                    )
                )
                session.add(
                    RoleAssignment(
                        tenant_id=context.tenant_id,
                        user_id=user.id,
                        role_id=role.id,
                        scope="TENANT",
                    )
                )
                audit(session, context, "auth.register", user)

    def login(
        self, context: AuthContext, phone: str, password: str, old_token: str = ""
    ) -> tuple[str, SessionResponse]:
        result: tuple[str, SessionResponse] | None = None
        with self.database.transaction(context.tenant_id) as session:
            require_active_context(session, context)
            user = session.scalar(
                select(User).where(User.phone_normalized == phone).with_for_update()
            )
            valid = self.security.verify_password(user.password_hash if user else None, password)
            if user and valid and user.is_active and user.deleted_at is None:
                if self.security.passwords.check_needs_rehash(user.password_hash):
                    user.password_hash = self.security.hash_password(password)
                old = (
                    session.scalar(
                        select(Session)
                        .where(
                            Session.token_hash == token_hash(old_token), Session.user_id == user.id
                        )
                        .with_for_update()
                    )
                    if old_token
                    else None
                )
                if old:
                    old.revoked_at = datetime.now(UTC)
                result = self.sessions.create(session, context, user)
            else:
                audit(session, context, "auth.login_failed")
        if result is None:
            raise unauthorized()
        return result

    def change_password(
        self, context: AuthContext, raw: str, csrf: str, current: str, new: str
    ) -> None:
        encoded = self.security.hash_password(new)
        with self.sessions.authorized(context, raw, csrf) as (session, identity):
            if not self.security.verify_password(identity.user.password_hash, current):
                raise AppError("invalid_credentials", "Current password is incorrect.", 400)
            identity.user.password_hash = encoded
            self.sessions.revoke_credentials(session, identity.user, datetime.now(UTC))
            audit(session, context, "auth.password_changed", identity.user)
