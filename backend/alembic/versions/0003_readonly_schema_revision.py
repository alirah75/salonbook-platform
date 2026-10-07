"""Expose only migration revision metadata to the runtime readiness probe.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE VIEW app_schema_revision AS SELECT version_num FROM alembic_version")
    op.execute("REVOKE ALL ON app_schema_revision FROM PUBLIC")
    # Also handles an existing installation whose runtime group predates this migration.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salonbook_runtime') THEN
                GRANT SELECT ON app_schema_revision TO salonbook_runtime;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP VIEW app_schema_revision")
