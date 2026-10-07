"""Booking permissions and explicit no-show grace policy."""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "appointment.reschedule_own": ("Reschedule own bookings", ("customer", "salon_manager")),
    "appointment.read_assigned": (
        "Read appointments assigned to own employee profile",
        ("employee", "salon_manager"),
    ),
    "appointment.finish_assigned": (
        "Complete or mark no-show for own assigned appointments",
        ("employee", "salon_manager"),
    ),
    "appointment.override": (
        "Override cancellation cutoff with an audited reason",
        ("salon_manager",),
    ),
}


def upgrade() -> None:
    op.add_column(
        "salon_settings",
        sa.Column("no_show_grace_minutes", sa.Integer(), server_default="15", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_salon_settings_no_show_grace"),
        "salon_settings",
        "no_show_grace_minutes BETWEEN 0 AND 240",
    )
    for table in ("roles", "role_permissions"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for code, (description, roles) in PERMISSIONS.items():
        op.get_bind().execute(
            sa.text("INSERT INTO permissions (code, description) VALUES (:code, :description)"),
            {"code": code, "description": description},
        )
        op.get_bind().execute(
            sa.text("""
            INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, :code FROM roles
            WHERE is_system AND deleted_at IS NULL AND code IN :roles
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING
        """).bindparams(sa.bindparam("roles", expanding=True)),
            {"code": code, "roles": roles},
        )
    for table in ("roles", "role_permissions"):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    for code in PERMISSIONS:
        op.get_bind().execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = :code"), {"code": code}
        )
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")
    for code in PERMISSIONS:
        op.get_bind().execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})
    op.drop_constraint(op.f("ck_salon_settings_no_show_grace"), "salon_settings", type_="check")
    op.drop_column("salon_settings", "no_show_grace_minutes")
