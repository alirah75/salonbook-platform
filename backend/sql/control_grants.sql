-- Offline operator group; NEVER grant this to the API login or run it in a web process.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salonbook_control') THEN
        CREATE ROLE salonbook_control NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salonbook_control'
               AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolcanlogin)) THEN
        RAISE EXCEPTION 'salonbook_control exists with unsafe role attributes';
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO salonbook_control;
GRANT SELECT ON permissions, app_schema_revision TO salonbook_control;
GRANT SELECT, INSERT ON salons, users TO salonbook_control;
GRANT UPDATE (status) ON salons TO salonbook_control;
GRANT UPDATE (auth_version) ON users TO salonbook_control;
GRANT SELECT, INSERT, UPDATE ON tenant_domains TO salonbook_control;
GRANT SELECT, INSERT ON roles, role_permissions, role_assignments, customer_profiles,
    salon_settings, calendar_controls, platform_audit_logs TO salonbook_control;
GRANT SELECT ON sessions, auth_tokens TO salonbook_control;
GRANT UPDATE (revoked_at) ON sessions TO salonbook_control;
GRANT UPDATE (consumed_at) ON auth_tokens TO salonbook_control;
-- FORCE RLS remains in force, including for this group. No financial access or DDL.
