from fastapi import APIRouter

from app.dependencies.runtime import HealthDependency
from app.modules.health.schemas import LivenessResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse, summary="Process liveness")
def live(service: HealthDependency) -> LivenessResponse:
    return service.live()


@router.get("/ready", response_model=ReadinessResponse, summary="Database and schema readiness")
def ready(service: HealthDependency) -> ReadinessResponse:
    return service.ready()
