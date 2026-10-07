"""Management permission catalog and existing system-role upgrade.

RLS stays enabled throughout. The migration owner temporarily lifts FORCE only
inside this DDL transaction to update system roles in salons without domains too.
Runtime roles still obey the existing policies. FORCE is restored before commit.
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

PERMISSIONS = (
    "profile.update",
    "salon.read",
    "salon.manage",
    "users.read",
    "users.manage",
    "roles.read",
)
ADDITIONS = {
    "customer": ("profile.update", "salon.read"),
    "employee": ("profile.update", "salon.read"),
    "line_manager": ("profile.update", "salon.read"),
    "salon_manager": (
        *PERMISSIONS,
        "appointment.create",
        "appointment.read_own",
        "appointment.cancel_own",
    ),
}


def upgrade() -> None:
    table = sa.table("permissions", sa.column("code", sa.String), sa.column("description", sa.Text))
    op.bulk_insert(table, [{"code": code, "description": code} for code in PERMISSIONS])
    for table_name in ("roles", "role_permissions"):
        op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
    for role, permissions in ADDITIONS.items():
        for permission in permissions:
            op.execute(
                sa.text("""
                INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, :permission FROM roles
                WHERE is_system AND code = :role AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING
            """).bindparams(role=role, permission=permission)
            )
    for table_name in ("roles", "role_permissions"):
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    for permission in PERMISSIONS:
        # Only remove permissions introduced by this revision; preserve older grants.
        op.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = :permission").bindparams(
                permission=permission
            )
        )
        op.execute(
            sa.text("DELETE FROM permissions WHERE code = :permission").bindparams(
                permission=permission
            )
        )
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")
