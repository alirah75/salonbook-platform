"""Trusted maintenance only: bind a known account to a mobile without claiming OTP proof."""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.database import Database
from app.modules.identity.models import User
from app.modules.identity.phone import normalize_mobile
from app.modules.identity.sessions import SessionService
from app.modules.operations.models import AuditLog


def bind_mobile(database: Database, tenant: UUID, user_id: UUID, phone: str) -> None:
    canonical = normalize_mobile(phone)
    with database.transaction(tenant) as session:
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.deleted_at is not None:
            raise ValueError("Account unavailable in the specified salon")
        if user.phone_normalized == canonical:
            return
        user.phone_normalized = canonical
        user.phone_verified_at = None
        SessionService.revoke_credentials(session, user, datetime.now(UTC))
        session.add(
            AuditLog(
                tenant_id=tenant,
                actor_kind="SYSTEM",
                action="auth.mobile_bound",
                entity_type="user",
                entity_id=user.id,
                reason="Trusted account migration",
                event_data={},
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--user", type=UUID, required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()
    database = Database(Settings(_env_file=args.env_file))
    try:
        bind_mobile(database, args.tenant, args.user, args.phone)
    except IntegrityError:
        raise SystemExit("Mobile identifier already assigned in this salon.") from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
    finally:
        database.dispose()
    print(
        "Mobile binding complete; any changed identity requires a new login. No OTP verification was claimed."
    )


if __name__ == "__main__":
    main()
