# فرهنگ دادهٔ مرحلهٔ ۲

این فایل از مدل‌های SQLAlchemy تولید شده است. توضیح تصمیم‌ها و مرز ضمانت‌ها در سند مرحلهٔ ۲ است. نام‌های طولانی قیود در PostgreSQL به‌صورت قطعی با پسوند Hash کوتاه می‌شوند.

تعداد جدول‌ها: **54**. FKهای تجاری متعلق به سالن، tenant_id را نیز حمل می‌کنند. همهٔ FKها RESTRICT هستند؛ حذف زنجیره‌ای مالی نداریم.

## appointment_history

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| appointment_id | UUID | خیر | FK | — |
| actor_id | UUID | بله | FK | — |
| action | VARCHAR(80) | خیر | — | — |
| reason | TEXT | بله | — | — |
| event_data | JSONB | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, actor_id) → users(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id, appointment_id) → appointments(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_appointment_history_tenant_id_actor_id ON appointment_history (tenant_id, actor_id)`
- `CREATE INDEX ix_appointment_history_tenant_id_appointment_id ON appointment_history (tenant_id, appointment_id)`

## appointment_items

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| appointment_id | UUID | خیر | FK | — |
| original_employee_id | UUID | خیر | FK | — |
| line_id | UUID | خیر | FK | — |
| service_id | UUID | خیر | FK | — |
| position | INTEGER | خیر | — | — |
| service_name | VARCHAR(160) | خیر | — | — |
| line_name | VARCHAR(120) | خیر | — | — |
| employee_name | VARCHAR(160) | خیر | — | — |
| duration_minutes | INTEGER | خیر | — | — |
| buffer_before_minutes | INTEGER | خیر | — | 0 |
| buffer_after_minutes | INTEGER | خیر | — | 0 |
| amount | BIGINT | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, appointment_id, line_id) → appointments(tenant_id, id, line_id), ON DELETE RESTRICT.
- (tenant_id, original_employee_id, line_id, service_id) → employee_services(tenant_id, employee_id, line_id, service_id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_appointment_items_values: `position > 0 AND duration_minutes > 0 AND amount >= 0 AND buffer_before_minutes >= 0 AND buffer_after_minutes >= 0`
- UNIQUE: (tenant_id, appointment_id, position)
- UNIQUE: (tenant_id, id, appointment_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_appointment_items_tenant_id_appointment_id_line_id ON appointment_items (tenant_id, appointment_id, line_id)`
- `CREATE INDEX ix_appointment_items_tenant_id_original_employee_id_lin_41fa ON appointment_items (tenant_id, original_employee_id, line_id, service_id)`

## appointments

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| customer_id | UUID | خیر | FK | — |
| employee_id | UUID | خیر | FK | — |
| line_id | UUID | خیر | FK | — |
| status | VARCHAR(16) | خیر | — | AWAITING_PAYMENT |
| starts_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| ends_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| occupied_starts_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| occupied_ends_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| occupied_period | TSTZRANGE | خیر | — | GENERATED: tstzrange(occupied_starts_at, occupied_ends_at, '[)'::text) |
| duration_minutes | INTEGER | خیر | — | — |
| buffer_before_minutes | INTEGER | خیر | — | 0 |
| buffer_after_minutes | INTEGER | خیر | — | 0 |
| total_amount | BIGINT | خیر | — | — |
| currency | VARCHAR(3) | خیر | — | IRR |
| is_test | BOOLEAN | خیر | — | true |
| hold_expires_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| confirmed_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| cancelled_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| cancellation_reason | TEXT | بله | — | — |
| policy_snapshot | JSONB | خیر | — | — |
| version | INTEGER | خیر | — | 1 |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, customer_id) → customer_profiles(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id, employee_id, line_id) → employee_lines(tenant_id, employee_id, line_id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_appointments_amount_currency_version: `total_amount >= 0 AND currency = 'IRR' AND version > 0`
- CHECK ck_appointments_appointment_status: `appointments.status IN ('AWAITING_PAYMENT', 'CONFIRMED', 'CANCELLED', 'COMPLETED', 'NO_SHOW', 'EXPIRED')`
- CHECK ck_appointments_buffers: `buffer_before_minutes >= 0 AND buffer_after_minutes >= 0 AND occupied_starts_at = starts_at - buffer_before_minutes * interval '1 minute' AND occupied_ends_at = ends_at + buffer_after_minutes * interval '1 minute'`
- CHECK ck_appointments_confirmation: `status NOT IN ('CONFIRMED', 'COMPLETED', 'NO_SHOW') OR confirmed_at IS NOT NULL`
- CHECK ck_appointments_duration: `duration_minutes > 0 AND ends_at = starts_at + duration_minutes * interval '1 minute'`
- CHECK ck_appointments_hold: `status <> 'AWAITING_PAYMENT' OR (hold_expires_at IS NOT NULL AND hold_expires_at > created_at AND hold_expires_at <= starts_at AND confirmed_at IS NULL)`
- CHECK ck_appointments_interval: `ends_at > starts_at AND occupied_starts_at <= starts_at AND occupied_ends_at >= ends_at`
- UNIQUE: (tenant_id, id, line_id)
- UNIQUE: (tenant_id, id, total_amount, currency, is_test)
- EXCLUDE USING GiST: برابری tenant_id و employee_id همراه با تداخل occupied_period در وضعیت‌های اشغال‌کننده ممنوع است.

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_appointments_customer_start ON appointments (tenant_id, customer_id, starts_at)`
- `CREATE INDEX ix_appointments_expiring ON appointments (tenant_id, hold_expires_at) WHERE status = 'AWAITING_PAYMENT'`
- `CREATE INDEX ix_appointments_line_start ON appointments (tenant_id, line_id, starts_at)`
- `CREATE INDEX ix_appointments_tenant_id_employee_id_line_id ON appointments (tenant_id, employee_id, line_id)`
- `CREATE UNIQUE INDEX uq_appointments_customer_hold ON appointments (tenant_id, customer_id) WHERE status = 'AWAITING_PAYMENT'`

## audit_logs

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| actor_kind | VARCHAR(10) | خیر | — | — |
| actor_id | UUID | بله | FK | — |
| platform_actor_id | UUID | بله | FK | — |
| action | VARCHAR(100) | خیر | — | — |
| entity_type | VARCHAR(80) | خیر | — | — |
| entity_id | UUID | بله | — | — |
| request_id | UUID | بله | — | — |
| ip_address | INET | بله | — | — |
| reason | TEXT | بله | — | — |
| event_data | JSONB | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (platform_actor_id) → platform_users(id), ON DELETE RESTRICT.
- (tenant_id, actor_id) → users(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_audit_logs_actor: `(actor_kind = 'USER' AND actor_id IS NOT NULL AND platform_actor_id IS NULL) OR (actor_kind = 'PLATFORM' AND actor_id IS NULL AND platform_actor_id IS NOT NULL) OR (actor_kind = 'SYSTEM' AND actor_id IS NULL AND platform_actor_id IS NULL)`

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_audit_logs_actor ON audit_logs (tenant_id, actor_id, created_at)`
- `CREATE INDEX ix_audit_logs_entity ON audit_logs (tenant_id, entity_type, entity_id, created_at)`
- `CREATE INDEX ix_audit_logs_platform_actor_id ON audit_logs (platform_actor_id)`

## auth_throttles

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| bucket_hash | BYTEA | خیر | — | — |
| purpose | VARCHAR(32) | خیر | — | — |
| attempts | INTEGER | خیر | — | 0 |
| blocked_until | TIMESTAMP WITH TIME ZONE | بله | — | — |
| expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_auth_throttles_bucket: `attempts >= 0 AND octet_length(bucket_hash) = 32`
- UNIQUE: (tenant_id, bucket_hash, purpose)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_auth_throttles_expiry ON auth_throttles (tenant_id, expires_at)`

## auth_tokens

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| user_id | UUID | خیر | FK | — |
| purpose | VARCHAR(18) | خیر | — | — |
| token_hash | BYTEA | خیر | — | — |
| subject_version | INTEGER | خیر | — | — |
| expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| consumed_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, user_id) → users(tenant_id, id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_auth_tokens_expiry: `expires_at > created_at`
- CHECK ck_auth_tokens_hash_length: `octet_length(token_hash) = 32`
- CHECK ck_auth_tokens_subject_version: `subject_version > 0`
- CHECK ck_auth_tokens_token_purpose: `auth_tokens.purpose IN ('EMAIL_VERIFICATION', 'PASSWORD_RESET')`
- UNIQUE: (tenant_id, token_hash)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_auth_tokens_tenant_id_user_id ON auth_tokens (tenant_id, user_id)`

## background_jobs

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| outbox_event_id | UUID | بله | FK | — |
| kind | VARCHAR(100) | خیر | — | — |
| deduplication_key | VARCHAR(180) | خیر | — | — |
| payload | JSONB | خیر | — | — |
| status | VARCHAR(9) | خیر | — | PENDING |
| attempts | INTEGER | خیر | — | 0 |
| max_attempts | INTEGER | خیر | — | 10 |
| run_after | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| lease_owner | UUID | بله | — | — |
| lease_until | TIMESTAMP WITH TIME ZONE | بله | — | — |
| last_error_code | VARCHAR(100) | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, outbox_event_id) → outbox_events(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_background_jobs_attempts: `attempts >= 0 AND max_attempts > 0`
- CHECK ck_background_jobs_job_status: `background_jobs.status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'DEAD')`
- CHECK ck_background_jobs_lease: `(status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_until IS NOT NULL) OR (status <> 'RUNNING' AND lease_owner IS NULL AND lease_until IS NULL)`
- UNIQUE: (tenant_id, deduplication_key)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_background_jobs_tenant_id_outbox_event_id ON background_jobs (tenant_id, outbox_event_id)`
- `CREATE INDEX ix_jobs_due ON background_jobs (tenant_id, run_after) WHERE status = 'PENDING'`
- `CREATE INDEX ix_jobs_expired_lease ON background_jobs (tenant_id, lease_until) WHERE status = 'RUNNING'`

## calendar_controls

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| version | INTEGER | خیر | — | 1 |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_calendar_controls_version: `version > 0`
- UNIQUE: (tenant_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## calendars

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| scope | VARCHAR(13) | خیر | — | — |
| line_id | UUID | بله | FK | — |
| employee_id | UUID | بله | FK | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, employee_id) → employee_profiles(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id, employee_id, line_id) → employee_lines(tenant_id, employee_id, line_id), ON DELETE RESTRICT.
- (tenant_id, line_id) → lines(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_calendars_calendar_scope: `calendars.scope IN ('SALON', 'LINE', 'EMPLOYEE', 'EMPLOYEE_LINE')`
- CHECK ck_calendars_scope_target: `(scope = 'SALON' AND line_id IS NULL AND employee_id IS NULL) OR (scope = 'LINE' AND line_id IS NOT NULL AND employee_id IS NULL) OR (scope = 'EMPLOYEE' AND line_id IS NULL AND employee_id IS NOT NULL) OR (scope = 'EMPLOYEE_LINE' AND line_id IS NOT NULL AND employee_id IS NOT NULL)`
- UNIQUE: (tenant_id, scope, line_id, employee_id)؛ NULLS NOT DISTINCT

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_calendars_tenant_id_employee_id ON calendars (tenant_id, employee_id)`
- `CREATE INDEX ix_calendars_tenant_id_employee_id_line_id ON calendars (tenant_id, employee_id, line_id)`
- `CREATE INDEX ix_calendars_tenant_id_line_id ON calendars (tenant_id, line_id)`

## callback_events

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| attempt_id | UUID | خیر | FK | — |
| provider_event_id | VARCHAR(180) | بله | — | — |
| outcome | VARCHAR(32) | خیر | — | — |
| safe_payload | JSONB | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, attempt_id) → payment_attempts(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_callback_events_tenant_id_attempt_id ON callback_events (tenant_id, attempt_id)`

## credit_notes

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| refund_id | UUID | خیر | FK | — |
| number | VARCHAR(64) | خیر | — | — |
| issued_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, refund_id) → refunds(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, number)
- UNIQUE: (tenant_id, refund_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## customer_profiles

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| user_id | UUID | خیر | FK | — |
| contact_preference | VARCHAR(32) | خیر | — | NONE |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, user_id) → users(tenant_id, id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, user_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## day_overrides

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| calendar_id | UUID | خیر | FK | — |
| local_date | DATE | خیر | — | — |
| mode | VARCHAR(7) | خیر | — | — |
| reason | VARCHAR(300) | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, calendar_id) → calendars(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_day_overrides_day_override_mode: `day_overrides.mode IN ('CLOSED', 'REPLACE')`
- UNIQUE: (tenant_id, calendar_id, local_date)
- UNIQUE: (tenant_id, id, mode)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## employee_lines

جداسازی: FORCE RLS. چرخهٔ عمر: حذف نرم با deleted_at.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| employee_id | UUID | خیر | FK | — |
| line_id | UUID | خیر | FK | — |
| is_active | BOOLEAN | خیر | — | true |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| deleted_at | TIMESTAMP WITH TIME ZONE | بله | — | — |

روابط:

- (tenant_id, employee_id) → employee_profiles(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id, line_id) → lines(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, employee_id, line_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_employee_lines_tenant_id_line_id ON employee_lines (tenant_id, line_id)`

## employee_profiles

جداسازی: FORCE RLS. چرخهٔ عمر: حذف نرم با deleted_at.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| user_id | UUID | خیر | FK | — |
| public_name | VARCHAR(160) | خیر | — | — |
| is_active | BOOLEAN | خیر | — | true |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| deleted_at | TIMESTAMP WITH TIME ZONE | بله | — | — |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, user_id) → users(tenant_id, id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, user_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## employee_services

جداسازی: FORCE RLS. چرخهٔ عمر: حذف نرم با deleted_at.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| employee_id | UUID | خیر | FK | — |
| line_id | UUID | خیر | FK | — |
| service_id | UUID | خیر | FK | — |
| is_active | BOOLEAN | خیر | — | true |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| deleted_at | TIMESTAMP WITH TIME ZONE | بله | — | — |

روابط:

- (tenant_id, employee_id, line_id) → employee_lines(tenant_id, employee_id, line_id), ON DELETE RESTRICT.
- (tenant_id, line_id, service_id) → line_services(tenant_id, line_id, service_id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, employee_id, line_id, service_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_employee_services_tenant_id_line_id_service_id ON employee_services (tenant_id, line_id, service_id)`

## financial_entries

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| kind | VARCHAR(8) | خیر | — | — |
| transaction_id | UUID | خیر | FK | — |
| captured_amount | BIGINT | خیر | FK | — |
| refund_id | UUID | بله | FK | — |
| amount | BIGINT | خیر | FK | — |
| currency | VARCHAR(3) | خیر | FK | — |
| is_test | BOOLEAN | خیر | FK | — |
| booked_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, refund_id, transaction_id, amount, currency, is_test) → refunds(tenant_id, id, transaction_id, amount, currency, is_test), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, transaction_id, captured_amount, currency, is_test) → payment_transactions(tenant_id, id, amount, currency, is_test), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_financial_entries_amount_currency: `amount > 0 AND amount <= captured_amount AND currency = 'IRR' AND (kind <> 'CAPTURE' OR amount = captured_amount)`
- CHECK ck_financial_entries_kind_source: `(kind = 'CAPTURE' AND refund_id IS NULL) OR (kind = 'REFUND' AND refund_id IS NOT NULL)`

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_financial_entries_booked ON financial_entries (tenant_id, is_test, booked_at)`
- `CREATE INDEX ix_financial_entries_tenant_id_refund_id_transaction_id_67e5 ON financial_entries (tenant_id, refund_id, transaction_id, amount, currency, is_test)`
- `CREATE INDEX ix_financial_entries_tenant_id_transaction_id_captured__6e5d ON financial_entries (tenant_id, transaction_id, captured_amount, currency, is_test)`
- `CREATE UNIQUE INDEX uq_financial_entries_capture ON financial_entries (tenant_id, transaction_id) WHERE kind = 'CAPTURE'`
- `CREATE UNIQUE INDEX uq_financial_entries_refund ON financial_entries (tenant_id, refund_id) WHERE kind = 'REFUND'`

## idempotency_records

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| actor_id | UUID | خیر | FK | — |
| operation | VARCHAR(100) | خیر | — | — |
| key | VARCHAR(128) | خیر | — | — |
| request_hash | BYTEA | خیر | — | — |
| state | VARCHAR(16) | خیر | — | PROCESSING |
| response_status | INTEGER | بله | — | — |
| response_body | JSONB | بله | — | — |
| expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, actor_id) → users(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_idempotency_records_completed_response: `state <> 'COMPLETED' OR (response_status BETWEEN 200 AND 599 AND response_body IS NOT NULL)`
- CHECK ck_idempotency_records_hash_length: `octet_length(request_hash) = 32`
- CHECK ck_idempotency_records_state_expiry: `state IN ('PROCESSING', 'COMPLETED') AND expires_at > created_at`
- UNIQUE: (tenant_id, actor_id, operation, key)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_idempotency_expiry ON idempotency_records (tenant_id, expires_at)`

## invoice_items

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| invoice_id | UUID | خیر | FK | — |
| appointment_id | UUID | خیر | FK | — |
| appointment_item_id | UUID | خیر | FK | — |
| position | INTEGER | خیر | — | — |
| description | VARCHAR(200) | خیر | — | — |
| amount | BIGINT | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, appointment_item_id, appointment_id) → appointment_items(tenant_id, id, appointment_id), ON DELETE RESTRICT.
- (tenant_id, invoice_id, appointment_id) → invoices(tenant_id, id, appointment_id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_invoice_items_values: `amount >= 0 AND position > 0`
- UNIQUE: (tenant_id, invoice_id, appointment_item_id)
- UNIQUE: (tenant_id, invoice_id, position)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_invoice_items_tenant_id_appointment_item_id_appointment_id ON invoice_items (tenant_id, appointment_item_id, appointment_id)`
- `CREATE INDEX ix_invoice_items_tenant_id_invoice_id_appointment_id ON invoice_items (tenant_id, invoice_id, appointment_id)`

## invoices

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| appointment_id | UUID | خیر | FK | — |
| number | VARCHAR(64) | خیر | — | — |
| total_amount | BIGINT | خیر | FK | — |
| currency | VARCHAR(3) | خیر | FK | — |
| is_test | BOOLEAN | خیر | FK | — |
| issued_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| seller_snapshot | JSONB | خیر | — | — |
| buyer_snapshot | JSONB | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, appointment_id, total_amount, currency, is_test) → appointments(tenant_id, id, total_amount, currency, is_test), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_invoices_amount_currency: `total_amount >= 0 AND currency = 'IRR'`
- UNIQUE: (tenant_id, appointment_id)
- UNIQUE: (tenant_id, id, appointment_id)
- UNIQUE: (tenant_id, number)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_invoices_tenant_id_appointment_id_total_amount_curre_f60d ON invoices (tenant_id, appointment_id, total_amount, currency, is_test)`

## line_services

جداسازی: FORCE RLS. چرخهٔ عمر: حذف نرم با deleted_at.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| line_id | UUID | خیر | FK | — |
| service_id | UUID | خیر | FK | — |
| price_amount | BIGINT | خیر | — | — |
| currency | VARCHAR(3) | خیر | — | IRR |
| duration_minutes | INTEGER | خیر | — | — |
| buffer_before_minutes | INTEGER | خیر | — | 0 |
| buffer_after_minutes | INTEGER | خیر | — | 0 |
| is_free | BOOLEAN | خیر | — | false |
| is_active | BOOLEAN | خیر | — | true |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| deleted_at | TIMESTAMP WITH TIME ZONE | بله | — | — |

روابط:

- (tenant_id, line_id) → lines(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, service_id) → services(tenant_id, id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_line_services_buffers: `buffer_before_minutes BETWEEN 0 AND 240 AND buffer_after_minutes BETWEEN 0 AND 240`
- CHECK ck_line_services_currency: `currency = 'IRR'`
- CHECK ck_line_services_duration: `duration_minutes BETWEEN 1 AND 1440`
- CHECK ck_line_services_price: `price_amount >= 0 AND is_free = (price_amount = 0)`
- UNIQUE: (tenant_id, line_id, service_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_line_services_tenant_id_service_id ON line_services (tenant_id, service_id)`

## lines

جداسازی: FORCE RLS. چرخهٔ عمر: حذف نرم با deleted_at.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| name | VARCHAR(120) | خیر | — | — |
| slug | VARCHAR(100) | خیر | — | — |
| is_active | BOOLEAN | خیر | — | true |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| deleted_at | TIMESTAMP WITH TIME ZONE | بله | — | — |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_lines_name: `length(trim(name)) > 0`
- UNIQUE: (tenant_id, slug)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## mock_orders

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| account_id | UUID | خیر | FK | — |
| request_key | VARCHAR(128) | خیر | — | — |
| merchant | VARCHAR(160) | خیر | — | — |
| amount | BIGINT | خیر | — | — |
| currency | VARCHAR(3) | خیر | — | — |
| status | VARCHAR(16) | خیر | — | PENDING |
| scenario | VARCHAR(32) | بله | — | — |
| unknown_reads | INTEGER | خیر | — | 0 |
| received_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, account_id) → payment_accounts(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_mock_orders_amount_currency: `amount > 0 AND currency = 'IRR'`
- CHECK ck_mock_orders_status: `status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'CANCELLED')`
- CHECK ck_mock_orders_unknown_reads: `unknown_reads >= 0`
- UNIQUE: (tenant_id, account_id, request_key)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## mock_refunds

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| order_id | UUID | خیر | FK | — |
| request_key | VARCHAR(128) | خیر | — | — |
| amount | BIGINT | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, order_id) → mock_orders(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_mock_refunds_amount: `amount > 0`
- UNIQUE: (tenant_id, order_id, request_key)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## notifications

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| user_id | UUID | خیر | FK | — |
| kind | VARCHAR(80) | خیر | — | — |
| title | VARCHAR(180) | خیر | — | — |
| body | TEXT | خیر | — | — |
| deduplication_key | VARCHAR(180) | خیر | — | — |
| read_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, user_id) → users(tenant_id, id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, user_id, deduplication_key)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_notifications_unread ON notifications (tenant_id, user_id, created_at) WHERE read_at IS NULL`

## outbox_events

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| event_type | VARCHAR(100) | خیر | — | — |
| aggregate_id | UUID | خیر | — | — |
| deduplication_key | VARCHAR(180) | خیر | — | — |
| payload | JSONB | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, deduplication_key)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## payment_accounts

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| provider | VARCHAR(40) | خیر | — | — |
| merchant_reference | VARCHAR(160) | خیر | — | — |
| secret_ref | VARCHAR(255) | بله | — | — |
| is_test | BOOLEAN | خیر | — | — |
| is_active | BOOLEAN | خیر | — | true |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_payment_accounts_mock_is_test: `provider <> 'mock' OR is_test`
- UNIQUE: (id)
- UNIQUE: (provider, merchant_reference, is_test)
- UNIQUE: (tenant_id, id, is_test)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## payment_allocations

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| intent_id | UUID | خیر | FK | — |
| transaction_id | UUID | خیر | FK | — |
| amount | BIGINT | خیر | FK | — |
| currency | VARCHAR(3) | خیر | FK | — |
| is_test | BOOLEAN | خیر | FK | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, intent_id, amount, currency, is_test) → payment_intents(tenant_id, id, amount, currency, is_test), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, transaction_id, intent_id, amount, currency, is_test) → payment_transactions(tenant_id, id, intent_id, amount, currency, is_test), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, intent_id)
- UNIQUE: (tenant_id, transaction_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_payment_allocations_tenant_id_intent_id_amount_curre_fe7d ON payment_allocations (tenant_id, intent_id, amount, currency, is_test)`
- `CREATE INDEX ix_payment_allocations_tenant_id_transaction_id_intent__b863 ON payment_allocations (tenant_id, transaction_id, intent_id, amount, currency, is_test)`

