"""Application factory: imports have no database or network side effects."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import router
from app.core.config import Settings
from app.core.errors import database_unavailable_handler, register_exception_handlers
from app.core.logging import configure_logging, logger
from app.core.middleware import (
    RequestContextMiddleware,
    RequestLimitsMiddleware,
    SafeExceptionMiddleware,
)
from app.core.runtime import AppRuntime
from app.db.database import Database, DatabaseNotReady
from app.modules.health.service import HealthService
from app.modules.identity.runtime import build_auth


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    configure_logging(config.log_level)
    db = database if database is not None else Database(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await run_in_threadpool(db.validate_ready)
            logger.info("application.started", extra={"event": "application.started"})
            yield
        except DatabaseNotReady as exc:
            logger.error(
                "application.startup_failed",
                extra={"event": "application.startup_failed", "error_code": exc.code},
            )
            raise RuntimeError(
                "Database prerequisites failed; check migration, runtime role and connectivity."
            ) from None
        finally:
            await run_in_threadpool(db.dispose)
            logger.info("application.stopped", extra={"event": "application.stopped"})

    app = FastAPI(
        title="SalonBook API",
        version="0.1.0",
        debug=False,
        lifespan=lifespan,
        docs_url="/api/v1/docs" if config.documentation_enabled else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        openapi_url="/api/v1/openapi.json" if config.documentation_enabled else None,
        middleware=[
            Middleware(RequestContextMiddleware, production=config.environment == "production"),
            Middleware(
                CORSMiddleware,
                allow_origins=list(config.cors_origins),
                allow_credentials=True,
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
                expose_headers=["X-Request-ID"],
            ),
            Middleware(
                TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts), www_redirect=False
            ),
            Middleware(SafeExceptionMiddleware),
            Middleware(RequestLimitsMiddleware, production=config.environment == "production"),
        ],
    )
    app.state.runtime = AppRuntime(config, db, HealthService(db), build_auth(db, config))
    register_exception_handlers(app)
    app.add_exception_handler(DatabaseNotReady, database_unavailable_handler)
    app.include_router(router)
    return app
