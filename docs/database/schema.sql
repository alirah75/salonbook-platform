BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE permissions (
    code VARCHAR(100) NOT NULL, 
    description TEXT NOT NULL, 
    CONSTRAINT pk_permissions PRIMARY KEY (code), 
    CONSTRAINT ck_permissions_code CHECK (code ~ '^[a-z][a-z0-9_.]+$')
);

CREATE TABLE platform_roles (
    code VARCHAR(80) NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_platform_roles PRIMARY KEY (id), 
    CONSTRAINT uq_platform_roles_code UNIQUE (code)
);

CREATE TABLE platform_users (
    email_normalized VARCHAR(254) NOT NULL, 
    password_hash VARCHAR(512) NOT NULL, 
    mfa_secret_ref VARCHAR(255), 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_platform_users PRIMARY KEY (id), 
    CONSTRAINT ck_platform_users_email_normalized CHECK (email_normalized = lower(trim(email_normalized))), 
    CONSTRAINT uq_platform_users_email_normalized UNIQUE (email_normalized)
);

CREATE TABLE salons (
    name VARCHAR(160) NOT NULL, 
    timezone VARCHAR(80) DEFAULT 'Asia/Tehran' NOT NULL, 
    status VARCHAR(16) DEFAULT 'ACTIVE' NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_salons PRIMARY KEY (id), 
    CONSTRAINT ck_salons_status CHECK (status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')), 
    CONSTRAINT ck_salons_name_not_blank CHECK (length(trim(name)) > 0)
);

CREATE TABLE auth_throttles (
    bucket_hash BYTEA NOT NULL, 
    purpose VARCHAR(32) NOT NULL, 
    attempts INTEGER DEFAULT '0' NOT NULL, 
    blocked_until TIMESTAMP WITH TIME ZONE, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_auth_throttles PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_auth_throttles_bucket CHECK (attempts >= 0 AND octet_length(bucket_hash) = 32), 
    CONSTRAINT fk_auth_throttles_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_auth_throttles_tenant_id_bucket_hash_purpose UNIQUE (tenant_id, bucket_hash, purpose)
);

CREATE INDEX ix_auth_throttles_expiry ON auth_throttles (tenant_id, expires_at);

CREATE TABLE calendar_controls (
    version INTEGER DEFAULT '1' NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_calendar_controls PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_calendar_controls_version CHECK (version > 0), 
    CONSTRAINT fk_calendar_controls_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_calendar_controls_tenant_id UNIQUE (tenant_id)
);

CREATE TABLE lines (
    name VARCHAR(120) NOT NULL, 
    slug VARCHAR(100) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_lines PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_lines_name CHECK (length(trim(name)) > 0), 
    CONSTRAINT fk_lines_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_lines_tenant_id_slug UNIQUE (tenant_id, slug)
);

CREATE TABLE outbox_events (
    event_type VARCHAR(100) NOT NULL, 
    aggregate_id UUID NOT NULL, 
    deduplication_key VARCHAR(180) NOT NULL, 
    payload JSONB NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_outbox_events PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_outbox_events_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_outbox_events_tenant_id_deduplication_key UNIQUE (tenant_id, deduplication_key)
);

CREATE TABLE payment_accounts (
    provider VARCHAR(40) NOT NULL, 
    merchant_reference VARCHAR(160) NOT NULL, 
    secret_ref VARCHAR(255), 
    is_test BOOLEAN NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_payment_accounts PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_payment_accounts_mock_is_test CHECK (provider <> 'mock' OR is_test), 
    CONSTRAINT fk_payment_accounts_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_payment_accounts_id UNIQUE (id), 
    CONSTRAINT uq_payment_accounts_provider_merchant_reference_is_test UNIQUE (provider, merchant_reference, is_test), 
    CONSTRAINT uq_payment_accounts_tenant_id_id_is_test UNIQUE (tenant_id, id, is_test)
);

CREATE TABLE platform_audit_logs (
    actor_id UUID, 
    action VARCHAR(100) NOT NULL, 
    entity_id UUID, 
    event_data JSONB NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_platform_audit_logs PRIMARY KEY (id), 
    CONSTRAINT fk_platform_audit_logs_actor_id_platform_users FOREIGN KEY(actor_id) REFERENCES platform_users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_platform_audit_logs_actor_id ON platform_audit_logs (actor_id);

CREATE TABLE platform_role_assignments (
    role_id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_platform_role_assignments PRIMARY KEY (id), 
    CONSTRAINT fk_platform_role_assignments_role_id_platform_roles FOREIGN KEY(role_id) REFERENCES platform_roles (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_platform_role_assignments_user_id_platform_users FOREIGN KEY(user_id) REFERENCES platform_users (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_platform_role_assignments_role_id_user_id UNIQUE (role_id, user_id)
);

CREATE INDEX ix_platform_role_assignments_user_id ON platform_role_assignments (user_id);

CREATE TABLE platform_role_permissions (
    role_id UUID NOT NULL, 
    permission_code VARCHAR(100) NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_platform_role_permissions PRIMARY KEY (id), 
    CONSTRAINT fk_platform_role_permissions_permission_code_permissions FOREIGN KEY(permission_code) REFERENCES permissions (code) ON DELETE RESTRICT, 
    CONSTRAINT fk_platform_role_permissions_role_id_platform_roles FOREIGN KEY(role_id) REFERENCES platform_roles (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_platform_role_permissions_role_id_permission_code UNIQUE (role_id, permission_code)
);

CREATE INDEX ix_platform_role_permissions_permission_code ON platform_role_permissions (permission_code);

CREATE TABLE platform_sessions (
    user_id UUID NOT NULL, 
    token_hash BYTEA NOT NULL, 
    csrf_hash BYTEA NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    idle_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_platform_sessions PRIMARY KEY (id), 
    CONSTRAINT ck_platform_sessions_expiry CHECK (expires_at > created_at AND idle_expires_at <= expires_at), 
    CONSTRAINT ck_platform_sessions_hash_length CHECK (octet_length(token_hash) = 32 AND octet_length(csrf_hash) = 32), 
    CONSTRAINT fk_platform_sessions_user_id_platform_users FOREIGN KEY(user_id) REFERENCES platform_users (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_platform_sessions_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_platform_sessions_user_id ON platform_sessions (user_id);

CREATE TABLE roles (
    code VARCHAR(80) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    is_system BOOLEAN DEFAULT false NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_roles PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_roles_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_roles_tenant_id_code UNIQUE (tenant_id, code)
);

CREATE TABLE salon_settings (
    currency VARCHAR(3) DEFAULT 'IRR' NOT NULL, 
    hold_minutes INTEGER DEFAULT '10' NOT NULL, 
    slot_step_minutes INTEGER DEFAULT '15' NOT NULL, 
    min_notice_minutes INTEGER DEFAULT '60' NOT NULL, 
    booking_horizon_days INTEGER DEFAULT '90' NOT NULL, 
    cancel_before_minutes INTEGER DEFAULT '1440' NOT NULL, 
    max_services INTEGER DEFAULT '10' NOT NULL, 
    max_duration_minutes INTEGER DEFAULT '720' NOT NULL, 
    policy_version INTEGER DEFAULT '1' NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_salon_settings PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_salon_settings_currency CHECK (currency = 'IRR'), 
    CONSTRAINT ck_salon_settings_booking_limits CHECK (cancel_before_minutes >= 0 AND max_services BETWEEN 1 AND 20 AND max_duration_minutes BETWEEN 1 AND 1440), 
    CONSTRAINT ck_salon_settings_hold_minutes CHECK (hold_minutes BETWEEN 1 AND 60), 
    CONSTRAINT ck_salon_settings_booking_window CHECK (min_notice_minutes >= 0 AND booking_horizon_days BETWEEN 1 AND 366), 
    CONSTRAINT ck_salon_settings_policy_version CHECK (policy_version > 0), 
    CONSTRAINT ck_salon_settings_slot_step CHECK (slot_step_minutes BETWEEN 1 AND 120), 
    CONSTRAINT fk_salon_settings_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_salon_settings_tenant_id UNIQUE (tenant_id)
);

CREATE TABLE services (
    code VARCHAR(80) NOT NULL, 
    name VARCHAR(160) NOT NULL, 
    description TEXT, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_services PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_services_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_services_tenant_id_code UNIQUE (tenant_id, code)
);

CREATE TABLE support_grants (
    platform_user_id UUID NOT NULL, 
    reason TEXT NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_support_grants PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_support_grants_expiry_reason CHECK (expires_at > created_at AND length(trim(reason)) > 0), 
    CONSTRAINT fk_support_grants_platform_user_id_platform_users FOREIGN KEY(platform_user_id) REFERENCES platform_users (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_support_grants_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT
);

CREATE INDEX ix_support_grants_platform_user_id ON support_grants (platform_user_id);

CREATE TABLE tenant_domains (
    tenant_id UUID NOT NULL, 
    hostname VARCHAR(253) NOT NULL, 
    verified_at TIMESTAMP WITH TIME ZONE, 
    is_active BOOLEAN DEFAULT false NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_tenant_domains PRIMARY KEY (id), 
    CONSTRAINT ck_tenant_domains_canonical_hostname CHECK (hostname = lower(hostname) AND hostname !~ '[/ :]' AND length(hostname) > 0), 
    CONSTRAINT fk_tenant_domains_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_tenant_domains_hostname UNIQUE (hostname)
);

CREATE INDEX ix_tenant_domains_tenant_id ON tenant_domains (tenant_id);

CREATE TABLE users (
    email_normalized VARCHAR(254) NOT NULL, 
    password_hash VARCHAR(512) NOT NULL, 
    display_name VARCHAR(160) NOT NULL, 
    phone VARCHAR(24), 
    email_verified_at TIMESTAMP WITH TIME ZONE, 
    mfa_secret_ref VARCHAR(255), 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    auth_version INTEGER DEFAULT '1' NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_users PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_users_email_normalized CHECK (email_normalized = lower(trim(email_normalized)) AND position('@' in email_normalized) > 1), 
    CONSTRAINT ck_users_auth_version CHECK (auth_version > 0), 
    CONSTRAINT fk_users_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_users_tenant_id_email_normalized UNIQUE (tenant_id, email_normalized)
);

CREATE TABLE audit_logs (
    actor_kind VARCHAR(10) NOT NULL, 
    actor_id UUID, 
    platform_actor_id UUID, 
    action VARCHAR(100) NOT NULL, 
    entity_type VARCHAR(80) NOT NULL, 
    entity_id UUID, 
    request_id UUID, 
    ip_address INET, 
    reason TEXT, 
    event_data JSONB NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_audit_logs PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_audit_logs_actor CHECK ((actor_kind = 'USER' AND actor_id IS NOT NULL AND platform_actor_id IS NULL) OR (actor_kind = 'PLATFORM' AND actor_id IS NULL AND platform_actor_id IS NOT NULL) OR (actor_kind = 'SYSTEM' AND actor_id IS NULL AND platform_actor_id IS NULL)), 
    CONSTRAINT fk_audit_logs_platform_actor_id_platform_users FOREIGN KEY(platform_actor_id) REFERENCES platform_users (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_audit_logs_tenant_id_actor_id_users FOREIGN KEY(tenant_id, actor_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_audit_logs_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT
);

CREATE INDEX ix_audit_logs_actor ON audit_logs (tenant_id, actor_id, created_at);

CREATE INDEX ix_audit_logs_entity ON audit_logs (tenant_id, entity_type, entity_id, created_at);

CREATE INDEX ix_audit_logs_platform_actor_id ON audit_logs (platform_actor_id);

CREATE TABLE auth_tokens (
    user_id UUID NOT NULL, 
    purpose VARCHAR(18) NOT NULL, 
    token_hash BYTEA NOT NULL, 
    subject_version INTEGER NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    consumed_at TIMESTAMP WITH TIME ZONE, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_auth_tokens PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_auth_tokens_expiry CHECK (expires_at > created_at), 
    CONSTRAINT ck_auth_tokens_subject_version CHECK (subject_version > 0), 
    CONSTRAINT ck_auth_tokens_hash_length CHECK (octet_length(token_hash) = 32), 
    CONSTRAINT fk_auth_tokens_tenant_id_user_id_users FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_auth_tokens_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_auth_tokens_tenant_id_token_hash UNIQUE (tenant_id, token_hash), 
    CONSTRAINT ck_auth_tokens_token_purpose CHECK (purpose IN ('EMAIL_VERIFICATION', 'PASSWORD_RESET'))
);

CREATE INDEX ix_auth_tokens_tenant_id_user_id ON auth_tokens (tenant_id, user_id);

CREATE TABLE background_jobs (
    outbox_event_id UUID, 
    kind VARCHAR(100) NOT NULL, 
    deduplication_key VARCHAR(180) NOT NULL, 
    payload JSONB NOT NULL, 
    status VARCHAR(9) DEFAULT 'PENDING' NOT NULL, 
    attempts INTEGER DEFAULT '0' NOT NULL, 
    max_attempts INTEGER DEFAULT '10' NOT NULL, 
    run_after TIMESTAMP WITH TIME ZONE NOT NULL, 
    lease_owner UUID, 
    lease_until TIMESTAMP WITH TIME ZONE, 
    last_error_code VARCHAR(100), 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_background_jobs PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_background_jobs_lease CHECK ((status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_until IS NOT NULL) OR (status <> 'RUNNING' AND lease_owner IS NULL AND lease_until IS NULL)), 
    CONSTRAINT ck_background_jobs_attempts CHECK (attempts >= 0 AND max_attempts > 0), 
    CONSTRAINT fk_background_jobs_tenant_id_outbox_event_id_outbox_events FOREIGN KEY(tenant_id, outbox_event_id) REFERENCES outbox_events (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_background_jobs_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_background_jobs_tenant_id_deduplication_key UNIQUE (tenant_id, deduplication_key), 
    CONSTRAINT ck_background_jobs_job_status CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'DEAD'))
);

CREATE INDEX ix_background_jobs_tenant_id_outbox_event_id ON background_jobs (tenant_id, outbox_event_id);

CREATE INDEX ix_jobs_due ON background_jobs (tenant_id, run_after) WHERE status = 'PENDING';

CREATE INDEX ix_jobs_expired_lease ON background_jobs (tenant_id, lease_until) WHERE status = 'RUNNING';

CREATE TABLE customer_profiles (
    user_id UUID NOT NULL, 
    contact_preference VARCHAR(32) DEFAULT 'EMAIL' NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_customer_profiles PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_customer_profiles_tenant_id_user_id_users FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_customer_profiles_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_customer_profiles_tenant_id_user_id UNIQUE (tenant_id, user_id)
);

CREATE TABLE employee_profiles (
    user_id UUID NOT NULL, 
    public_name VARCHAR(160) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_employee_profiles PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_employee_profiles_tenant_id_user_id_users FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_employee_profiles_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_employee_profiles_tenant_id_user_id UNIQUE (tenant_id, user_id)
);

CREATE TABLE idempotency_records (
    actor_id UUID NOT NULL, 
    operation VARCHAR(100) NOT NULL, 
    key VARCHAR(128) NOT NULL, 
    request_hash BYTEA NOT NULL, 
    state VARCHAR(16) DEFAULT 'PROCESSING' NOT NULL, 
    response_status INTEGER, 
    response_body JSONB, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_idempotency_records PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_idempotency_records_completed_response CHECK (state <> 'COMPLETED' OR (response_status BETWEEN 200 AND 599 AND response_body IS NOT NULL)), 
    CONSTRAINT ck_idempotency_records_state_expiry CHECK (state IN ('PROCESSING', 'COMPLETED') AND expires_at > created_at), 
    CONSTRAINT ck_idempotency_records_hash_length CHECK (octet_length(request_hash) = 32), 
    CONSTRAINT fk_idempotency_records_tenant_id_actor_id_users FOREIGN KEY(tenant_id, actor_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_idempotency_records_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_idempotency_records_tenant_id_actor_id_operation_key UNIQUE (tenant_id, actor_id, operation, key)
);

CREATE INDEX ix_idempotency_expiry ON idempotency_records (tenant_id, expires_at);

CREATE TABLE line_services (
    line_id UUID NOT NULL, 
    service_id UUID NOT NULL, 
    price_amount BIGINT NOT NULL, 
    currency VARCHAR(3) DEFAULT 'IRR' NOT NULL, 
    duration_minutes INTEGER NOT NULL, 
    buffer_before_minutes INTEGER DEFAULT '0' NOT NULL, 
    buffer_after_minutes INTEGER DEFAULT '0' NOT NULL, 
    is_free BOOLEAN DEFAULT false NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_line_services PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_line_services_currency CHECK (currency = 'IRR'), 
    CONSTRAINT ck_line_services_buffers CHECK (buffer_before_minutes BETWEEN 0 AND 240 AND buffer_after_minutes BETWEEN 0 AND 240), 
    CONSTRAINT ck_line_services_duration CHECK (duration_minutes BETWEEN 1 AND 1440), 
    CONSTRAINT ck_line_services_price CHECK (price_amount >= 0 AND (price_amount > 0 OR is_free)), 
    CONSTRAINT fk_line_services_tenant_id_line_id_lines FOREIGN KEY(tenant_id, line_id) REFERENCES lines (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_line_services_tenant_id_service_id_services FOREIGN KEY(tenant_id, service_id) REFERENCES services (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_line_services_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_line_services_tenant_id_line_id_service_id UNIQUE (tenant_id, line_id, service_id)
);

CREATE INDEX ix_line_services_tenant_id_service_id ON line_services (tenant_id, service_id);

CREATE TABLE notifications (
    user_id UUID NOT NULL, 
    kind VARCHAR(80) NOT NULL, 
    title VARCHAR(180) NOT NULL, 
    body TEXT NOT NULL, 
    deduplication_key VARCHAR(180) NOT NULL, 
    read_at TIMESTAMP WITH TIME ZONE, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_notifications PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_notifications_tenant_id_user_id_users FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_notifications_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_notifications_tenant_id_user_id_deduplication_key UNIQUE (tenant_id, user_id, deduplication_key)
);

CREATE INDEX ix_notifications_unread ON notifications (tenant_id, user_id, created_at) WHERE read_at IS NULL;

CREATE TABLE role_assignments (
    user_id UUID NOT NULL, 
    role_id UUID NOT NULL, 
    scope VARCHAR(10) NOT NULL, 
    line_id UUID, 
    granted_by_id UUID, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_role_assignments PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_role_assignments_scope CHECK ((scope = 'TENANT' AND line_id IS NULL) OR (scope = 'LINE' AND line_id IS NOT NULL)), 
    CONSTRAINT fk_role_assignments_tenant_id_granted_by_id_users FOREIGN KEY(tenant_id, granted_by_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_role_assignments_tenant_id_line_id_lines FOREIGN KEY(tenant_id, line_id) REFERENCES lines (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_role_assignments_tenant_id_role_id_roles FOREIGN KEY(tenant_id, role_id) REFERENCES roles (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_role_assignments_tenant_id_user_id_users FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_role_assignments_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT
);

CREATE INDEX ix_role_assignments_tenant_id_granted_by_id ON role_assignments (tenant_id, granted_by_id);

CREATE INDEX ix_role_assignments_tenant_id_line_id ON role_assignments (tenant_id, line_id);

CREATE INDEX ix_role_assignments_tenant_id_role_id ON role_assignments (tenant_id, role_id);

CREATE INDEX ix_role_assignments_tenant_id_user_id ON role_assignments (tenant_id, user_id);

CREATE UNIQUE INDEX uq_role_assignments_active ON role_assignments (tenant_id, user_id, role_id, scope, line_id) NULLS NOT DISTINCT WHERE revoked_at IS NULL;

CREATE TABLE role_permissions (
    role_id UUID NOT NULL, 
    permission_code VARCHAR(100) NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_role_permissions PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_role_permissions_permission_code_permissions FOREIGN KEY(permission_code) REFERENCES permissions (code) ON DELETE RESTRICT, 
    CONSTRAINT fk_role_permissions_tenant_id_role_id_roles FOREIGN KEY(tenant_id, role_id) REFERENCES roles (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_role_permissions_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_role_permissions_tenant_id_role_id_permission_code UNIQUE (tenant_id, role_id, permission_code)
);

CREATE INDEX ix_role_permissions_permission_code ON role_permissions (permission_code);

CREATE TABLE sessions (
    user_id UUID NOT NULL, 
    token_hash BYTEA NOT NULL, 
    csrf_hash BYTEA NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    idle_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    auth_version INTEGER NOT NULL, 
    ip_address INET, 
    user_agent VARCHAR(512), 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_sessions PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_sessions_auth_version CHECK (auth_version > 0), 
    CONSTRAINT ck_sessions_expiry CHECK (expires_at > created_at AND idle_expires_at <= expires_at), 
    CONSTRAINT ck_sessions_hash_lengths CHECK (octet_length(token_hash) = 32 AND octet_length(csrf_hash) = 32), 
    CONSTRAINT fk_sessions_tenant_id_user_id_users FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_sessions_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_sessions_tenant_id_token_hash UNIQUE (tenant_id, token_hash)
);

CREATE INDEX ix_sessions_expiry ON sessions (tenant_id, expires_at) WHERE revoked_at IS NULL;

CREATE INDEX ix_sessions_tenant_id_user_id ON sessions (tenant_id, user_id);

CREATE TABLE employee_lines (
    employee_id UUID NOT NULL, 
    line_id UUID NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_employee_lines PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_employee_lines_tenant_id_employee_id_employee_profiles FOREIGN KEY(tenant_id, employee_id) REFERENCES employee_profiles (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_employee_lines_tenant_id_line_id_lines FOREIGN KEY(tenant_id, line_id) REFERENCES lines (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_employee_lines_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_employee_lines_tenant_id_employee_id_line_id UNIQUE (tenant_id, employee_id, line_id)
);

CREATE INDEX ix_employee_lines_tenant_id_line_id ON employee_lines (tenant_id, line_id);

CREATE TABLE appointments (
    customer_id UUID NOT NULL, 
    employee_id UUID NOT NULL, 
    line_id UUID NOT NULL, 
    status VARCHAR(16) DEFAULT 'AWAITING_PAYMENT' NOT NULL, 
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    occupied_starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    occupied_ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    occupied_period TSTZRANGE GENERATED ALWAYS AS (tstzrange(occupied_starts_at, occupied_ends_at, '[)'::text)) STORED NOT NULL, 
    duration_minutes INTEGER NOT NULL, 
    buffer_before_minutes INTEGER DEFAULT '0' NOT NULL, 
    buffer_after_minutes INTEGER DEFAULT '0' NOT NULL, 
    total_amount BIGINT NOT NULL, 
    currency VARCHAR(3) DEFAULT 'IRR' NOT NULL, 
    is_test BOOLEAN DEFAULT true NOT NULL, 
    hold_expires_at TIMESTAMP WITH TIME ZONE, 
    confirmed_at TIMESTAMP WITH TIME ZONE, 
    cancelled_at TIMESTAMP WITH TIME ZONE, 
    cancellation_reason TEXT, 
    policy_snapshot JSONB NOT NULL, 
    version INTEGER DEFAULT '1' NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_appointments PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ex_appointments_employee_period EXCLUDE USING gist (tenant_id WITH =, employee_id WITH =, occupied_period WITH &&) WHERE (status IN ('AWAITING_PAYMENT', 'CONFIRMED', 'COMPLETED', 'NO_SHOW')), 
    CONSTRAINT ck_appointments_buffers CHECK (buffer_before_minutes >= 0 AND buffer_after_minutes >= 0 AND occupied_starts_at = starts_at - buffer_before_minutes * interval '1 minute' AND occupied_ends_at = ends_at + buffer_after_minutes * interval '1 minute'), 
    CONSTRAINT ck_appointments_duration CHECK (duration_minutes > 0 AND ends_at = starts_at + duration_minutes * interval '1 minute'), 
    CONSTRAINT ck_appointments_hold CHECK (status <> 'AWAITING_PAYMENT' OR (hold_expires_at IS NOT NULL AND hold_expires_at > created_at AND hold_expires_at <= starts_at AND confirmed_at IS NULL)), 
    CONSTRAINT ck_appointments_confirmation CHECK (status NOT IN ('CONFIRMED', 'COMPLETED', 'NO_SHOW') OR confirmed_at IS NOT NULL), 
    CONSTRAINT ck_appointments_amount_currency_version CHECK (total_amount >= 0 AND currency = 'IRR' AND version > 0), 
    CONSTRAINT ck_appointments_interval CHECK (ends_at > starts_at AND occupied_starts_at <= starts_at AND occupied_ends_at >= ends_at), 
    CONSTRAINT fk_appointments_tenant_id_customer_id_customer_profiles FOREIGN KEY(tenant_id, customer_id) REFERENCES customer_profiles (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_appointments_tenant_id_employee_id_line_id_employee_lines FOREIGN KEY(tenant_id, employee_id, line_id) REFERENCES employee_lines (tenant_id, employee_id, line_id) ON DELETE RESTRICT, 
    CONSTRAINT fk_appointments_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_appointments_tenant_id_id_line_id UNIQUE (tenant_id, id, line_id), 
    CONSTRAINT uq_appointments_tenant_id_id_total_amount_currency_is_test UNIQUE (tenant_id, id, total_amount, currency, is_test), 
    CONSTRAINT ck_appointments_appointment_status CHECK (status IN ('AWAITING_PAYMENT', 'CONFIRMED', 'CANCELLED', 'COMPLETED', 'NO_SHOW', 'EXPIRED'))
);

CREATE INDEX ix_appointments_customer_start ON appointments (tenant_id, customer_id, starts_at);

CREATE INDEX ix_appointments_expiring ON appointments (tenant_id, hold_expires_at) WHERE status = 'AWAITING_PAYMENT';

CREATE INDEX ix_appointments_line_start ON appointments (tenant_id, line_id, starts_at);

CREATE INDEX ix_appointments_tenant_id_employee_id_line_id ON appointments (tenant_id, employee_id, line_id);

CREATE UNIQUE INDEX uq_appointments_customer_hold ON appointments (tenant_id, customer_id) WHERE status = 'AWAITING_PAYMENT';

CREATE TABLE calendars (
    scope VARCHAR(13) NOT NULL, 
    line_id UUID, 
    employee_id UUID, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_calendars PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_calendars_scope_target CHECK ((scope = 'SALON' AND line_id IS NULL AND employee_id IS NULL) OR (scope = 'LINE' AND line_id IS NOT NULL AND employee_id IS NULL) OR (scope = 'EMPLOYEE' AND line_id IS NULL AND employee_id IS NOT NULL) OR (scope = 'EMPLOYEE_LINE' AND line_id IS NOT NULL AND employee_id IS NOT NULL)), 
    CONSTRAINT fk_calendars_tenant_id_employee_id_line_id_employee_lines FOREIGN KEY(tenant_id, employee_id, line_id) REFERENCES employee_lines (tenant_id, employee_id, line_id) ON DELETE RESTRICT, 
    CONSTRAINT fk_calendars_tenant_id_employee_id_employee_profiles FOREIGN KEY(tenant_id, employee_id) REFERENCES employee_profiles (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_calendars_tenant_id_line_id_lines FOREIGN KEY(tenant_id, line_id) REFERENCES lines (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_calendars_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_calendars_tenant_id_scope_line_id_employee_id UNIQUE NULLS NOT DISTINCT (tenant_id, scope, line_id, employee_id), 
    CONSTRAINT ck_calendars_calendar_scope CHECK (scope IN ('SALON', 'LINE', 'EMPLOYEE', 'EMPLOYEE_LINE'))
);

CREATE INDEX ix_calendars_tenant_id_employee_id ON calendars (tenant_id, employee_id);

CREATE INDEX ix_calendars_tenant_id_employee_id_line_id ON calendars (tenant_id, employee_id, line_id);

CREATE INDEX ix_calendars_tenant_id_line_id ON calendars (tenant_id, line_id);

CREATE TABLE employee_services (
    employee_id UUID NOT NULL, 
    line_id UUID NOT NULL, 
    service_id UUID NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_employee_services PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_employee_services_tenant_id_employee_id_line_id_empl_13ab FOREIGN KEY(tenant_id, employee_id, line_id) REFERENCES employee_lines (tenant_id, employee_id, line_id) ON DELETE RESTRICT, 
    CONSTRAINT fk_employee_services_tenant_id_line_id_service_id_line_services FOREIGN KEY(tenant_id, line_id, service_id) REFERENCES line_services (tenant_id, line_id, service_id) ON DELETE RESTRICT, 
    CONSTRAINT fk_employee_services_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_employee_services_tenant_id_employee_id_line_id_service_id UNIQUE (tenant_id, employee_id, line_id, service_id)
);

CREATE INDEX ix_employee_services_tenant_id_line_id_service_id ON employee_services (tenant_id, line_id, service_id);

CREATE TABLE appointment_history (
    appointment_id UUID NOT NULL, 
    actor_id UUID, 
    action VARCHAR(80) NOT NULL, 
    reason TEXT, 
    event_data JSONB NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_appointment_history PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_appointment_history_tenant_id_actor_id_users FOREIGN KEY(tenant_id, actor_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_appointment_history_tenant_id_appointment_id_appointments FOREIGN KEY(tenant_id, appointment_id) REFERENCES appointments (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_appointment_history_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT
);

CREATE INDEX ix_appointment_history_tenant_id_actor_id ON appointment_history (tenant_id, actor_id);

CREATE INDEX ix_appointment_history_tenant_id_appointment_id ON appointment_history (tenant_id, appointment_id);

CREATE TABLE appointment_items (
    appointment_id UUID NOT NULL, 
    original_employee_id UUID NOT NULL, 
    line_id UUID NOT NULL, 
    service_id UUID NOT NULL, 
    position INTEGER NOT NULL, 
    service_name VARCHAR(160) NOT NULL, 
    line_name VARCHAR(120) NOT NULL, 
    employee_name VARCHAR(160) NOT NULL, 
    duration_minutes INTEGER NOT NULL, 
    buffer_before_minutes INTEGER DEFAULT '0' NOT NULL, 
    buffer_after_minutes INTEGER DEFAULT '0' NOT NULL, 
    amount BIGINT NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_appointment_items PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_appointment_items_values CHECK (position > 0 AND duration_minutes > 0 AND amount >= 0 AND buffer_before_minutes >= 0 AND buffer_after_minutes >= 0), 
    CONSTRAINT fk_appointment_items_tenant_id_appointment_id_line_id_a_917b FOREIGN KEY(tenant_id, appointment_id, line_id) REFERENCES appointments (tenant_id, id, line_id) ON DELETE RESTRICT, 
    CONSTRAINT fk_appointment_items_tenant_id_original_employee_id_lin_36ff FOREIGN KEY(tenant_id, original_employee_id, line_id, service_id) REFERENCES employee_services (tenant_id, employee_id, line_id, service_id) ON DELETE RESTRICT, 
    CONSTRAINT fk_appointment_items_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_appointment_items_tenant_id_appointment_id_position UNIQUE (tenant_id, appointment_id, position), 
    CONSTRAINT uq_appointment_items_tenant_id_id_appointment_id UNIQUE (tenant_id, id, appointment_id)
);

CREATE INDEX ix_appointment_items_tenant_id_appointment_id_line_id ON appointment_items (tenant_id, appointment_id, line_id);

CREATE INDEX ix_appointment_items_tenant_id_original_employee_id_lin_41fa ON appointment_items (tenant_id, original_employee_id, line_id, service_id);

CREATE TABLE day_overrides (
    calendar_id UUID NOT NULL, 
    local_date DATE NOT NULL, 
    mode VARCHAR(7) NOT NULL, 
    reason VARCHAR(300), 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_day_overrides PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_day_overrides_tenant_id_calendar_id_calendars FOREIGN KEY(tenant_id, calendar_id) REFERENCES calendars (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_day_overrides_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_day_overrides_tenant_id_calendar_id_local_date UNIQUE (tenant_id, calendar_id, local_date), 
    CONSTRAINT uq_day_overrides_tenant_id_id_mode UNIQUE (tenant_id, id, mode), 
    CONSTRAINT ck_day_overrides_day_override_mode CHECK (mode IN ('CLOSED', 'REPLACE'))
);

CREATE TABLE invoices (
    appointment_id UUID NOT NULL, 
    number VARCHAR(64) NOT NULL, 
    total_amount BIGINT NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    is_test BOOLEAN NOT NULL, 
    issued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    seller_snapshot JSONB NOT NULL, 
    buyer_snapshot JSONB NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_invoices PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_invoices_amount_currency CHECK (total_amount >= 0 AND currency = 'IRR'), 
    CONSTRAINT fk_invoices_tenant_id_appointment_id_total_amount_curre_e798 FOREIGN KEY(tenant_id, appointment_id, total_amount, currency, is_test) REFERENCES appointments (tenant_id, id, total_amount, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_invoices_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_invoices_tenant_id_appointment_id UNIQUE (tenant_id, appointment_id), 
    CONSTRAINT uq_invoices_tenant_id_id_appointment_id UNIQUE (tenant_id, id, appointment_id), 
    CONSTRAINT uq_invoices_tenant_id_number UNIQUE (tenant_id, number)
);

CREATE INDEX ix_invoices_tenant_id_appointment_id_total_amount_curre_f60d ON invoices (tenant_id, appointment_id, total_amount, currency, is_test);

CREATE TABLE payment_intents (
    appointment_id UUID NOT NULL, 
    amount BIGINT NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    is_test BOOLEAN NOT NULL, 
    status VARCHAR(23) DEFAULT 'CREATED' NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_payment_intents PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_payment_intents_amount_currency CHECK (amount > 0 AND currency = 'IRR'), 
    CONSTRAINT ck_payment_intents_expiry CHECK (expires_at > created_at), 
    CONSTRAINT fk_payment_intents_tenant_id_appointment_id_amount_curr_718f FOREIGN KEY(tenant_id, appointment_id, amount, currency, is_test) REFERENCES appointments (tenant_id, id, total_amount, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_payment_intents_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_payment_intents_tenant_id_appointment_id UNIQUE (tenant_id, appointment_id), 
    CONSTRAINT uq_payment_intents_tenant_id_id_amount_currency_is_test UNIQUE (tenant_id, id, amount, currency, is_test), 
    CONSTRAINT ck_payment_intents_payment_status CHECK (status IN ('CREATED', 'PENDING', 'VERIFYING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED', 'RECONCILIATION_REQUIRED'))
);

CREATE INDEX ix_payment_intents_tenant_id_appointment_id_amount_curr_f2fd ON payment_intents (tenant_id, appointment_id, amount, currency, is_test);

CREATE TABLE schedule_blocks (
    calendar_id UUID NOT NULL, 
    kind VARCHAR(7) NOT NULL, 
    status VARCHAR(9) DEFAULT 'REQUESTED' NOT NULL, 
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    requested_by_id UUID, 
    approved_by_id UUID, 
    reason TEXT, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_schedule_blocks PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_schedule_blocks_interval CHECK (ends_at > starts_at), 
    CONSTRAINT fk_schedule_blocks_tenant_id_approved_by_id_users FOREIGN KEY(tenant_id, approved_by_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_schedule_blocks_tenant_id_calendar_id_calendars FOREIGN KEY(tenant_id, calendar_id) REFERENCES calendars (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_schedule_blocks_tenant_id_requested_by_id_users FOREIGN KEY(tenant_id, requested_by_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_schedule_blocks_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT ck_schedule_blocks_block_kind CHECK (kind IN ('LEAVE', 'HOLIDAY', 'BLOCKED')), 
    CONSTRAINT ck_schedule_blocks_block_status CHECK (status IN ('REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED'))
);

CREATE INDEX ix_schedule_blocks_calendar_start ON schedule_blocks (tenant_id, calendar_id, starts_at);

CREATE INDEX ix_schedule_blocks_tenant_id_approved_by_id ON schedule_blocks (tenant_id, approved_by_id);

CREATE INDEX ix_schedule_blocks_tenant_id_requested_by_id ON schedule_blocks (tenant_id, requested_by_id);

CREATE TABLE weekly_periods (
    calendar_id UUID NOT NULL, 
    kind VARCHAR(8) DEFAULT 'OPEN' NOT NULL, 
    weekday INTEGER NOT NULL, 
    start_minute INTEGER NOT NULL, 
    end_minute INTEGER NOT NULL, 
    valid_from DATE NOT NULL, 
    valid_until DATE, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_weekly_periods PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_weekly_periods_kind CHECK (kind IN ('OPEN', 'BREAK')), 
    CONSTRAINT ck_weekly_periods_minutes CHECK (start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440), 
    CONSTRAINT ck_weekly_periods_effective_dates CHECK (valid_until IS NULL OR valid_until > valid_from), 
    CONSTRAINT ck_weekly_periods_weekday CHECK (weekday BETWEEN 0 AND 6), 
    CONSTRAINT fk_weekly_periods_tenant_id_calendar_id_calendars FOREIGN KEY(tenant_id, calendar_id) REFERENCES calendars (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_weekly_periods_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_weekly_periods_tenant_id_calendar_id_kind_weekday_st_9d1f UNIQUE (tenant_id, calendar_id, kind, weekday, start_minute, end_minute, valid_from)
);

CREATE TABLE invoice_items (
    invoice_id UUID NOT NULL, 
    appointment_id UUID NOT NULL, 
    appointment_item_id UUID NOT NULL, 
    position INTEGER NOT NULL, 
    description VARCHAR(200) NOT NULL, 
    amount BIGINT NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_invoice_items PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_invoice_items_values CHECK (amount >= 0 AND position > 0), 
    CONSTRAINT fk_invoice_items_tenant_id_appointment_item_id_appointm_23c0 FOREIGN KEY(tenant_id, appointment_item_id, appointment_id) REFERENCES appointment_items (tenant_id, id, appointment_id) ON DELETE RESTRICT, 
    CONSTRAINT fk_invoice_items_tenant_id_invoice_id_appointment_id_invoices FOREIGN KEY(tenant_id, invoice_id, appointment_id) REFERENCES invoices (tenant_id, id, appointment_id) ON DELETE RESTRICT, 
    CONSTRAINT fk_invoice_items_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_invoice_items_tenant_id_invoice_id_appointment_item_id UNIQUE (tenant_id, invoice_id, appointment_item_id), 
    CONSTRAINT uq_invoice_items_tenant_id_invoice_id_position UNIQUE (tenant_id, invoice_id, position)
);

CREATE INDEX ix_invoice_items_tenant_id_appointment_item_id_appointment_id ON invoice_items (tenant_id, appointment_item_id, appointment_id);

CREATE INDEX ix_invoice_items_tenant_id_invoice_id_appointment_id ON invoice_items (tenant_id, invoice_id, appointment_id);

CREATE TABLE payment_attempts (
    intent_id UUID NOT NULL, 
    account_id UUID NOT NULL, 
    amount BIGINT NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    is_test BOOLEAN NOT NULL, 
    status VARCHAR(23) DEFAULT 'CREATED' NOT NULL, 
    request_key VARCHAR(128) NOT NULL, 
    gateway_order_id VARCHAR(180), 
    next_check_at TIMESTAMP WITH TIME ZONE, 
    verified_at TIMESTAMP WITH TIME ZONE, 
    failure_code VARCHAR(80), 
    safe_response JSONB DEFAULT '{}'::jsonb NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_payment_attempts PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_payment_attempts_amount_currency CHECK (amount > 0 AND currency = 'IRR'), 
    CONSTRAINT fk_payment_attempts_tenant_id_account_id_is_test_paymen_4348 FOREIGN KEY(tenant_id, account_id, is_test) REFERENCES payment_accounts (tenant_id, id, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_payment_attempts_tenant_id_intent_id_amount_currency_fe79 FOREIGN KEY(tenant_id, intent_id, amount, currency, is_test) REFERENCES payment_intents (tenant_id, id, amount, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_payment_attempts_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_payment_attempts_account_id_gateway_order_id UNIQUE (account_id, gateway_order_id), 
    CONSTRAINT uq_payment_attempts_tenant_id_id_intent_id_account_id_c_a4da UNIQUE (tenant_id, id, intent_id, account_id, currency, is_test), 
    CONSTRAINT uq_payment_attempts_tenant_id_intent_id_request_key UNIQUE (tenant_id, intent_id, request_key), 
    CONSTRAINT ck_payment_attempts_attempt_status CHECK (status IN ('CREATED', 'PENDING', 'VERIFYING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED', 'RECONCILIATION_REQUIRED'))
);

CREATE INDEX ix_payment_attempts_reconcile ON payment_attempts (tenant_id, next_check_at) WHERE status IN ('PENDING', 'VERIFYING', 'RECONCILIATION_REQUIRED');

CREATE INDEX ix_payment_attempts_tenant_id_account_id_is_test ON payment_attempts (tenant_id, account_id, is_test);

CREATE INDEX ix_payment_attempts_tenant_id_intent_id_amount_currency_is_test ON payment_attempts (tenant_id, intent_id, amount, currency, is_test);

CREATE UNIQUE INDEX uq_payment_attempts_open_intent ON payment_attempts (tenant_id, intent_id) WHERE status IN ('CREATED', 'PENDING', 'VERIFYING', 'RECONCILIATION_REQUIRED');

CREATE TABLE special_periods (
    override_id UUID NOT NULL, 
    override_mode VARCHAR(7) DEFAULT 'REPLACE' NOT NULL, 
    start_minute INTEGER NOT NULL, 
    end_minute INTEGER NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_special_periods PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_special_periods_replace_only CHECK (override_mode = 'REPLACE'), 
    CONSTRAINT ck_special_periods_minutes CHECK (start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440), 
    CONSTRAINT fk_special_periods_tenant_id_override_id_override_mode__518d FOREIGN KEY(tenant_id, override_id, override_mode) REFERENCES day_overrides (tenant_id, id, mode) ON DELETE RESTRICT, 
    CONSTRAINT fk_special_periods_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_special_periods_tenant_id_override_id_start_minute_e_9833 UNIQUE (tenant_id, override_id, start_minute, end_minute)
);

CREATE INDEX ix_special_periods_tenant_id_override_id_override_mode ON special_periods (tenant_id, override_id, override_mode);

CREATE TABLE callback_events (
    attempt_id UUID NOT NULL, 
    provider_event_id VARCHAR(180), 
    outcome VARCHAR(32) NOT NULL, 
    safe_payload JSONB NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_callback_events PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_callback_events_tenant_id_attempt_id_payment_attempts FOREIGN KEY(tenant_id, attempt_id) REFERENCES payment_attempts (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_callback_events_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT
);

CREATE INDEX ix_callback_events_tenant_id_attempt_id ON callback_events (tenant_id, attempt_id);

CREATE TABLE payment_transactions (
    attempt_id UUID NOT NULL, 
    intent_id UUID NOT NULL, 
    account_id UUID NOT NULL, 
    amount BIGINT NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    is_test BOOLEAN NOT NULL, 
    gateway_transaction_id VARCHAR(180) NOT NULL, 
    received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    verified_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    evidence JSONB NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_payment_transactions PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_payment_transactions_amount_currency CHECK (amount > 0 AND currency = 'IRR'), 
    CONSTRAINT fk_payment_transactions_tenant_id_attempt_id_intent_id__dee6 FOREIGN KEY(tenant_id, attempt_id, intent_id, account_id, currency, is_test) REFERENCES payment_attempts (tenant_id, id, intent_id, account_id, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_payment_transactions_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_payment_transactions_account_id_gateway_transaction_id UNIQUE (account_id, gateway_transaction_id), 
    CONSTRAINT uq_payment_transactions_tenant_id_id_amount_currency_is_test UNIQUE (tenant_id, id, amount, currency, is_test), 
    CONSTRAINT uq_payment_transactions_tenant_id_id_intent_id_amount_c_e736 UNIQUE (tenant_id, id, intent_id, amount, currency, is_test)
);

CREATE INDEX ix_payment_transactions_received ON payment_transactions (tenant_id, received_at);

CREATE INDEX ix_payment_transactions_tenant_id_attempt_id_intent_id__a142 ON payment_transactions (tenant_id, attempt_id, intent_id, account_id, currency, is_test);

CREATE TABLE payment_allocations (
    intent_id UUID NOT NULL, 
    transaction_id UUID NOT NULL, 
    amount BIGINT NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    is_test BOOLEAN NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_payment_allocations PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_payment_allocations_tenant_id_intent_id_amount_curre_28b4 FOREIGN KEY(tenant_id, intent_id, amount, currency, is_test) REFERENCES payment_intents (tenant_id, id, amount, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_payment_allocations_tenant_id_transaction_id_intent__d6ae FOREIGN KEY(tenant_id, transaction_id, intent_id, amount, currency, is_test) REFERENCES payment_transactions (tenant_id, id, intent_id, amount, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_payment_allocations_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_payment_allocations_tenant_id_intent_id UNIQUE (tenant_id, intent_id), 
    CONSTRAINT uq_payment_allocations_tenant_id_transaction_id UNIQUE (tenant_id, transaction_id)
);

CREATE INDEX ix_payment_allocations_tenant_id_intent_id_amount_curre_fe7d ON payment_allocations (tenant_id, intent_id, amount, currency, is_test);

CREATE INDEX ix_payment_allocations_tenant_id_transaction_id_intent__b863 ON payment_allocations (tenant_id, transaction_id, intent_id, amount, currency, is_test);

CREATE TABLE receipts (
    transaction_id UUID NOT NULL, 
    number VARCHAR(64) NOT NULL, 
    amount BIGINT NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    is_test BOOLEAN NOT NULL, 
    issued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_receipts PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_receipts_tenant_id_transaction_id_amount_currency_is_85ac FOREIGN KEY(tenant_id, transaction_id, amount, currency, is_test) REFERENCES payment_transactions (tenant_id, id, amount, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_receipts_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_receipts_tenant_id_number UNIQUE (tenant_id, number), 
    CONSTRAINT uq_receipts_tenant_id_transaction_id UNIQUE (tenant_id, transaction_id)
);

CREATE INDEX ix_receipts_tenant_id_transaction_id_amount_currency_is_test ON receipts (tenant_id, transaction_id, amount, currency, is_test);

CREATE TABLE refunds (
    transaction_id UUID NOT NULL, 
    captured_amount BIGINT NOT NULL, 
    amount BIGINT NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    is_test BOOLEAN NOT NULL, 
    status VARCHAR(23) DEFAULT 'REQUESTED' NOT NULL, 
    request_key VARCHAR(128) NOT NULL, 
    gateway_refund_id VARCHAR(180), 
    requested_by_id UUID, 
    approved_by_id UUID, 
    reason TEXT NOT NULL, 
    succeeded_at TIMESTAMP WITH TIME ZONE, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_refunds PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_refunds_amount_currency CHECK (amount > 0 AND amount <= captured_amount AND currency = 'IRR'), 
    CONSTRAINT ck_refunds_success_time CHECK (status <> 'SUCCEEDED' OR succeeded_at IS NOT NULL), 
    CONSTRAINT fk_refunds_tenant_id_approved_by_id_users FOREIGN KEY(tenant_id, approved_by_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_refunds_tenant_id_requested_by_id_users FOREIGN KEY(tenant_id, requested_by_id) REFERENCES users (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_refunds_tenant_id_transaction_id_captured_amount_cur_7088 FOREIGN KEY(tenant_id, transaction_id, captured_amount, currency, is_test) REFERENCES payment_transactions (tenant_id, id, amount, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_refunds_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_refunds_tenant_id_id_transaction_id_amount_currency_is_test UNIQUE (tenant_id, id, transaction_id, amount, currency, is_test), 
    CONSTRAINT uq_refunds_tenant_id_request_key UNIQUE (tenant_id, request_key), 
    CONSTRAINT uq_refunds_tenant_id_transaction_id_gateway_refund_id UNIQUE (tenant_id, transaction_id, gateway_refund_id), 
    CONSTRAINT ck_refunds_refund_status CHECK (status IN ('REQUESTED', 'APPROVED', 'PROCESSING', 'RECONCILIATION_REQUIRED', 'SUCCEEDED', 'FAILED', 'CANCELLED'))
);

CREATE INDEX ix_refunds_tenant_id_approved_by_id ON refunds (tenant_id, approved_by_id);

CREATE INDEX ix_refunds_tenant_id_requested_by_id ON refunds (tenant_id, requested_by_id);

CREATE INDEX ix_refunds_tenant_id_transaction_id_captured_amount_cur_79ef ON refunds (tenant_id, transaction_id, captured_amount, currency, is_test);

CREATE TABLE credit_notes (
    refund_id UUID NOT NULL, 
    number VARCHAR(64) NOT NULL, 
    issued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_credit_notes PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_credit_notes_tenant_id_refund_id_refunds FOREIGN KEY(tenant_id, refund_id) REFERENCES refunds (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT fk_credit_notes_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_credit_notes_tenant_id_number UNIQUE (tenant_id, number), 
    CONSTRAINT uq_credit_notes_tenant_id_refund_id UNIQUE (tenant_id, refund_id)
);

CREATE TABLE financial_entries (
    kind VARCHAR(8) NOT NULL, 
    transaction_id UUID NOT NULL, 
    captured_amount BIGINT NOT NULL, 
    refund_id UUID, 
    amount BIGINT NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    is_test BOOLEAN NOT NULL, 
    booked_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_financial_entries PRIMARY KEY (tenant_id, id), 
    CONSTRAINT ck_financial_entries_kind_source CHECK ((kind = 'CAPTURE' AND refund_id IS NULL) OR (kind = 'REFUND' AND refund_id IS NOT NULL)), 
    CONSTRAINT ck_financial_entries_amount_currency CHECK (amount > 0 AND amount <= captured_amount AND currency = 'IRR' AND (kind <> 'CAPTURE' OR amount = captured_amount)), 
    CONSTRAINT fk_financial_entries_tenant_id_refund_id_transaction_id_ac91 FOREIGN KEY(tenant_id, refund_id, transaction_id, amount, currency, is_test) REFERENCES refunds (tenant_id, id, transaction_id, amount, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_financial_entries_tenant_id_transaction_id_captured__6fb7 FOREIGN KEY(tenant_id, transaction_id, captured_amount, currency, is_test) REFERENCES payment_transactions (tenant_id, id, amount, currency, is_test) ON DELETE RESTRICT, 
    CONSTRAINT fk_financial_entries_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT
);

CREATE INDEX ix_financial_entries_booked ON financial_entries (tenant_id, is_test, booked_at);

CREATE INDEX ix_financial_entries_tenant_id_refund_id_transaction_id_67e5 ON financial_entries (tenant_id, refund_id, transaction_id, amount, currency, is_test);

CREATE INDEX ix_financial_entries_tenant_id_transaction_id_captured__6e5d ON financial_entries (tenant_id, transaction_id, captured_amount, currency, is_test);

CREATE UNIQUE INDEX uq_financial_entries_capture ON financial_entries (tenant_id, transaction_id) WHERE kind = 'CAPTURE';

CREATE UNIQUE INDEX uq_financial_entries_refund ON financial_entries (tenant_id, refund_id) WHERE kind = 'REFUND';

INSERT INTO alembic_version (version_num) VALUES ('0001') RETURNING alembic_version.version_num;

-- Running upgrade 0001 -> 0002

CREATE SCHEMA app_private;

REVOKE ALL ON SCHEMA app_private FROM PUBLIC;

CREATE FUNCTION app_private.touch_updated_at() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END $$;

CREATE FUNCTION app_private.guard_tenant_identity() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.id IS DISTINCT FROM OLD.id THEN
                RAISE EXCEPTION 'Tenant and record identity are immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;

CREATE FUNCTION app_private.reject_evidence_mutation() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Evidence is append-only; use a compensating record' USING ERRCODE = '55000';
        END $$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app_private FROM PUBLIC;

ALTER TABLE "appointment_history" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "appointment_history" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "appointment_history" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "appointment_history" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "appointment_items" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "appointment_items" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "appointment_items" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "appointment_items" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "appointments" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "appointments" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "appointments" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "appointments" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "audit_logs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "audit_logs" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "audit_logs" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "audit_logs" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "auth_throttles" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "auth_throttles" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "auth_throttles" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "auth_throttles" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "auth_tokens" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "auth_tokens" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "auth_tokens" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "auth_tokens" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "background_jobs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "background_jobs" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "background_jobs" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "background_jobs" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "calendar_controls" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "calendar_controls" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "calendar_controls" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "calendar_controls" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "calendars" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "calendars" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "calendars" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "calendars" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "callback_events" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "callback_events" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "callback_events" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "callback_events" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "credit_notes" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "credit_notes" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "credit_notes" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "credit_notes" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "customer_profiles" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "customer_profiles" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "customer_profiles" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "customer_profiles" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "day_overrides" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "day_overrides" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "day_overrides" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "day_overrides" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "employee_lines" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "employee_lines" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "employee_lines" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "employee_lines" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "employee_profiles" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "employee_profiles" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "employee_profiles" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "employee_profiles" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "employee_services" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "employee_services" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "employee_services" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "employee_services" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "financial_entries" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "financial_entries" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "financial_entries" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "financial_entries" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "idempotency_records" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "idempotency_records" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "idempotency_records" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "idempotency_records" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "invoice_items" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "invoice_items" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "invoice_items" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "invoice_items" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "invoices" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "invoices" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "invoices" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "invoices" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "line_services" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "line_services" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "line_services" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "line_services" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "lines" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "lines" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "lines" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "lines" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "notifications" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "notifications" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "notifications" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "notifications" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "outbox_events" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "outbox_events" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "outbox_events" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "outbox_events" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "payment_accounts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payment_accounts" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "payment_accounts" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "payment_accounts" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "payment_allocations" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payment_allocations" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "payment_allocations" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "payment_allocations" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "payment_attempts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payment_attempts" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "payment_attempts" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "payment_attempts" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "payment_intents" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payment_intents" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "payment_intents" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "payment_intents" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "payment_transactions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "payment_transactions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "payment_transactions" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "payment_transactions" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "receipts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "receipts" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "receipts" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "receipts" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "refunds" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "refunds" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "refunds" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "refunds" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "role_assignments" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "role_assignments" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "role_assignments" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "role_assignments" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "role_permissions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "role_permissions" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "role_permissions" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "roles" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "roles" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "roles" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "roles" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "salon_settings" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "salon_settings" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "salon_settings" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "salon_settings" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "schedule_blocks" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "schedule_blocks" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "schedule_blocks" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "schedule_blocks" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "services" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "services" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "services" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "services" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "sessions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "sessions" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "sessions" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "sessions" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "special_periods" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "special_periods" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "special_periods" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "special_periods" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "support_grants" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "support_grants" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "support_grants" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "support_grants" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "users" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "users" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "users" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "users" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE "weekly_periods" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "weekly_periods" FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON "weekly_periods" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON "weekly_periods" FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

ALTER TABLE salons ENABLE ROW LEVEL SECURITY;

ALTER TABLE salons FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON salons USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "appointments" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "auth_throttles" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "background_jobs" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "calendar_controls" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "calendars" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "customer_profiles" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "day_overrides" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "employee_lines" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "employee_profiles" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "employee_services" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "idempotency_records" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "line_services" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "lines" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "notifications" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "payment_accounts" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "payment_attempts" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "payment_intents" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "platform_roles" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "platform_sessions" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "platform_users" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "refunds" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "role_assignments" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "roles" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "salon_settings" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "salons" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "schedule_blocks" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "services" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "sessions" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "special_periods" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "tenant_domains" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "users" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON "weekly_periods" FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "appointment_history" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "appointment_items" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "audit_logs" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "callback_events" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "credit_notes" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "financial_entries" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "invoice_items" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "invoices" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "outbox_events" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "payment_allocations" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "payment_transactions" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "platform_audit_logs" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON "receipts" FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

CREATE VIEW tenant_hostnames WITH (security_barrier = true) AS SELECT hostname, tenant_id FROM tenant_domains WHERE is_active AND verified_at IS NOT NULL;

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001';

-- Running upgrade 0002 -> 0003

CREATE VIEW app_schema_revision AS SELECT version_num FROM alembic_version;

REVOKE ALL ON app_schema_revision FROM PUBLIC;

DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'salonbook_runtime') THEN
                GRANT SELECT ON app_schema_revision TO salonbook_runtime;
            END IF;
        END $$;

UPDATE alembic_version SET version_num='0003' WHERE alembic_version.version_num = '0002';

-- Running upgrade 0003 -> 0004

ALTER TABLE sessions ADD COLUMN grants_fingerprint VARCHAR(64) DEFAULT '' NOT NULL;

INSERT INTO permissions (code, description) VALUES ('profile.read', 'profile.read');

INSERT INTO permissions (code, description) VALUES ('session.manage', 'session.manage');

INSERT INTO permissions (code, description) VALUES ('appointment.create', 'appointment.create');

INSERT INTO permissions (code, description) VALUES ('appointment.read_own', 'appointment.read_own');

INSERT INTO permissions (code, description) VALUES ('appointment.cancel_own', 'appointment.cancel_own');

INSERT INTO permissions (code, description) VALUES ('appointment.read', 'appointment.read');

INSERT INTO permissions (code, description) VALUES ('appointment.manage', 'appointment.manage');

INSERT INTO permissions (code, description) VALUES ('catalog.manage', 'catalog.manage');

INSERT INTO permissions (code, description) VALUES ('staff.manage', 'staff.manage');

INSERT INTO permissions (code, description) VALUES ('finance.read', 'finance.read');

INSERT INTO permissions (code, description) VALUES ('payment.refund', 'payment.refund');

INSERT INTO permissions (code, description) VALUES ('roles.manage', 'roles.manage');

INSERT INTO permissions (code, description) VALUES ('audit.read', 'audit.read');

UPDATE alembic_version SET version_num='0004' WHERE alembic_version.version_num = '0003';

-- Running upgrade 0004 -> 0005

ALTER TABLE customer_profiles ALTER COLUMN contact_preference SET DEFAULT 'NONE';

ALTER TABLE users ALTER COLUMN email_normalized DROP NOT NULL;

ALTER TABLE users ADD COLUMN phone_normalized VARCHAR(16);

ALTER TABLE users ADD COLUMN phone_verified_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE users ADD CONSTRAINT uq_users_tenant_id_phone_normalized UNIQUE (tenant_id, phone_normalized);

ALTER TABLE users ADD CONSTRAINT ck_users_phone_normalized CHECK (phone_normalized IS NULL OR phone_normalized ~ '^\+989[0-9]{9}$');

ALTER TABLE users ADD CONSTRAINT ck_users_phone_verification CHECK (phone_verified_at IS NULL OR phone_normalized IS NOT NULL);

UPDATE alembic_version SET version_num='0005' WHERE alembic_version.version_num = '0004';

-- Running upgrade 0005 -> 0006

INSERT INTO permissions (code, description) VALUES ('profile.update', 'profile.update');

INSERT INTO permissions (code, description) VALUES ('salon.read', 'salon.read');

INSERT INTO permissions (code, description) VALUES ('salon.manage', 'salon.manage');

INSERT INTO permissions (code, description) VALUES ('users.read', 'users.read');

INSERT INTO permissions (code, description) VALUES ('users.manage', 'users.manage');

INSERT INTO permissions (code, description) VALUES ('roles.read', 'roles.read');

ALTER TABLE roles NO FORCE ROW LEVEL SECURITY;

ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'profile.update' FROM roles
                WHERE is_system AND code = 'customer' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'salon.read' FROM roles
                WHERE is_system AND code = 'customer' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'profile.update' FROM roles
                WHERE is_system AND code = 'employee' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'salon.read' FROM roles
                WHERE is_system AND code = 'employee' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'profile.update' FROM roles
                WHERE is_system AND code = 'line_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'salon.read' FROM roles
                WHERE is_system AND code = 'line_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'profile.update' FROM roles
                WHERE is_system AND code = 'salon_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'salon.read' FROM roles
                WHERE is_system AND code = 'salon_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'salon.manage' FROM roles
                WHERE is_system AND code = 'salon_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'users.read' FROM roles
                WHERE is_system AND code = 'salon_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'users.manage' FROM roles
                WHERE is_system AND code = 'salon_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'roles.read' FROM roles
                WHERE is_system AND code = 'salon_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'appointment.create' FROM roles
                WHERE is_system AND code = 'salon_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'appointment.read_own' FROM roles
                WHERE is_system AND code = 'salon_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
                SELECT tenant_id, id, 'appointment.cancel_own' FROM roles
                WHERE is_system AND code = 'salon_manager' AND deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

ALTER TABLE roles FORCE ROW LEVEL SECURITY;

ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY;

UPDATE alembic_version SET version_num='0006' WHERE alembic_version.version_num = '0005';

-- Running upgrade 0006 -> 0007

ALTER TABLE line_services DROP CONSTRAINT ck_line_services_price;

ALTER TABLE line_services ADD CONSTRAINT ck_line_services_price CHECK (price_amount >= 0 AND is_free = (price_amount = 0));

INSERT INTO permissions (code, description) VALUES ('staff.assign', 'Manage employee assignments in authorized lines');

ALTER TABLE roles NO FORCE ROW LEVEL SECURITY;

ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
        SELECT tenant_id, id, 'staff.assign' FROM roles
        WHERE is_system AND code IN ('salon_manager', 'line_manager') AND deleted_at IS NULL
        ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

ALTER TABLE roles FORCE ROW LEVEL SECURITY;

ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY;

UPDATE alembic_version SET version_num='0007' WHERE alembic_version.version_num = '0006';

-- Running upgrade 0007 -> 0008

INSERT INTO permissions (code, description) VALUES (NULL, NULL);

INSERT INTO permissions (code, description) VALUES (NULL, NULL);

INSERT INTO permissions (code, description) VALUES (NULL, NULL);

INSERT INTO permissions (code, description) VALUES (NULL, NULL);

ALTER TABLE roles NO FORCE ROW LEVEL SECURITY;

ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, NULL FROM roles
            WHERE is_system AND code IN (NULL) AND deleted_at IS NULL
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, NULL FROM roles
            WHERE is_system AND code IN (NULL) AND deleted_at IS NULL
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, NULL FROM roles
            WHERE is_system AND code IN (NULL) AND deleted_at IS NULL
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, NULL FROM roles
            WHERE is_system AND code IN (NULL) AND deleted_at IS NULL
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

ALTER TABLE roles FORCE ROW LEVEL SECURITY;

ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY;

UPDATE alembic_version SET version_num='0008' WHERE alembic_version.version_num = '0007';

-- Running upgrade 0008 -> 0009

ALTER TABLE salon_settings ADD COLUMN no_show_grace_minutes INTEGER DEFAULT '15' NOT NULL;

ALTER TABLE salon_settings ADD CONSTRAINT ck_salon_settings_no_show_grace CHECK (no_show_grace_minutes BETWEEN 0 AND 240);

ALTER TABLE roles NO FORCE ROW LEVEL SECURITY;

ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY;

INSERT INTO permissions (code, description) VALUES (NULL, NULL);

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, NULL FROM roles
            WHERE is_system AND deleted_at IS NULL AND code IN (NULL)
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO permissions (code, description) VALUES (NULL, NULL);

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, NULL FROM roles
            WHERE is_system AND deleted_at IS NULL AND code IN (NULL)
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO permissions (code, description) VALUES (NULL, NULL);

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, NULL FROM roles
            WHERE is_system AND deleted_at IS NULL AND code IN (NULL)
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

INSERT INTO permissions (code, description) VALUES (NULL, NULL);

INSERT INTO role_permissions (tenant_id, role_id, permission_code)
            SELECT tenant_id, id, NULL FROM roles
            WHERE is_system AND deleted_at IS NULL AND code IN (NULL)
            ON CONFLICT (tenant_id, role_id, permission_code) DO NOTHING;

ALTER TABLE roles FORCE ROW LEVEL SECURITY;

ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY;

UPDATE alembic_version SET version_num='0009' WHERE alembic_version.version_num = '0008';

-- Running upgrade 0009 -> 0010

CREATE TABLE mock_orders (
    account_id UUID NOT NULL, 
    request_key VARCHAR(128) NOT NULL, 
    merchant VARCHAR(160) NOT NULL, 
    amount BIGINT NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    status VARCHAR(16) DEFAULT 'PENDING' NOT NULL, 
    scenario VARCHAR(32), 
    unknown_reads INTEGER DEFAULT '0' NOT NULL, 
    received_at TIMESTAMP WITH TIME ZONE, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_mock_orders PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_mock_orders_tenant_id_account_id_payment_accounts FOREIGN KEY(tenant_id, account_id) REFERENCES payment_accounts (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_mock_orders_tenant_id_account_id_request_key UNIQUE (tenant_id, account_id, request_key), 
    CONSTRAINT ck_mock_orders_amount_currency CHECK (amount > 0 AND currency = 'IRR'), 
    CONSTRAINT ck_mock_orders_unknown_reads CHECK (unknown_reads >= 0), 
    CONSTRAINT ck_mock_orders_status CHECK (status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'CANCELLED')), 
    CONSTRAINT fk_mock_orders_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT
);

ALTER TABLE mock_orders ENABLE ROW LEVEL SECURITY;

ALTER TABLE mock_orders FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON mock_orders USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON mock_orders FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

CREATE TABLE mock_refunds (
    order_id UUID NOT NULL, 
    request_key VARCHAR(128) NOT NULL, 
    amount BIGINT NOT NULL, 
    tenant_id UUID NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_mock_refunds PRIMARY KEY (tenant_id, id), 
    CONSTRAINT fk_mock_refunds_tenant_id_order_id_mock_orders FOREIGN KEY(tenant_id, order_id) REFERENCES mock_orders (tenant_id, id) ON DELETE RESTRICT, 
    CONSTRAINT uq_mock_refunds_tenant_id_order_id_request_key UNIQUE (tenant_id, order_id, request_key), 
    CONSTRAINT ck_mock_refunds_amount CHECK (amount > 0), 
    CONSTRAINT fk_mock_refunds_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT
);

ALTER TABLE mock_refunds ENABLE ROW LEVEL SECURITY;

ALTER TABLE mock_refunds FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON mock_refunds USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

CREATE TRIGGER guard_identity BEFORE UPDATE ON mock_refunds FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity();

CREATE TRIGGER touch_timestamp BEFORE UPDATE ON mock_orders FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON mock_refunds FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation();

ALTER TABLE refunds ADD COLUMN next_check_at timestamptz;

CREATE INDEX ix_refunds_reconcile ON refunds (tenant_id, next_check_at) WHERE status IN ('APPROVED', 'PROCESSING', 'RECONCILIATION_REQUIRED');

DROP INDEX ix_payment_attempts_reconcile;

CREATE INDEX ix_payment_attempts_reconcile ON payment_attempts (tenant_id, next_check_at) WHERE status <> 'SUCCEEDED';

UPDATE alembic_version SET version_num='0010' WHERE alembic_version.version_num = '0009';

-- Running upgrade 0010 -> 0011

CREATE TABLE platform_auth_throttles (key bytea PRIMARY KEY, attempts integer NOT NULL, expires_at timestamptz NOT NULL, CONSTRAINT ck_platform_auth_throttles_values CHECK (attempts > 0 AND octet_length(key) = 32));

CREATE INDEX ix_platform_auth_throttles_expires_at ON platform_auth_throttles (expires_at);

ALTER TABLE platform_users ALTER COLUMN email_normalized DROP NOT NULL;

ALTER TABLE platform_users ADD COLUMN phone_normalized varchar(16);

ALTER TABLE platform_users ADD COLUMN display_name varchar(160) NOT NULL DEFAULT 'Platform administrator';

ALTER TABLE platform_users ADD CONSTRAINT uq_platform_users_phone_normalized UNIQUE (phone_normalized);

ALTER TABLE platform_users ADD CONSTRAINT ck_platform_users_phone_normalized CHECK (phone_normalized IS NULL OR phone_normalized ~ '^\+989[0-9]{9}$');

INSERT INTO permissions (code, description) VALUES ('platform.manage', 'Operate the separate platform console') ON CONFLICT DO NOTHING;

UPDATE alembic_version SET version_num='0011' WHERE alembic_version.version_num = '0010';

COMMIT;

