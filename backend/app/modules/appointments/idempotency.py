import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.base import JsonObject
from app.modules.appointments.domain import ExpiredHold
from app.modules.appointments.models import IdempotencyRecord
from app.modules.appointments.schemas import AppointmentResponse
from app.modules.identity.context import AuthContext


@dataclass(frozen=True)
class Outcome:
    status: int
    body: JsonObject
    replayed: bool = False


def execute(
    session: Session,
    context: AuthContext,
    actor: UUID,
    operation: str,
    key: str,
    payload: JsonObject,
    callback: Callable[[], AppointmentResponse],
    *,
    status: int = 200,
) -> Outcome:
    # User/session lock serializes keys for this actor; uniqueness is a second guard.
    if re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key) is None:
        raise AppError("idempotency_key", "Use an 8 to 128 character idempotency key.", 422)
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).digest()
    record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == actor,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key == key,
        )
    )
    now = datetime.now(UTC)
    if record is not None:
        if record.request_hash != digest:
            raise AppError("idempotency_conflict", "This key was used with different input.", 409)
        if record.expires_at <= now:
            raise AppError(
                "idempotency_expired",
                "This key has expired. Review the booking before using a new key.",
                409,
            )
        if (
            record.state != "COMPLETED"
            or record.response_status is None
            or record.response_body is None
        ):
            raise AppError(
                "booking_busy", "Request is still processing. Retry with the same key.", 409
            )
        return Outcome(record.response_status, record.response_body, True)
    record = IdempotencyRecord(
        tenant_id=context.tenant_id,
        actor_id=actor,
        operation=operation,
        key=key,
        request_hash=digest,
        expires_at=now + timedelta(days=7),
    )
    session.add(record)
    session.flush()
    try:
        with session.begin_nested():
            try:
                body = callback().model_dump(mode="json")
            except ExpiredHold as expired:
                status = expired.status_code
                body = {
                    "error": {
                        "code": expired.code,
                        "message": expired.public_message,
                        "request_id": str(context.request_id),
                        "details": [],
                    }
                }
            session.flush()
    except AppError as exc:
        if exc.status_code >= 500:
            raise
        status = exc.status_code
        body = {
            "error": {
                "code": exc.code,
                "message": exc.public_message,
                "request_id": str(context.request_id),
                "details": [d.model_dump(mode="json") for d in exc.details],
            }
        }
    record.state, record.response_status, record.response_body = "COMPLETED", status, body
    return Outcome(status, body)
