-- Run once using a database administrator AFTER `alembic upgrade head`.
-- This is a NOLOGIN privilege group, not a user and not a stored password.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salonbook_runtime') THEN
        CREATE ROLE salonbook_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salonbook_runtime'
               AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolcanlogin)) THEN
        RAISE EXCEPTION 'salonbook_runtime exists with unsafe role attributes';
    END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO salonbook_runtime;
GRANT SELECT ON salons, permissions, tenant_hostnames, app_schema_revision TO salonbook_runtime;
-- Tenant managers may rename their salon; lifecycle/domain control stays separate.
GRANT UPDATE (name) ON salons TO salonbook_runtime;

GRANT SELECT, INSERT, UPDATE ON
    appointments, auth_throttles, auth_tokens, background_jobs, calendar_controls,
    calendars, customer_profiles, day_overrides, employee_lines, employee_profiles,
    employee_services, idempotency_records, line_services, lines, notifications,
    payment_accounts, payment_attempts, payment_intents, refunds, role_assignments,
    roles, salon_settings, schedule_blocks, services, sessions, special_periods,
    users, weekly_periods, mock_orders
TO salonbook_runtime;

GRANT SELECT, INSERT ON
    appointment_history, appointment_items, audit_logs, callback_events,
    credit_notes, financial_entries, invoice_items, invoices, outbox_events,
    payment_allocations, payment_transactions, receipts, role_permissions, mock_refunds
TO salonbook_runtime;

GRANT DELETE ON auth_throttles, auth_tokens, background_jobs, idempotency_records,
    notifications, role_permissions, sessions, weekly_periods, special_periods, day_overrides
TO salonbook_runtime;

-- No blanket grants, no ownership, no TRUNCATE, no platform/control-plane writes.
-- A provisioned application LOGIN receives membership in this group separately.