## payment_attempts

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| intent_id | UUID | خیر | FK | — |
| account_id | UUID | خیر | FK | — |
| amount | BIGINT | خیر | FK | — |
| currency | VARCHAR(3) | خیر | FK | — |
| is_test | BOOLEAN | خیر | FK | — |
| status | VARCHAR(23) | خیر | — | CREATED |
| request_key | VARCHAR(128) | خیر | — | — |
| gateway_order_id | VARCHAR(180) | بله | — | — |
| next_check_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| verified_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| failure_code | VARCHAR(80) | بله | — | — |
| safe_response | JSONB | خیر | — | '{}'::jsonb |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, account_id, is_test) → payment_accounts(tenant_id, id, is_test), ON DELETE RESTRICT.
- (tenant_id, intent_id, amount, currency, is_test) → payment_intents(tenant_id, id, amount, currency, is_test), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_payment_attempts_amount_currency: `amount > 0 AND currency = 'IRR'`
- CHECK ck_payment_attempts_attempt_status: `payment_attempts.status IN ('CREATED', 'PENDING', 'VERIFYING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED', 'RECONCILIATION_REQUIRED')`
- UNIQUE: (account_id, gateway_order_id)
- UNIQUE: (tenant_id, id, intent_id, account_id, currency, is_test)
- UNIQUE: (tenant_id, intent_id, request_key)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_payment_attempts_reconcile ON payment_attempts (tenant_id, next_check_at) WHERE status <> 'SUCCEEDED'`
- `CREATE INDEX ix_payment_attempts_tenant_id_account_id_is_test ON payment_attempts (tenant_id, account_id, is_test)`
- `CREATE INDEX ix_payment_attempts_tenant_id_intent_id_amount_currency_is_test ON payment_attempts (tenant_id, intent_id, amount, currency, is_test)`
- `CREATE UNIQUE INDEX uq_payment_attempts_open_intent ON payment_attempts (tenant_id, intent_id) WHERE status IN ('CREATED', 'PENDING', 'VERIFYING', 'RECONCILIATION_REQUIRED')`

## payment_intents

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| appointment_id | UUID | خیر | FK | — |
| amount | BIGINT | خیر | FK | — |
| currency | VARCHAR(3) | خیر | FK | — |
| is_test | BOOLEAN | خیر | FK | — |
| status | VARCHAR(23) | خیر | — | CREATED |
| expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, appointment_id, amount, currency, is_test) → appointments(tenant_id, id, total_amount, currency, is_test), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_payment_intents_amount_currency: `amount > 0 AND currency = 'IRR'`
- CHECK ck_payment_intents_expiry: `expires_at > created_at`
- CHECK ck_payment_intents_payment_status: `payment_intents.status IN ('CREATED', 'PENDING', 'VERIFYING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED', 'RECONCILIATION_REQUIRED')`
- UNIQUE: (tenant_id, appointment_id)
- UNIQUE: (tenant_id, id, amount, currency, is_test)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_payment_intents_tenant_id_appointment_id_amount_curr_f2fd ON payment_intents (tenant_id, appointment_id, amount, currency, is_test)`

