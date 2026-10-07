from dataclasses import dataclass

from app.core.config import Settings
from app.db.database import Database
from app.modules.health.service import HealthService
from app.modules.identity.runtime import AuthRuntime


@dataclass(frozen=True)
class AppRuntime:
    settings: Settings
    database: Database
    health: HealthService
    auth: AuthRuntime | None = None
