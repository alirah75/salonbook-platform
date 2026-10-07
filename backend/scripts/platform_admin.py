"""Offline bootstrap only; platform web credentials cannot create platform users."""

import argparse
import os
from getpass import getpass
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

from app.db.schema import REQUIRED_SCHEMA_REVISION
from app.modules.access.models import (
    PlatformRole,
    PlatformRoleAssignment,
    PlatformRolePermission,
    PlatformUser,
)
from app.modules.identity.schemas import RegisterInput
from app.modules.identity.security import Security
from app.modules.operations.models import PlatformAuditLog


def bootstrap(engine: Engine, payload: RegisterInput, reason: str) -> UUID:
    if not reason.strip():
        raise ValueError("An operator reason is required.")
    security = Security(Fernet.generate_key().decode())
    encoded = security.hash_password(payload.password.get_secret_value())
    with Session(engine) as session, session.begin():
        if (
            session.scalar(text("SELECT version_num FROM app_schema_revision"))
            != REQUIRED_SCHEMA_REVISION
        ):
            raise RuntimeError("Migrate before bootstrap.")
        if session.scalar(
            select(PlatformUser.id).where(PlatformUser.phone_normalized == payload.phone)
        ):
            raise ValueError("Platform account already exists; bootstrap never resets passwords.")
        role = session.scalar(select(PlatformRole).where(PlatformRole.code == "super_admin"))
        if role is None:
            role = PlatformRole(code="super_admin")
            session.add(role)
            session.flush()
            session.add(PlatformRolePermission(role_id=role.id, permission_code="platform.manage"))
        user = PlatformUser(
            phone_normalized=payload.phone, display_name=payload.display_name, password_hash=encoded
        )
        session.add(user)
        session.flush()
        session.add(PlatformRoleAssignment(role_id=role.id, user_id=user.id))
        session.add(
            PlatformAuditLog(
                actor_id=user.id,
                entity_id=user.id,
                action="platform.bootstrapped",
                event_data={"reason": reason.strip(), "source": "offline_operator"},
            )
        )
        return user.id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    payload = RegisterInput(
        phone=args.phone,
        display_name=args.name,
        password=SecretStr(getpass("Platform password (15+ characters): ")),
    )
    engine = create_engine(os.environ["DATABASE_MIGRATION_URL"], hide_parameters=True)
    try:
        identifier = bootstrap(engine, payload, args.reason)
        print(f"Platform account created: {identifier}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