## payment_transactions

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| attempt_id | UUID | خیر | FK | — |
| intent_id | UUID | خیر | FK | — |
| account_id | UUID | خیر | FK | — |
| amount | BIGINT | خیر | — | — |
| currency | VARCHAR(3) | خیر | FK | — |
| is_test | BOOLEAN | خیر | FK | — |
| gateway_transaction_id | VARCHAR(180) | خیر | — | — |
| received_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| verified_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| evidence | JSONB | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, attempt_id, intent_id, account_id, currency, is_test) → payment_attempts(tenant_id, id, intent_id, account_id, currency, is_test), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_payment_transactions_amount_currency: `amount > 0 AND currency = 'IRR'`
- UNIQUE: (account_id, gateway_transaction_id)
- UNIQUE: (tenant_id, id, amount, currency, is_test)
- UNIQUE: (tenant_id, id, intent_id, amount, currency, is_test)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_payment_transactions_received ON payment_transactions (tenant_id, received_at)`
- `CREATE INDEX ix_payment_transactions_tenant_id_attempt_id_intent_id__a142 ON payment_transactions (tenant_id, attempt_id, intent_id, account_id, currency, is_test)`

## permissions

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| code | VARCHAR(100) | خیر | PK | — |
| description | TEXT | خیر | — | — |

روابط:

- رابطهٔ خروجی ندارد.

قیود یکتا و اعتبارسنجی:

- PK: (code).
- CHECK ck_permissions_code: `code ~ '^[a-z][a-z0-9_.]+$'`

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## platform_audit_logs

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| actor_id | UUID | بله | FK | — |
| action | VARCHAR(100) | خیر | — | — |
| entity_id | UUID | بله | — | — |
| event_data | JSONB | خیر | — | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (actor_id) → platform_users(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (id).

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_platform_audit_logs_actor_id ON platform_audit_logs (actor_id)`

