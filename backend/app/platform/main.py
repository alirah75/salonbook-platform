from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.errors import AppError, register_exception_handlers
from app.core.middleware import (
    RequestContextMiddleware,
    RequestLimitsMiddleware,
    SafeExceptionMiddleware,
)
from app.modules.identity.schemas import LoginInput
from app.modules.operations.models import PlatformAuditLog
from app.modules.tenancy.administration import (
    OperationReason,
    TenantAdministration,
    TenantCreate,
    canonical_hostname,
)
from app.modules.tenancy.models import Salon, TenantDomain
from app.platform.config import PlatformSettings
from app.platform.service import Identity, PlatformService


class CreateTenant(TenantCreate, OperationReason):
    pass


class StatusWrite(OperationReason):
    status: Literal["ACTIVE", "SUSPENDED"]


class DomainWrite(OperationReason):
    hostname: str
    operation: Literal["add", "activate", "disable"]
    ownership_verified: bool = False


class Account(BaseModel):
    id: UUID
    phone: str | None
    display_name: str


class SessionView(BaseModel):
    user: Account
    csrf_token: str
    expires_at: datetime


def session_view(identity: Identity) -> SessionView:
    return SessionView(
        user=Account(
            id=identity.user.id,
            phone=identity.user.phone_normalized,
            display_name=identity.user.display_name,
        ),
        csrf_token=identity.csrf,
        expires_at=identity.session.expires_at,
    )


def create_platform_app(
    settings: PlatformSettings | None = None, service: PlatformService | None = None
) -> FastAPI:
    config = settings or PlatformSettings()
    control = service or PlatformService(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(control.validate_ready)
        try:
            yield
        finally:
            control.engine.dispose()

    async def guard(request: Request) -> None:
        await run_in_threadpool(control.api_throttle)
        if request.method in {"GET", "HEAD"}:
            return
        if request.headers.get("origin") != config.public_origin:
            raise AppError("csrf_failed", "Invalid platform origin.", 403)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise AppError("invalid_content_type", "JSON is required.", 415)

    app = FastAPI(
        title="SalonBook Platform",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        dependencies=[Depends(guard)],
        middleware=[
            Middleware(RequestContextMiddleware, production=config.environment == "production"),
            Middleware(
                TrustedHostMiddleware,
                allowed_hosts=[urlsplit(config.public_origin).hostname or ""],
                www_redirect=False,
            ),
            Middleware(SafeExceptionMiddleware),
            Middleware(RequestLimitsMiddleware, production=config.environment == "production"),
        ],
    )
    register_exception_handlers(app)

    def current(request: Request) -> Iterator[tuple[Session, Identity]]:
        with control.authorized(
            request.cookies.get(config.cookie_name, ""),
            request.headers.get("x-csrf-token", "")
            if request.method not in {"GET", "HEAD"}
            else None,
        ) as identity:
            yield identity

    Current = Annotated[tuple[Session, Identity], Depends(current)]
    prefix = "/platform/api/v1"

    @app.post(prefix + "/auth/login", response_model=SessionView)
    def login(payload: LoginInput, request: Request, response: Response) -> SessionView:
        raw, identity = control.login(payload, request.cookies.get(config.cookie_name, ""))
        response.set_cookie(
            config.cookie_name,
            raw,
            max_age=8 * 3600,
            path="/platform",
            secure=config.environment == "production",
            httponly=True,
            samesite="strict",
        )
        return session_view(identity)

    @app.get(prefix + "/auth/me", response_model=SessionView)
    def me(auth: Current) -> SessionView:
        return session_view(auth[1])

    @app.post(prefix + "/auth/logout", status_code=204)
    def logout(auth: Current, response: Response) -> None:
        auth[1].session.revoked_at = datetime.now(UTC)
        auth[0].add(
            PlatformAuditLog(
                actor_id=auth[1].user.id,
                action="platform.logout",
                entity_id=auth[1].user.id,
                event_data={},
            )
        )
        response.delete_cookie(
            config.cookie_name,
            path="/platform",
            secure=config.environment == "production",
            httponly=True,
            samesite="strict",
        )

    @app.get(prefix + "/salons")
    def salons(
        auth: Current,
        limit: Annotated[int, Query(ge=1, le=100)] = 24,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    ) -> dict[str, object]:
        session = auth[0]
        rows = list(
            session.scalars(
                select(Salon)
                .order_by(Salon.created_at.desc(), Salon.id)
                .limit(limit + 1)
                .offset(offset)
            )
        )
        domains = list(
            session.scalars(
                select(TenantDomain)
                .where(TenantDomain.tenant_id.in_([row.id for row in rows[:limit]]))
                .order_by(TenantDomain.hostname)
            )
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "name": row.name,
                    "status": row.status,
                    "timezone": row.timezone,
                    "created_at": row.created_at,
                    "domains": [
                        {
                            "hostname": d.hostname,
                            "is_active": d.is_active,
                            "verified": d.verified_at is not None,
                        }
                        for d in domains
                        if d.tenant_id == row.id
                    ],
                }
                for row in rows[:limit]
            ],
            "has_more": len(rows) > limit,
            "limit": limit,
            "offset": offset,
        }

    @app.post(prefix + "/salons", status_code=201)
    def create(payload: CreateTenant, auth: Current) -> dict[str, UUID]:
        tenant = TenantAdministration(control.engine, control.security, auth[1].user.id).create(
            TenantCreate(**payload.model_dump(exclude={"reason"})), payload.reason
        )
        return {"id": tenant}

    @app.patch(prefix + "/salons/{tenant}/status", status_code=204)
    def status(tenant: UUID, payload: StatusWrite, auth: Current) -> None:
        TenantAdministration(control.engine, control.security, auth[1].user.id).status(
            tenant, payload.status, payload.reason
        )

    @app.post(prefix + "/salons/{tenant}/domains", status_code=204)
    def domain(tenant: UUID, payload: DomainWrite, auth: Current) -> None:
        if payload.operation == "activate" and not payload.ownership_verified:
            raise AppError(
                "ownership_required", "Confirm domain ownership and routing before activation.", 422
            )
        try:
            hostname = canonical_hostname(payload.hostname)
        except ValueError:
            raise AppError("invalid_hostname", "Invalid hostname.", 422) from None
        TenantAdministration(control.engine, control.security, auth[1].user.id).domain(
            tenant, hostname, payload.operation, payload.reason
        )

    @app.get(prefix + "/audit")
    def audit(
        auth: Current,
        limit: Annotated[int, Query(ge=1, le=100)] = 24,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    ) -> dict[str, object]:
        rows = list(
            auth[0].scalars(
                select(PlatformAuditLog)
                .order_by(PlatformAuditLog.created_at.desc(), PlatformAuditLog.id)
                .limit(limit + 1)
                .offset(offset)
            )
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "actor_id": row.actor_id,
                    "action": row.action,
                    "entity_id": row.entity_id,
                    "created_at": row.created_at,
                    "reason": row.event_data.get("reason"),
                }
                for row in rows[:limit]
            ],
            "has_more": len(rows) > limit,
            "limit": limit,
            "offset": offset,
        }

    return app
