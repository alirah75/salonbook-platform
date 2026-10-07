"""Bind sessions to authorization state and seed the executable permission catalog."""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

PERMISSIONS = (
    "profile.read",
    "session.manage",
    "appointment.create",
    "appointment.read_own",
    "appointment.cancel_own",
    "appointment.read",
    "appointment.manage",
    "catalog.manage",
    "staff.manage",
    "finance.read",
    "payment.refund",
    "roles.manage",
    "audit.read",
)


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("grants_fingerprint", sa.String(64), nullable=False, server_default=""),
    )
    table = sa.table("permissions", sa.column("code", sa.String), sa.column("description", sa.Text))
    op.bulk_insert(table, [{"code": code, "description": code} for code in PERMISSIONS])


def downgrade() -> None:
    op.drop_column("sessions", "grants_fingerprint")
    for code in PERMISSIONS:
        op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=code))