## platform_auth_throttles

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| key | BYTEA | خیر | PK | — |
| attempts | INTEGER | خیر | — | — |
| expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |

روابط:

- رابطهٔ خروجی ندارد.

قیود یکتا و اعتبارسنجی:

- PK: (key).
- CHECK ck_platform_auth_throttles_values: `attempts > 0 AND octet_length(key) = 32`

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_platform_auth_throttles_expires_at ON platform_auth_throttles (expires_at)`

## platform_role_assignments

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| role_id | UUID | خیر | FK | — |
| user_id | UUID | خیر | FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (role_id) → platform_roles(id), ON DELETE RESTRICT.
- (user_id) → platform_users(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (id).
- UNIQUE: (role_id, user_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_platform_role_assignments_user_id ON platform_role_assignments (user_id)`

## platform_role_permissions

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| role_id | UUID | خیر | FK | — |
| permission_code | VARCHAR(100) | خیر | FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (permission_code) → permissions(code), ON DELETE RESTRICT.
- (role_id) → platform_roles(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (id).
- UNIQUE: (role_id, permission_code)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_platform_role_permissions_permission_code ON platform_role_permissions (permission_code)`

## platform_roles

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| code | VARCHAR(80) | خیر | — | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- رابطهٔ خروجی ندارد.

قیود یکتا و اعتبارسنجی:

- PK: (id).
- UNIQUE: (code)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## platform_sessions

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| user_id | UUID | خیر | FK | — |
| token_hash | BYTEA | خیر | — | — |
| csrf_hash | BYTEA | خیر | — | — |
| expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| idle_expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| revoked_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (user_id) → platform_users(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (id).
- CHECK ck_platform_sessions_expiry: `expires_at > created_at AND idle_expires_at <= expires_at`
- CHECK ck_platform_sessions_hash_length: `octet_length(token_hash) = 32 AND octet_length(csrf_hash) = 32`
- UNIQUE: (token_hash)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_platform_sessions_user_id ON platform_sessions (user_id)`

## platform_users

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| email_normalized | VARCHAR(254) | بله | — | — |
| phone_normalized | VARCHAR(16) | بله | — | — |
| display_name | VARCHAR(160) | خیر | — | Platform administrator |
| password_hash | VARCHAR(512) | خیر | — | — |
| mfa_secret_ref | VARCHAR(255) | بله | — | — |
| is_active | BOOLEAN | خیر | — | true |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- رابطهٔ خروجی ندارد.

قیود یکتا و اعتبارسنجی:

- PK: (id).
- CHECK ck_platform_users_email_normalized: `email_normalized = lower(trim(email_normalized))`
- CHECK ck_platform_users_phone_normalized: `phone_normalized IS NULL OR phone_normalized ~ '^\+989[0-9]{9}$'`
- UNIQUE: (email_normalized)
- UNIQUE: (phone_normalized)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## receipts

جداسازی: FORCE RLS. چرخهٔ عمر: الحاقی؛ Update/Delete با Trigger ممنوع.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| transaction_id | UUID | خیر | FK | — |
| number | VARCHAR(64) | خیر | — | — |
| amount | BIGINT | خیر | FK | — |
| currency | VARCHAR(3) | خیر | FK | — |
| is_test | BOOLEAN | خیر | FK | — |
| issued_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, transaction_id, amount, currency, is_test) → payment_transactions(tenant_id, id, amount, currency, is_test), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, number)
- UNIQUE: (tenant_id, transaction_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_receipts_tenant_id_transaction_id_amount_currency_is_test ON receipts (tenant_id, transaction_id, amount, currency, is_test)`

## refunds

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| transaction_id | UUID | خیر | FK | — |
| captured_amount | BIGINT | خیر | FK | — |
| amount | BIGINT | خیر | — | — |
| currency | VARCHAR(3) | خیر | FK | — |
| is_test | BOOLEAN | خیر | FK | — |
| status | VARCHAR(23) | خیر | — | REQUESTED |
| request_key | VARCHAR(128) | خیر | — | — |
| gateway_refund_id | VARCHAR(180) | بله | — | — |
| requested_by_id | UUID | بله | FK | — |
| approved_by_id | UUID | بله | FK | — |
| reason | TEXT | خیر | — | — |
| succeeded_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| next_check_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, approved_by_id) → users(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id, requested_by_id) → users(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, transaction_id, captured_amount, currency, is_test) → payment_transactions(tenant_id, id, amount, currency, is_test), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_refunds_amount_currency: `amount > 0 AND amount <= captured_amount AND currency = 'IRR'`
- CHECK ck_refunds_refund_status: `refunds.status IN ('REQUESTED', 'APPROVED', 'PROCESSING', 'RECONCILIATION_REQUIRED', 'SUCCEEDED', 'FAILED', 'CANCELLED')`
- CHECK ck_refunds_success_time: `status <> 'SUCCEEDED' OR succeeded_at IS NOT NULL`
- UNIQUE: (tenant_id, id, transaction_id, amount, currency, is_test)
- UNIQUE: (tenant_id, request_key)
- UNIQUE: (tenant_id, transaction_id, gateway_refund_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_refunds_reconcile ON refunds (tenant_id, next_check_at) WHERE status IN ('APPROVED', 'PROCESSING', 'RECONCILIATION_REQUIRED')`
- `CREATE INDEX ix_refunds_tenant_id_approved_by_id ON refunds (tenant_id, approved_by_id)`
- `CREATE INDEX ix_refunds_tenant_id_requested_by_id ON refunds (tenant_id, requested_by_id)`
- `CREATE INDEX ix_refunds_tenant_id_transaction_id_captured_amount_cur_79ef ON refunds (tenant_id, transaction_id, captured_amount, currency, is_test)`

## role_assignments

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| user_id | UUID | خیر | FK | — |
| role_id | UUID | خیر | FK | — |
| scope | VARCHAR(10) | خیر | — | — |
| line_id | UUID | بله | FK | — |
| granted_by_id | UUID | بله | FK | — |
| revoked_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, granted_by_id) → users(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id, line_id) → lines(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id, role_id) → roles(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, user_id) → users(tenant_id, id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_role_assignments_scope: `(scope = 'TENANT' AND line_id IS NULL) OR (scope = 'LINE' AND line_id IS NOT NULL)`

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_role_assignments_tenant_id_granted_by_id ON role_assignments (tenant_id, granted_by_id)`
- `CREATE INDEX ix_role_assignments_tenant_id_line_id ON role_assignments (tenant_id, line_id)`
- `CREATE INDEX ix_role_assignments_tenant_id_role_id ON role_assignments (tenant_id, role_id)`
- `CREATE INDEX ix_role_assignments_tenant_id_user_id ON role_assignments (tenant_id, user_id)`
- `CREATE UNIQUE INDEX uq_role_assignments_active ON role_assignments (tenant_id, user_id, role_id, scope, line_id) NULLS NOT DISTINCT WHERE revoked_at IS NULL`

## role_permissions

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| role_id | UUID | خیر | FK | — |
| permission_code | VARCHAR(100) | خیر | FK | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (permission_code) → permissions(code), ON DELETE RESTRICT.
- (tenant_id, role_id) → roles(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, role_id, permission_code)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_role_permissions_permission_code ON role_permissions (permission_code)`

## roles

جداسازی: FORCE RLS. چرخهٔ عمر: حذف نرم با deleted_at.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| code | VARCHAR(80) | خیر | — | — |
| name | VARCHAR(120) | خیر | — | — |
| is_system | BOOLEAN | خیر | — | false |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| deleted_at | TIMESTAMP WITH TIME ZONE | بله | — | — |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, code)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## salon_settings

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| currency | VARCHAR(3) | خیر | — | IRR |
| hold_minutes | INTEGER | خیر | — | 10 |
| slot_step_minutes | INTEGER | خیر | — | 15 |
| min_notice_minutes | INTEGER | خیر | — | 60 |
| booking_horizon_days | INTEGER | خیر | — | 90 |
| cancel_before_minutes | INTEGER | خیر | — | 1440 |
| max_services | INTEGER | خیر | — | 10 |
| max_duration_minutes | INTEGER | خیر | — | 720 |
| policy_version | INTEGER | خیر | — | 1 |
| no_show_grace_minutes | INTEGER | خیر | — | 15 |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_salon_settings_booking_limits: `cancel_before_minutes >= 0 AND max_services BETWEEN 1 AND 20 AND max_duration_minutes BETWEEN 1 AND 1440`
- CHECK ck_salon_settings_booking_window: `min_notice_minutes >= 0 AND booking_horizon_days BETWEEN 1 AND 366`
- CHECK ck_salon_settings_currency: `currency = 'IRR'`
- CHECK ck_salon_settings_hold_minutes: `hold_minutes BETWEEN 1 AND 60`
- CHECK ck_salon_settings_no_show_grace: `no_show_grace_minutes BETWEEN 0 AND 240`
- CHECK ck_salon_settings_policy_version: `policy_version > 0`
- CHECK ck_salon_settings_slot_step: `slot_step_minutes BETWEEN 1 AND 120`
- UNIQUE: (tenant_id)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## salons

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| name | VARCHAR(160) | خیر | — | — |
| timezone | VARCHAR(80) | خیر | — | Asia/Tehran |
| status | VARCHAR(16) | خیر | — | ACTIVE |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- رابطهٔ خروجی ندارد.

