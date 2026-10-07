from unittest.mock import patch

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from alembic import command
from scripts.postgres_lab import temporary_postgres

pytestmark = pytest.mark.postgres


def test_platform_mobile_migration_preserves_legacy_and_blocks_lossy_rollback() -> None:
    with (
        temporary_postgres() as lab,
        patch.dict("os.environ", {"DATABASE_MIGRATION_URL": lab.owner_url}),
    ):
        config = Config("alembic.ini")
        command.upgrade(config, "0010")
        with lab.admin.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform_users (email_normalized, password_hash) VALUES ('legacy@example.test', 'legacy-only')"
                )
            )
        command.upgrade(config, "head")
        with lab.admin.begin() as conn:
            assert tuple(
                conn.execute(
                    text(
                        "SELECT email_normalized, password_hash, phone_normalized FROM platform_users"
                    )
                ).one()
            ) == ("legacy@example.test", "legacy-only", None)
            conn.execute(
                text(
                    "INSERT INTO platform_users (phone_normalized, password_hash, display_name) VALUES ('+989121234567', 'mobile-only', 'Mobile admin')"
                )
            )
        with pytest.raises(IntegrityError):
            command.downgrade(config, "0010")
        with lab.admin.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM platform_users")) == 2
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0011"
