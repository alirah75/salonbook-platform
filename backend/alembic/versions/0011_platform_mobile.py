"""Mobile identities for the separately deployed platform console."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE platform_auth_throttles (key bytea PRIMARY KEY, attempts integer NOT NULL, expires_at timestamptz NOT NULL, CONSTRAINT ck_platform_auth_throttles_values CHECK (attempts > 0 AND octet_length(key) = 32))"
    )
    op.execute(
        "CREATE INDEX ix_platform_auth_throttles_expires_at ON platform_auth_throttles (expires_at)"
    )
    op.execute("ALTER TABLE platform_users ALTER COLUMN email_normalized DROP NOT NULL")
    op.execute("ALTER TABLE platform_users ADD COLUMN phone_normalized varchar(16)")
    op.execute(
        "ALTER TABLE platform_users ADD COLUMN display_name varchar(160) NOT NULL DEFAULT 'Platform administrator'"
    )
    op.execute(
        "ALTER TABLE platform_users ADD CONSTRAINT uq_platform_users_phone_normalized UNIQUE (phone_normalized)"
    )
    op.execute(
        "ALTER TABLE platform_users ADD CONSTRAINT ck_platform_users_phone_normalized CHECK (phone_normalized IS NULL OR phone_normalized ~ '^\\+989[0-9]{9}$')"
    )
    op.execute(
        "INSERT INTO permissions (code, description) VALUES ('platform.manage', 'Operate the separate platform console') ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    # Fail transactionally rather than invent email addresses or discard mobile identities.
    op.execute("ALTER TABLE platform_users ALTER COLUMN email_normalized SET NOT NULL")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM platform_users WHERE phone_normalized IS NOT NULL OR display_name <> 'Platform administrator') THEN
            RAISE EXCEPTION 'Platform identity rollback would discard mobile identity data' USING ERRCODE = '23514';
        END IF;
    END $$;""")
    # Active role references also block removing this permission through existing FKs.
    op.execute("DELETE FROM permissions WHERE code = 'platform.manage'")
    op.execute("ALTER TABLE platform_users DROP CONSTRAINT ck_platform_users_phone_normalized")
    op.execute("ALTER TABLE platform_users DROP CONSTRAINT uq_platform_users_phone_normalized")
    op.execute("ALTER TABLE platform_users DROP COLUMN phone_normalized")
    op.execute("ALTER TABLE platform_users DROP COLUMN display_name")
    op.drop_table("platform_auth_throttles")