قیود یکتا و اعتبارسنجی:

- PK: (id).
- CHECK ck_salons_name_not_blank: `length(trim(name)) > 0`
- CHECK ck_salons_status: `status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')`

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## schedule_blocks

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| calendar_id | UUID | خیر | FK | — |
| kind | VARCHAR(7) | خیر | — | — |
| status | VARCHAR(9) | خیر | — | REQUESTED |
| starts_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| ends_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| requested_by_id | UUID | بله | FK | — |
| approved_by_id | UUID | بله | FK | — |
| reason | TEXT | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, approved_by_id) → users(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id, calendar_id) → calendars(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id, requested_by_id) → users(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_schedule_blocks_block_kind: `schedule_blocks.kind IN ('LEAVE', 'HOLIDAY', 'BLOCKED')`
- CHECK ck_schedule_blocks_block_status: `schedule_blocks.status IN ('REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED')`
- CHECK ck_schedule_blocks_interval: `ends_at > starts_at`

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_schedule_blocks_calendar_start ON schedule_blocks (tenant_id, calendar_id, starts_at)`
- `CREATE INDEX ix_schedule_blocks_tenant_id_approved_by_id ON schedule_blocks (tenant_id, approved_by_id)`
- `CREATE INDEX ix_schedule_blocks_tenant_id_requested_by_id ON schedule_blocks (tenant_id, requested_by_id)`

## services

جداسازی: FORCE RLS. چرخهٔ عمر: حذف نرم با deleted_at.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| code | VARCHAR(80) | خیر | — | — |
| name | VARCHAR(160) | خیر | — | — |
| description | TEXT | بله | — | — |
| is_active | BOOLEAN | خیر | — | true |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| deleted_at | TIMESTAMP WITH TIME ZONE | بله | — | — |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- UNIQUE: (tenant_id, code)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## sessions

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| user_id | UUID | خیر | FK | — |
| token_hash | BYTEA | خیر | — | — |
| csrf_hash | BYTEA | خیر | — | — |
| expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| idle_expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| last_seen_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| revoked_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| auth_version | INTEGER | خیر | — | — |
| grants_fingerprint | VARCHAR(64) | خیر | — |  |
| ip_address | INET | بله | — | — |
| user_agent | VARCHAR(512) | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.
- (tenant_id, user_id) → users(tenant_id, id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_sessions_auth_version: `auth_version > 0`
- CHECK ck_sessions_expiry: `expires_at > created_at AND idle_expires_at <= expires_at`
- CHECK ck_sessions_hash_lengths: `octet_length(token_hash) = 32 AND octet_length(csrf_hash) = 32`
- UNIQUE: (tenant_id, token_hash)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_sessions_expiry ON sessions (tenant_id, expires_at) WHERE revoked_at IS NULL`
- `CREATE INDEX ix_sessions_tenant_id_user_id ON sessions (tenant_id, user_id)`

## special_periods

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| override_id | UUID | خیر | FK | — |
| override_mode | VARCHAR(7) | خیر | FK | REPLACE |
| start_minute | INTEGER | خیر | — | — |
| end_minute | INTEGER | خیر | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, override_id, override_mode) → day_overrides(tenant_id, id, mode), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_special_periods_minutes: `start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440`
- CHECK ck_special_periods_replace_only: `override_mode = 'REPLACE'`
- UNIQUE: (tenant_id, override_id, start_minute, end_minute)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_special_periods_tenant_id_override_id_override_mode ON special_periods (tenant_id, override_id, override_mode)`

## support_grants

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| platform_user_id | UUID | خیر | FK | — |
| reason | TEXT | خیر | — | — |
| expires_at | TIMESTAMP WITH TIME ZONE | خیر | — | — |
| revoked_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (platform_user_id) → platform_users(id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_support_grants_expiry_reason: `expires_at > created_at AND length(trim(reason)) > 0`

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_support_grants_platform_user_id ON support_grants (platform_user_id)`

