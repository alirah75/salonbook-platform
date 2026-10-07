import hmac
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, create_engine, delete, exists, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.database import RLS_CHECK, RUNTIME_ROLE_CHECK
from app.db.models import Base
from app.db.schema import REQUIRED_SCHEMA_REVISION
from app.modules.access.models import (
    PlatformAuthThrottle,
    PlatformRoleAssignment,
    PlatformRolePermission,
    PlatformSession,
    PlatformUser,
)
from app.modules.identity.schemas import LoginInput
from app.modules.identity.security import Security, new_token, token_hash
from app.modules.operations.models import PlatformAuditLog
from app.platform.config import PlatformSettings


@dataclass
class Identity:
    user: PlatformUser
    session: PlatformSession
    csrf: str


class PlatformService:
    def __init__(self, settings: PlatformSettings, engine: Engine | None = None) -> None:
        self.settings = settings
        self.security = Security(settings.auth_key.get_secret_value())
        self.engine = engine or create_engine(
            settings.database_url.get_secret_value(),
            hide_parameters=True,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=3,
            pool_timeout=5,
            connect_args={
                "connect_timeout": 5,
                "application_name": "salonbook-platform",
                "options": "-c timezone=UTC -c search_path=public -c statement_timeout=10000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000",
            },
        )

    def validate_ready(self) -> None:
        with self.engine.connect() as connection:
            role = connection.execute(RUNTIME_ROLE_CHECK).one()
            # Owners, bypass roles and the tenant runtime cannot host this application.
            if any(role[:3]) or not connection.scalar(
                text(
                    "SELECT pg_has_role(current_user, 'salonbook_platform', 'MEMBER') AND NOT pg_has_role(current_user, 'salonbook_runtime', 'MEMBER')"
                )
            ):
                raise RuntimeError("Unsafe platform database role.")
            if connection.scalar(
                text(
                    "SELECT has_table_privilege(current_user, 'appointments', 'SELECT,INSERT,UPDATE,DELETE') OR has_table_privilege(current_user, 'financial_entries', 'SELECT,INSERT,UPDATE,DELETE') OR has_table_privilege(current_user, 'platform_users', 'INSERT,UPDATE,DELETE') OR has_column_privilege(current_user, 'platform_users', 'password_hash', 'UPDATE') OR has_column_privilege(current_user, 'platform_users', 'is_active', 'UPDATE') OR has_column_privilege(current_user, 'platform_users', 'phone_normalized', 'UPDATE')"
                )
            ):
                raise RuntimeError("Excess platform database permissions.")
            if (
                connection.scalar(text("SELECT version_num FROM app_schema_revision"))
                != REQUIRED_SCHEMA_REVISION
            ):
                raise RuntimeError("Upgrade the database before platform startup.")
            tables = {
                t.name
                for t in Base.metadata.tables.values()
                if "tenant_id" in t.c and t.name != "tenant_domains"
            } | {"salons"}
            protected = {
                name
                for name, enabled, forced in connection.execute(
                    RLS_CHECK, {"tables": sorted(tables)}
                )
                if enabled and forced
            }
            if protected != tables:
                raise RuntimeError("Tenant isolation is missing.")

    @staticmethod
    def permitted(session: Session, user_id: UUID) -> bool:
        return bool(
            session.scalar(
                select(
                    exists().where(
                        PlatformRoleAssignment.user_id == user_id,
                        PlatformRoleAssignment.role_id == PlatformRolePermission.role_id,
                        PlatformRolePermission.permission_code == "platform.manage",
                    )
                )
            )
        )

    def csrf(self, raw: str) -> str:
        return self.security.digest("platform-csrf", raw).hex()

    def throttle(self, phone: str) -> None:
        self._throttle((("global", 60, 60), (phone, 900, 8)))

    def api_throttle(self) -> None:
        self._throttle((("api-global", 60, 600),))

    def _throttle(self, buckets: tuple[tuple[str, int, int], ...]) -> None:
        now = datetime.now(UTC)
        blocked = False
        # Atomic shared counters across workers. Account keys contain no phone numbers.
        with Session(self.engine) as session, session.begin():
            session.execute(
                delete(PlatformAuthThrottle).where(PlatformAuthThrottle.expires_at < now)
            )
            for label, seconds, maximum in buckets:
                bucket = int(now.timestamp()) // seconds
                key = self.security.digest("platform-throttle", f"{label}:{bucket}")
                statement = insert(PlatformAuthThrottle).values(
                    key=key,
                    attempts=1,
                    expires_at=datetime.fromtimestamp((bucket + 1) * seconds, UTC),
                )
                count = session.scalar(
                    statement.on_conflict_do_update(
                        index_elements=[PlatformAuthThrottle.key],
                        set_={"attempts": PlatformAuthThrottle.attempts + 1},
                    ).returning(PlatformAuthThrottle.attempts)
                )
                blocked = blocked or bool(count and count > maximum)
                if blocked:
                    break
        if blocked:
            raise AppError(
                "rate_limited",
                "Please wait before trying again.",
                429,
                retry_after=max(seconds for _, seconds, _ in buckets),
            )

    def login(self, payload: LoginInput, previous: str = "") -> tuple[str, Identity]:
        self.throttle(payload.phone)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            user = session.scalar(
                select(PlatformUser)
                .where(PlatformUser.phone_normalized == payload.phone)
                .with_for_update()
            )
            if (
                not self.security.verify_password(
                    user.password_hash if user else None, payload.password.get_secret_value()
                )
                or not user
                or not user.is_active
                or not self.permitted(session, user.id)
            ):
                raise AppError(
                    "invalid_credentials", "Mobile number or password is incorrect.", 401
                )
            now = datetime.now(UTC)
            active = list(
                session.scalars(
                    select(PlatformSession)
                    .where(PlatformSession.user_id == user.id, PlatformSession.revoked_at.is_(None))
                    .order_by(PlatformSession.created_at.desc())
                    .with_for_update()
                )
            )
            for index, old in enumerate(active):
                if (
                    index >= 9
                    or old.token_hash == token_hash(previous)
                    or old.idle_expires_at <= now
                ):
                    old.revoked_at = now
            raw = new_token()
            record = PlatformSession(
                user_id=user.id,
                token_hash=token_hash(raw),
                csrf_hash=token_hash(self.csrf(raw)),
                expires_at=now + timedelta(hours=8),
                idle_expires_at=now + timedelta(minutes=30),
            )
            session.add(record)
            session.add(
                PlatformAuditLog(
                    actor_id=user.id, action="platform.login", entity_id=user.id, event_data={}
                )
            )
            session.flush()
            return raw, Identity(user, record, self.csrf(raw))

    @contextmanager
    def authorized(self, raw: str, csrf: str | None = None) -> Iterator[tuple[Session, Identity]]:
        if not 20 <= len(raw) <= 100:
            raise AppError("unauthenticated", "Platform sign-in required.", 401)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            user_id = session.scalar(
                select(PlatformSession.user_id).where(PlatformSession.token_hash == token_hash(raw))
            )
            user = (
                session.scalar(
                    select(PlatformUser)
                    .where(PlatformUser.id == user_id)
                    .with_for_update(key_share=True)
                )
                if user_id
                else None
            )
            record = session.scalar(
                select(PlatformSession)
                .where(PlatformSession.token_hash == token_hash(raw))
                .with_for_update()
            )
            now = datetime.now(UTC)
            if (
                not user
                or not user.is_active
                or not record
                or record.revoked_at
                or record.expires_at <= now
                or record.idle_expires_at <= now
                or not self.permitted(session, user.id)
            ):
                raise AppError("unauthenticated", "Platform session expired.", 401)
            if csrf is not None and (
                len(csrf) > 200 or not hmac.compare_digest(token_hash(csrf), record.csrf_hash)
            ):
                raise AppError("csrf_failed", "Invalid platform CSRF token.", 403)
            record.idle_expires_at = min(record.expires_at, now + timedelta(minutes=30))
            yield session, Identity(user, record, self.csrf(raw))
