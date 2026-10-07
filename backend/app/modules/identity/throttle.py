"""Atomic shared limits; their transaction commits even when authentication fails."""

from sqlalchemy import text

from app.core.config import Settings
from app.core.errors import AppError
from app.db.database import Database
from app.modules.identity.context import AuthContext
from app.modules.identity.security import Security


class AuthLimiter:
    def __init__(self, database: Database, settings: Settings, security: Security) -> None:
        self.database, self.settings, self.security = database, settings, security

    def check(self, context: AuthContext, purpose: str, account: str = "") -> None:
        self._check(
            context,
            purpose,
            account,
            self.settings.auth_ip_limit,
            self.settings.auth_attempt_limit,
            self.settings.auth_window_seconds,
        )

    def check_api(self, context: AuthContext) -> None:
        self._check(
            context, "api", "", self.settings.api_ip_limit, 0, self.settings.api_window_seconds
        )

    def _check(
        self,
        context: AuthContext,
        purpose: str,
        account: str,
        ip_limit: int,
        account_limit: int,
        window: int,
    ) -> None:
        blocked = False
        buckets = [("ip", context.ip, ip_limit)]
        if account:
            buckets.append(("account", account, account_limit))
        with self.database.transaction(context.tenant_id) as session:
            for kind, value, limit in buckets:
                attempts = session.scalar(
                    text("""
                    INSERT INTO auth_throttles (tenant_id, bucket_hash, purpose, attempts, expires_at)
                    VALUES (:tenant, :bucket, :purpose, 1, clock_timestamp() + make_interval(secs => :window))
                    ON CONFLICT (tenant_id, bucket_hash, purpose) DO UPDATE SET
                        attempts = CASE WHEN auth_throttles.expires_at <= clock_timestamp() THEN 1 ELSE auth_throttles.attempts + 1 END,
                        expires_at = CASE WHEN auth_throttles.expires_at <= clock_timestamp() THEN excluded.expires_at ELSE auth_throttles.expires_at END
                    RETURNING attempts
                """),
                    {
                        "tenant": context.tenant_id,
                        "bucket": self.security.digest(f"throttle:{kind}", value),
                        "purpose": purpose,
                        "window": window,
                    },
                )
                blocked |= int(attempts or 0) > limit
        if blocked:
            raise AppError(
                "rate_limited", "Too many attempts. Try again later.", 429, retry_after=window
            )
