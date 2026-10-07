from fastapi import APIRouter

from app.core.errors import ERROR_RESPONSES
from app.modules.appointments.router import router as appointments_router
from app.modules.catalog.router import router as catalog_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.finance.router import router as finance_router
from app.modules.health.router import router as health_router
from app.modules.identity.router import router as auth_router
from app.modules.payments.router import router as payments_router
from app.modules.scheduling.router import router as scheduling_router
from app.modules.tenancy.router import router as management_router
from app.modules.workforce.router import router as workforce_router

router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(management_router)
router.include_router(catalog_router)
router.include_router(workforce_router)
router.include_router(scheduling_router)
router.include_router(appointments_router)
router.include_router(payments_router)
router.include_router(dashboard_router)
router.include_router(finance_router)
