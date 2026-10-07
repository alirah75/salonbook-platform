from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.modules.appointments.router import Limit, Offset
from app.modules.dashboard.service import DashboardService, Overview, Workspace
from app.modules.identity.dependencies import AuthDependency, ContextDependency, session_token

router = APIRouter(prefix="/dashboard", tags=["Staff dashboard"])


def dashboard(auth: AuthDependency) -> DashboardService:
    return DashboardService(auth.sessions)


DashboardDependency = Annotated[DashboardService, Depends(dashboard)]


@router.get("/context", response_model=Workspace)
def workspace(
    request: Request, context: ContextDependency, service: DashboardDependency
) -> Workspace:
    return service.context(context, session_token(request))


@router.get("/overview", response_model=Overview)
def overview(
    request: Request,
    context: ContextDependency,
    service: DashboardDependency,
    day: Annotated[date | None, Query(ge=date(2000, 1, 1), le=date(2100, 12, 31))] = None,
    line_id: UUID | None = None,
    limit: Limit = 24,
    offset: Offset = 0,
) -> Overview:
    return service.overview(context, session_token(request), day, line_id, limit, offset)
