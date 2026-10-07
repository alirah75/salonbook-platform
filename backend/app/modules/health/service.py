from app.core.errors import AppError
from app.core.logging import logger
from app.db.database import Database, DatabaseNotReady
from app.modules.health.schemas import LivenessResponse, ReadinessResponse


class HealthService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def live(self) -> LivenessResponse:
        return LivenessResponse()

    def ready(self) -> ReadinessResponse:
        try:
            self.database.validate_ready()
        except DatabaseNotReady as exc:
            logger.warning(
                "readiness.failed", extra={"event": "readiness.failed", "error_code": exc.code}
            )
            raise AppError("not_ready", "The service is not ready.", 503) from None
        return ReadinessResponse()