## tenant_domains

جداسازی: Control plane / Global؛ دسترسی صریح. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| tenant_id | UUID | خیر | FK | — |
| hostname | VARCHAR(253) | خیر | — | — |
| verified_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| is_active | BOOLEAN | خیر | — | false |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (id).
- CHECK ck_tenant_domains_canonical_hostname: `hostname = lower(hostname) AND hostname !~ '[/ :]' AND length(hostname) > 0`
- UNIQUE: (hostname)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- `CREATE INDEX ix_tenant_domains_tenant_id ON tenant_domains (tenant_id)`

## users

جداسازی: FORCE RLS. چرخهٔ عمر: حذف نرم با deleted_at.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| email_normalized | VARCHAR(254) | بله | — | — |
| password_hash | VARCHAR(512) | خیر | — | — |
| mfa_secret_ref | VARCHAR(255) | بله | — | — |
| display_name | VARCHAR(160) | خیر | — | — |
| phone | VARCHAR(24) | بله | — | — |
| phone_normalized | VARCHAR(16) | بله | — | — |
| phone_verified_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| email_verified_at | TIMESTAMP WITH TIME ZONE | بله | — | — |
| is_active | BOOLEAN | خیر | — | true |
| auth_version | INTEGER | خیر | — | 1 |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| deleted_at | TIMESTAMP WITH TIME ZONE | بله | — | — |

