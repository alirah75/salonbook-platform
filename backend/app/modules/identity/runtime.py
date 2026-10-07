from dataclasses import dataclass

from app.core.config import Settings
from app.db.database import Database
from app.modules.identity.accounts import AccountService
from app.modules.identity.security import Security
from app.modules.identity.sessions import SessionService
from app.modules.identity.throttle import AuthLimiter


@dataclass(frozen=True)
class AuthRuntime:
    security: Security
    accounts: AccountService
    sessions: SessionService
    limiter: AuthLimiter


def build_auth(database: Database, settings: Settings) -> AuthRuntime | None:
    if settings.auth_key is None:
        return None
    security = Security(settings.auth_key.get_secret_value())
    sessions = SessionService(database, settings, security)
    return AuthRuntime(
        security,
        AccountService(database, security, sessions),
        sessions,
        AuthLimiter(database, settings, security),
    )
