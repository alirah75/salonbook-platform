"""Schedule management, scoped reads and employee leave requests."""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "schedule.read": "Read schedules in authorized scopes",
    "schedule.manage": "Manage schedules in authorized scopes",
    "schedule.read_own": "Read personal employee schedules",
    "leave.request_own": "Request leave for own employee calendar",
}


def upgrade() -> None:
    bind = op.get_bind()
    for code, description in PERMISSIONS.items():
        bind.execute(
            sa.text("INSERT INTO permissions (code, description) VALUES (:code, :description)"),
            {"code": code, "description": description},
        )
    for table in ("roles", "role_permissions"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for permission in PERMISSIONS:
        roles = (
            ("employee", "salon_manager")
            if permission.endswith("_own")
            else ("salon_manager", "line_manager")
        )
        bind.execute(
            sa.text("""
            INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, :permission FROM roles
            WHERE is_system AND code IN :roles AND deleted_at IS NULL
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING
        """).bindparams(sa.bindparam("roles", expanding=True)),
            {"permission": permission, "roles": roles},
        )
    for table in ("roles", "role_permissions"):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    for permission in PERMISSIONS:
        op.get_bind().execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = :code"),
            {"code": permission},
        )
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")
    for permission in PERMISSIONS:
        op.get_bind().execute(
            sa.text("DELETE FROM permissions WHERE code = :code"), {"code": permission}
        )
