# ERD مرحلهٔ ۲

این نمودارها روابط اصلی مرحلهٔ ۲ را نشان می‌دهند. تمام FKهای بین موجودیت‌های یک سالن، tenant_id را نیز دارند. طرح جاری پس از مرحلهٔ ۹ شامل ۵۳ جدول است؛ جزئیات و دو جدول شبیه‌ساز پرداخت در [ERD کامل](schema-erd.mmd) و [فرهنگ داده](schema-dictionary.md) آمده‌اند.

## هویت، نقش و کاتالوگ

```mermaid
erDiagram
    salons ||--o{ users : owns
    users ||--o| customer_profiles : customer
    users ||--o| employee_profiles : employee
    users ||--o{ sessions : authenticates
    users ||--o{ auth_tokens : verifies
    users ||--o{ role_assignments : receives
    roles ||--o{ role_assignments : assigned
    roles ||--o{ role_permissions : grants
    permissions ||--o{ role_permissions : defines
    lines o|--o{ role_assignments : scopes
    salons ||--o{ lines : contains
    lines ||--o{ line_services : offers
    services ||--o{ line_services : supplied
    employee_profiles ||--o{ employee_lines : joins
    lines ||--o{ employee_lines : has
    employee_lines ||--o{ employee_services : qualifies
    line_services ||--o{ employee_services : permitted
```

Employee و Customer قابل جمع روی یک User هستند. یک RoleAssignment یا در سطح Tenant است یا یک Line مشخص. مدیر پلتفرم از این Userها و نقش‌ها جداست.

## تقویم و نوبت

```mermaid
erDiagram
    salons ||--o| calendar_controls : serializes_edits
    salons ||--o{ calendars : owns
    lines o|--o{ calendars : scopes
    employee_profiles o|--o{ calendars : scopes
    calendars ||--o{ weekly_periods : weekly_open_or_break
    calendars ||--o{ day_overrides : overrides_date
    day_overrides ||--o{ special_periods : replacement_hours
    calendars ||--o{ schedule_blocks : leave_holiday_block
    customer_profiles ||--o{ appointments : books
    employee_lines ||--o{ appointments : assigned
    appointments ||--o{ appointment_items : snapshots
    employee_services ||--o{ appointment_items : original_qualification
    appointments ||--o{ appointment_history : records
```

هر Appointment دارای Range محاسبه‌شدهٔ اشغال و قید عدم تداخل متخصص است. صفر قلم در سطح FK ممکن است؛ Service مرحلهٔ ۸ ایجاد نوبت با حداقل یک قلم و مجموع صحیح را در یک تراکنش تضمین می‌کند.

## پرداخت و اسناد

```mermaid
erDiagram
    appointments ||--o| payment_intents : expects
    payment_intents ||--o{ payment_attempts : attempts
    payment_accounts ||--o{ payment_attempts : routes
    payment_attempts ||--o{ payment_transactions : actual_receipts
    payment_attempts ||--o{ callback_events : callbacks
    payment_intents ||--o| payment_allocations : settled_once
    payment_transactions ||--o| payment_allocations : applied_once
    payment_transactions ||--o| receipts : documents
    payment_transactions ||--o{ refunds : returns
    refunds ||--o| credit_notes : documents
    appointments ||--o| invoices : invoices
    invoices ||--o{ invoice_items : contains
    appointment_items ||--o{ invoice_items : source
    payment_transactions ||--o{ financial_entries : cash_events
    refunds o|--o{ financial_entries : refund_event
```

یک PaymentAttempt ممکن است بیش از یک دریافت واقعی داشته باشد؛ این دریافت‌ها حذف نمی‌شوند. PaymentAllocation حداکثر یک تسویهٔ معتبر برای سفارش می‌پذیرد. مبلغ ناسازگار می‌تواند به‌عنوان دریافت واقعی برای رسیدگی ثبت شود، ولی قابل تخصیص به سفارش نیست.

## عملیات و پلتفرم

```mermaid
erDiagram
    salons ||--o{ audit_logs : audited
    users o|--o{ audit_logs : actor
    users ||--o{ notifications : receives
    users ||--o{ idempotency_records : deduplicates
    salons ||--o{ outbox_events : emits
    outbox_events o|--o{ background_jobs : schedules
    platform_users ||--o{ platform_sessions : authenticates
    platform_users ||--o{ platform_role_assignments : receives
    platform_roles ||--o{ platform_role_assignments : assigned
    platform_roles ||--o{ platform_role_permissions : grants
    permissions ||--o{ platform_role_permissions : defines
    platform_users ||--o{ support_grants : authorized_support
    salons ||--o{ support_grants : target
    platform_users o|--o{ platform_audit_logs : records
```

شناسهٔ entity در Audit یک مرجع عمومی برای چند نوع موجودیت است و FK مستقیم ندارد؛ حذف موجودیت نباید رخداد Audit را از بین ببرد. این استثنا فقط برای ارجاع حسابرسی است و در روابط مالی و رزرو استفاده نشده است.