روابط:

- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_users_auth_version: `auth_version > 0`
- CHECK ck_users_email_normalized: `email_normalized = lower(trim(email_normalized)) AND position('@' in email_normalized) > 1`
- CHECK ck_users_phone_normalized: `phone_normalized IS NULL OR phone_normalized ~ '^\+989[0-9]{9}$'`
- CHECK ck_users_phone_verification: `phone_verified_at IS NULL OR phone_normalized IS NOT NULL`
- UNIQUE: (tenant_id, email_normalized)
- UNIQUE: (tenant_id, phone_normalized)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.

## weekly_periods

جداسازی: FORCE RLS. چرخهٔ عمر: تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK.

| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |
|---|---|---|---|---|
| calendar_id | UUID | خیر | FK | — |
| kind | VARCHAR(8) | خیر | — | OPEN |
| weekday | INTEGER | خیر | — | — |
| start_minute | INTEGER | خیر | — | — |
| end_minute | INTEGER | خیر | — | — |
| valid_from | DATE | خیر | — | — |
| valid_until | DATE | بله | — | — |
| tenant_id | UUID | خیر | PK, FK | — |
| id | UUID | خیر | PK | gen_random_uuid() |
| created_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |
| updated_at | TIMESTAMP WITH TIME ZONE | خیر | — | now() |

روابط:

- (tenant_id, calendar_id) → calendars(tenant_id, id), ON DELETE RESTRICT.
- (tenant_id) → salons(id), ON DELETE RESTRICT.

قیود یکتا و اعتبارسنجی:

- PK: (tenant_id, id).
- CHECK ck_weekly_periods_effective_dates: `valid_until IS NULL OR valid_until > valid_from`
- CHECK ck_weekly_periods_kind: `kind IN ('OPEN', 'BREAK')`
- CHECK ck_weekly_periods_minutes: `start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440`
- CHECK ck_weekly_periods_weekday: `weekday BETWEEN 0 AND 6`
- UNIQUE: (tenant_id, calendar_id, kind, weekday, start_minute, end_minute, valid_from)

Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):

- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.
