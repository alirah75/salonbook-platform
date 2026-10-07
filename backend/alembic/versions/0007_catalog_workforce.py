"""Scoped employee assignment and consistent free/paid offer prices."""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_line_services_price"), "line_services", type_="check")
    op.create_check_constraint(
        op.f("ck_line_services_price"),
        "line_services",
        "price_amount >= 0 AND is_free = (price_amount = 0)",
    )
    op.execute(
        "INSERT INTO permissions (code, description) VALUES ('staff.assign', 'Manage employee assignments in authorized lines')"
    )
    for name in ("roles", "role_permissions"):
        op.execute(f"ALTER TABLE {name} NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        INSERT INTO role_permissions (tenant_id, role_id, permission_code)
        SELECT tenant_id, id, 'staff.assign' FROM roles
        WHERE is_system AND code IN ('salon_manager', 'line_manager') AND deleted_at IS NULL
        ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING
    """)
    for name in ("roles", "role_permissions"):
        op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_line_services_price"), "line_services", type_="check")
    op.create_check_constraint(
        op.f("ck_line_services_price"),
        "line_services",
        "price_amount >= 0 AND (price_amount > 0 OR is_free)",
    )
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    op.execute(sa.text("DELETE FROM role_permissions WHERE permission_code = 'staff.assign'"))
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")
    op.execute(sa.text("DELETE FROM permissions WHERE code = 'staff.assign'"))
