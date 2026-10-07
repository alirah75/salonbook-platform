from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.database import Database
from app.modules.tenancy.locks import require_active_tenant
from app.modules.tenancy.models import Salon


@dataclass(frozen=True)
class AuthContext:
    tenant_id: UUID
    origin: str
    ip: str
    request_id: UUID


def require_active_context(session: Session, context: AuthContext) -> None:
    require_active_tenant(session, context.tenant_id)
    # Resolve again under the lifecycle lock: domain retirement may have happened
    # between the HTTP dependency and the service transaction.
    tenant = session.scalar(
        text("SELECT tenant_id FROM tenant_hostnames WHERE hostname = :host"),
        {"host": urlsplit(context.origin).hostname},
    )
    if tenant != context.tenant_id:
        raise AppError("unknown_salon", "Salon unavailable.", 404)


def resolve_context(request: Request, database: Database, settings: Settings) -> AuthContext:
    if settings.environment == "production" and request.url.scheme != "https":
        raise AppError("https_required", "HTTPS is required.", 400)
    hostname = (request.url.hostname or "").lower()
    with database.engine.connect() as connection:
        identifier = connection.scalar(
            text("SELECT tenant_id FROM tenant_hostnames WHERE hostname = :host"),
            {"host": hostname},
        )
    if not isinstance(identifier, UUID):
        raise AppError("unknown_salon", "Salon unavailable.", 404)
    with database.transaction(identifier, read_only=True) as session:
        if session.scalar(select(Salon.status).where(Salon.id == identifier)) != "ACTIVE":
            raise AppError("unknown_salon", "Salon unavailable.", 404)
    scheme = "https" if settings.environment == "production" else request.url.scheme
    port = f":{settings.auth_public_port}" if settings.auth_public_port else ""
    try:
        peer = str(ip_address(request.client.host)) if request.client else "0.0.0.0"
    except ValueError:
        peer = "0.0.0.0"  # Test transport; never trust X-Forwarded-For.
    from app.core.logging import request_id_context

    return AuthContext(
        identifier, f"{scheme}://{hostname}{port}", peer, UUID(request_id_context.get() or "")
    )
