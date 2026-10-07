-- Separate web control plane. NEVER grant this group to the salon API login.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salonbook_platform') THEN
        CREATE ROLE salonbook_platform NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salonbook_platform' AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolcanlogin)) THEN
        RAISE EXCEPTION 'Unsafe platform group';
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO salonbook_platform;
GRANT SELECT ON permissions, app_schema_revision, platform_users, platform_roles, platform_role_permissions, platform_role_assignments TO salonbook_platform;
GRANT SELECT, INSERT, UPDATE ON platform_sessions TO salonbook_platform;
-- Row locks require UPDATE on at least one column; identity/security fields stay read-only.
GRANT UPDATE (updated_at) ON platform_users TO salonbook_platform;
GRANT SELECT, INSERT, UPDATE, DELETE ON platform_auth_throttles TO salonbook_platform;
GRANT SELECT, INSERT ON salons, users, roles, role_permissions, role_assignments, customer_profiles, salon_settings, calendar_controls, platform_audit_logs TO salonbook_platform;
GRANT UPDATE (status) ON salons TO salonbook_platform;
GRANT UPDATE (auth_version) ON users TO salonbook_platform;
GRANT SELECT, INSERT, UPDATE ON tenant_domains TO salonbook_platform;
GRANT SELECT ON sessions, auth_tokens TO salonbook_platform;
GRANT UPDATE (revoked_at) ON sessions TO salonbook_platform;
GRANT UPDATE (consumed_at) ON auth_tokens TO salonbook_platform;
-- Cross-tenant access is limited to salon directory metadata. Customer tables
-- still require an explicit tenant context and existing lifecycle locks.
DROP POLICY IF EXISTS platform_directory ON salons;
CREATE POLICY platform_directory ON salons FOR SELECT TO salonbook_platform USING (true);
-- No financial, scheduling, user-profile update or DDL permissions.
