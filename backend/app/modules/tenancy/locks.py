"""Lock order: lifecycle -> management (writes) -> calendar (when needed) -> User -> Session.

Authentication shares the lifecycle lock. Trusted suspension takes it exclusively,
so it cannot race an in-flight login or an authorized business transaction.
"""

import hashlib
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.tenancy.models import Salon


def tenant_lock(session: Session, tenant: UUID, purpose: str, *, shared: bool = False) -> None:
    key = int.from_bytes(
        hashlib.blake2b(f"salonbook:{purpose}:{tenant}".encode(), digest_size=8).digest(),
        signed=True,
    )
    statement = (
        "SELECT pg_advisory_xact_lock_shared(:key)"
        if shared
        else "SELECT pg_advisory_xact_lock(:key)"
    )
    session.execute(text(statement), {"key": key})


def require_active_tenant(session: Session, tenant: UUID) -> None:
    tenant_lock(session, tenant, "lifecycle", shared=True)
    if session.scalar(select(Salon.status).where(Salon.id == tenant)) != "ACTIVE":
        raise AppError("unknown_salon", "Salon unavailable.", 404)
