from sqlalchemy.orm import Session

from app.modules.identity.context import AuthContext
from app.modules.identity.models import User
from app.modules.operations.models import AuditLog


def audit(session: Session, context: AuthContext, action: str, user: User | None = None) -> None:
    session.add(
        AuditLog(
            tenant_id=context.tenant_id,
            actor_kind="USER" if user else "SYSTEM",
            actor_id=user.id if user else None,
            action=action,
            entity_type="user",
            entity_id=user.id if user else None,
            request_id=context.request_id,
            ip_address=context.ip,
            event_data={},
        )
    )
