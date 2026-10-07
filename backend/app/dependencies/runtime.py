from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.runtime import AppRuntime
from app.db.database import Database
from app.modules.health.service import HealthService


def get_runtime(request: Request) -> AppRuntime:
    return cast(AppRuntime, request.app.state.runtime)


RuntimeDependency = Annotated[AppRuntime, Depends(get_runtime)]


def get_database(runtime: RuntimeDependency) -> Database:
    return runtime.database


def get_health_service(runtime: RuntimeDependency) -> HealthService:
    return runtime.health


DatabaseDependency = Annotated[Database, Depends(get_database)]
HealthDependency = Annotated[HealthService, Depends(get_health_service)]
