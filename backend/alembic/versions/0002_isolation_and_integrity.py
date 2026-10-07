"""Tenant isolation, immutable evidence and database-managed timestamps.

Revision ID: 0002
Revises: 0001
The lists below are deliberately frozen; migrations never import live app models.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "appointment_history",
    "appointment_items",
    "appointments",
    "audit_logs",
    "auth_throttles",
    "auth_tokens",
    "background_jobs",
    "calendar_controls",
    "calendars",
    "callback_events",
    "credit_notes",
    "customer_profiles",
    "day_overrides",
    "employee_lines",
    "employee_profiles",
    "employee_services",
    "financial_entries",
    "idempotency_records",
    "invoice_items",
    "invoices",
    "line_services",
    "lines",
    "notifications",
    "outbox_events",
    "payment_accounts",
    "payment_allocations",
    "payment_attempts",
    "payment_intents",
    "payment_transactions",
    "receipts",
    "refunds",
    "role_assignments",
    "role_permissions",
    "roles",
    "salon_settings",
    "schedule_blocks",
    "services",
    "sessions",
    "special_periods",
    "support_grants",
    "users",
    "weekly_periods",
)
MUTABLE_TABLES = (
    "appointments",
    "auth_throttles",
    "background_jobs",
    "calendar_controls",
    "calendars",
    "customer_profiles",
    "day_overrides",
    "employee_lines",
    "employee_profiles",
    "employee_services",
    "idempotency_records",
    "line_services",
    "lines",
    "notifications",
    "payment_accounts",
    "payment_attempts",
    "payment_intents",
    "platform_roles",
    "platform_sessions",
    "platform_users",
    "refunds",
    "role_assignments",
    "roles",
    "salon_settings",
    "salons",
    "schedule_blocks",
    "services",
    "sessions",
    "special_periods",
    "tenant_domains",
    "users",
    "weekly_periods",
)
APPEND_ONLY_TABLES = (
    "appointment_history",
    "appointment_items",
    "audit_logs",
    "callback_events",
    "credit_notes",
    "financial_entries",
    "invoice_items",
    "invoices",
    "outbox_events",
    "payment_allocations",
    "payment_transactions",
    "platform_audit_logs",
    "receipts",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA app_private")
    op.execute("REVOKE ALL ON SCHEMA app_private FROM PUBLIC")
    op.execute("""
        CREATE FUNCTION app_private.touch_updated_at() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION app_private.guard_tenant_identity() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.id IS DISTINCT FROM OLD.id THEN
                RAISE EXCEPTION 'Tenant and record identity are immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION app_private.reject_evidence_mutation() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Evidence is append-only; use a compensating record' USING ERRCODE = '55000';
        END $$
    """)
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app_private FROM PUBLIC")
    tenant_expression = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" USING ({tenant_expression}) WITH CHECK ({tenant_expression})'
        )
        op.execute(
            f'CREATE TRIGGER guard_identity BEFORE UPDATE ON "{table}" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity()'
        )
    op.execute("ALTER TABLE salons ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE salons FORCE ROW LEVEL SECURITY")
    salon_expression = "id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"CREATE POLICY tenant_isolation ON salons USING ({salon_expression}) WITH CHECK ({salon_expression})"
    )
    for table in MUTABLE_TABLES:
        op.execute(
            f'CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "{table}" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at()'
        )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f'CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation()'
        )
    # Only verified public hostname -> tenant mappings cross the pre-auth boundary.
    op.execute(
        "CREATE VIEW tenant_hostnames WITH (security_barrier = true) AS SELECT hostname, tenant_id FROM tenant_domains WHERE is_active AND verified_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP VIEW tenant_hostnames")
    for table in APPEND_ONLY_TABLES:
        op.execute(f'DROP TRIGGER immutable_evidence ON "{table}"')
    for table in MUTABLE_TABLES:
        op.execute(f'DROP TRIGGER touch_timestamp ON "{table}"')
    for table in TENANT_TABLES:
        op.execute(f'DROP TRIGGER guard_identity ON "{table}"')
    for table in (*TENANT_TABLES, "salons"):
        op.execute(f'DROP POLICY tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.execute("DROP FUNCTION app_private.touch_updated_at()")
    op.execute("DROP FUNCTION app_private.guard_tenant_identity()")
    op.execute("DROP FUNCTION app_private.reject_evidence_mutation()")
    op.execute("DROP SCHEMA app_private")
