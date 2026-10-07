"""Add canonical mobile login without inventing identifiers for existing accounts."""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "customer_profiles",
        "contact_preference",
        existing_type=sa.String(32),
        server_default="NONE",
    )
    op.alter_column("users", "email_normalized", existing_type=sa.String(254), nullable=True)
    op.add_column("users", sa.Column("phone_normalized", sa.String(16), nullable=True))
    op.add_column(
        "users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint(
        "uq_users_tenant_id_phone_normalized", "users", ["tenant_id", "phone_normalized"]
    )
    op.create_check_constraint(
        op.f("ck_users_phone_normalized"),
        "users",
        "phone_normalized IS NULL OR phone_normalized ~ '^\\+989[0-9]{9}$'",
    )
    op.create_check_constraint(
        op.f("ck_users_phone_verification"),
        "users",
        "phone_verified_at IS NULL OR phone_normalized IS NOT NULL",
    )


def downgrade() -> None:
    # NOT NULL fails safely if phone-only accounts exist; do not invent email addresses.
    op.alter_column("users", "email_normalized", existing_type=sa.String(254), nullable=False)
    op.drop_constraint(op.f("ck_users_phone_verification"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_phone_normalized"), "users", type_="check")
    op.drop_constraint("uq_users_tenant_id_phone_normalized", "users", type_="unique")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "phone_normalized")
    op.alter_column(
        "customer_profiles",
        "contact_preference",
        existing_type=sa.String(32),
        server_default="EMAIL",
    )
