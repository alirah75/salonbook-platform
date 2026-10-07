# مرحلهٔ ۲ از ۱۵ — طراحی و پیاده‌سازی لایهٔ داده

مبنای کار: معماری تأییدشدهٔ مرحلهٔ ۱. دامنه: PostgreSQL، مدل‌های SQLAlchemy، migrationهای Alembic، امنیت لایهٔ داده و آزمون‌های همین مرحله. Backend HTTP و مراحل ۳ به بعد در این تحویل آغاز نشده‌اند.

وضعیت: مرحلهٔ ۲ تکمیل و با درخواست «بریم گام بعدی» برای ورود به مرحلهٔ ۳ تأیید شد. نتیجهٔ تحویل این مرحله: **۸۳ آزمون موفق، بدون هشدار؛ Lint، قالب‌بندی و Type Check موفق**. [گزارش تاریخی مرحلهٔ ۲](../database/verification-stage-02.md) · [وضعیت مرحلهٔ ۳](stage-03.md)

## هدف و تصمیم‌های نهایی

هدف، تبدیل قواعد معماری به ساختاری است که خطاهای مهم را در خود دیتابیس رد کند و برای پیاده‌سازی Serviceها قرارداد مشخص داشته باشد. **۵۱ جدول در ۱۰ ماژول**، دو migration نسخه‌دار و اسناد کامل طراحی ایجاد شدند.

| تصمیم | علت و اثر |
|---|---|
| PostgreSQL 18، SQLAlchemy 2.0، Psycopg 3 | پشتیبانی از تراکنش، Range، Exclusion، RLS و اتصال همگام/ناهمگام در مراحل بعد |
| کلید اصلی جدول‌های سالن: tenant_id + id | جلوگیری از ابهام هویت و مناسب‌بودن ابتدای Index برای محدودیت سالن |
| FKهای مرکب شامل Tenant | UUID متعلق به سالن دیگر نمی‌تواند به رکورد این سالن متصل شود |
| UUID تصادفی و timestamptz | شناسهٔ غیرترتیبی و حفظ لحظهٔ دقیق مستقل از نمایش شمسی |
| مبلغ BIGINT و ارز IRR | حذف خطای اعشاری پول و قرارداد روشن با Provider |
| وضعیت با CHECK و Enum پایتون | مقدار ناشناخته رد می‌شود؛ افزودن وضعیت تغییر نسخه‌دار Schema است |
| اشغال متخصص داخل Appointment | در نسخهٔ تک‌متخصص، دو وضعیت جدا برای نوبت و ظرفیت ایجاد نمی‌شود |
| دریافت وجه جدا از تخصیص به سفارش | دریافت تکراری/دیرهنگام حفظ می‌شود؛ سفارش فقط یک بار تسویه می‌شود |
| سند و رخداد مالی الحاقی | اصلاح با رویداد یا سند جبرانی انجام می‌شود؛ تاریخچه پاک نمی‌شود |
| RLS همراه با Grant محدود | درخواست فاقد زمینهٔ سالن داده‌ای نمی‌بیند؛ اتصال برنامه مالک دیتابیس نیست |

نسخهٔ دقیق کتابخانه‌ها در backend/uv.lock قفل شده است: SQLAlchemy 2.0.54، Alembic 1.20.0 و Psycopg 3.3.6. محیط این مرحله Python 3.13 است. Image آزمایش PostgreSQL نیز با digest ثابت استفاده می‌شود.

## خروجی‌های قابل بازبینی

- [ERDهای خوانا بر اساس حوزه](../database/erd.md)
- [ERD کامل تولیدشده از مدل‌ها](../database/schema-erd.mmd)
- [فرهنگ داده: تمام ستون‌ها، انواع، PK/FK، CHECK، UNIQUE و Indexها](../database/schema-dictionary.md)
- [SQL کامل Schema، RLS و Triggerها](../database/schema.sql)
- [قرارداد اجرای migration](../../backend/alembic/README.md)

فرهنگ داده و SQL از مدل‌ها و migrationها تولید می‌شوند. دستور بررسی اسناد در انتهای این سند، قدیمی‌شدن خروجی‌ها را تشخیص می‌دهد. نام طولانی Constraintها مطابق قرارداد SQLAlchemy به‌صورت قطعی کوتاه می‌شود؛ نام فیزیکی الزاماً متن کامل نام در مدل نیست.

## موجودیت‌ها و روابط

| حوزه | جدول‌ها و روابط اصلی |
|---|---|
| سالن | salons، tenant_domains، salon_settings، calendar_controls؛ تنظیمات و ردیف کنترل تقویم برای هر سالن حداکثر یکی |
| هویت | users، customer_profiles، sessions، auth_tokens، auth_throttles؛ مشتری یک پروفایل روی User است و Tokenها Hash نگهداری می‌شوند |
| دسترسی | permissions، roles، role_permissions، role_assignments؛ انتساب نقش در سطح سالن یا لاین، با امکان لغو |
| مدیریت پلتفرم | platform_users، platform_sessions، platform_roles، platform_role_permissions، platform_role_assignments، support_grants؛ جدا از حساب‌های سالن |
| کاتالوگ | lines، services، line_services؛ قیمت و مدت روی عرضهٔ خدمت در لاین قرار می‌گیرند |
| کارکنان | employee_profiles، employee_lines، employee_services؛ صلاحیت ارائهٔ خدمت به عضویت در لاین و عرضهٔ همان خدمت متصل است |
| زمان‌بندی | calendars، weekly_periods، day_overrides، special_periods، schedule_blocks؛ برنامهٔ هفتگی، استراحت، روز ویژه، مرخصی و مسدودی |
| رزرو | appointments، appointment_items، appointment_history، idempotency_records؛ یک نوبت با چند قلم خدمت و Snapshot مستقل |
| پرداخت | payment_accounts، payment_intents، payment_attempts، payment_transactions، payment_allocations، refunds، callback_events |
| اسناد مالی | invoices، invoice_items، receipts، credit_notes، financial_entries؛ فاکتور، رسید دریافت، سند برگشت و گردش نقدی |
| عملیات | audit_logs، platform_audit_logs، notifications، outbox_events، background_jobs |

نام‌های مفهومی مرحلهٔ ۱ به این صورت نهایی شدند: Break در weekly_periods با kind=BREAK، Holiday کامل در day_overrides و تعطیلی/مرخصی بازه‌ای در schedule_blocks ذخیره می‌شوند. Email Verification و Password Reset یک جدول auth_tokens با purpose متمایز دارند. Occupancy در Appointment ادغام شده است. این ادغام‌ها دامنهٔ قابلیت را کم نمی‌کنند و از چند منبع حقیقت جلوگیری می‌کنند.

## جداسازی سالن و محدودهٔ اعتماد

تمام ۴۲ جدول متعلق به سالن و خود salons دارای ENABLE RLS و FORCE RLS هستند. سیاست هم برای خواندن و هم برای نوشتن، شناسهٔ رکورد را با app.tenant_id مقایسه می‌کند. مقدار زمینه باید در تراکنش جاری تنظیم شود و پس از Commit یا Rollback باقی نمی‌ماند. این رفتار روی اتصال بازاستفاده‌شده آزمایش شده است.

نقش salonbook_runtime یک گروه NOLOGIN و بدون Superuser، BYPASSRLS، CREATE ROLE و CREATE DATABASE است. برنامه در مرحلهٔ ۳ با Login جدا عضو این گروه می‌شود. نقش migration مستقل است و آزمون‌ها حتی FORCE RLS برای مالک غیرSuperuser جدول را بررسی می‌کنند.

استثنای آگاهانه، registry دامنه است: tenant_domains فقط در Control plane قابل خواندن/نوشتن است. برنامه تنها View با نام tenant_hostnames را می‌خواند که hostname فعال و تأییدشده و UUID سالن را برمی‌گرداند؛ این اطلاعات برای تعیین Tenant پیش از احراز هویت لازم است. هیچ اطلاعات مشتری، رمز، تنظیمات خصوصی یا نشست در View وجود ندارد. جدول permissions نیز کاتالوگ عمومی قابلیت‌ها و برای برنامه فقط خواندنی است.

FK مرکب جلوی ارجاع بین دو سالن را مستقل از فیلتر Query می‌گیرد. Trigger هویت، جابه‌جایی tenant_id یا id رکورد موجود را ممنوع می‌کند. RLS جایگزین مجوز مالکیت مشتری یا لاین نیست؛ این کنترل‌ها در Serviceهای مراحل ۴ و ۵ اعمال می‌شوند. همچنین کسی که Credential مورد اعتماد Backend را به دست آورد می‌تواند زمینهٔ Tenant را تغییر دهد؛ RLS جایگزین حفاظت Credential و SQL injection نیست.

این انتخاب با رفتار مستند مالک جدول، BYPASSRLS و کنترل نوشتن در PostgreSQL هماهنگ است. [مستند CREATE POLICY](https://www.postgresql.org/docs/current/sql-createpolicy.html)

## نوبت، بازهٔ اشغال و قرارداد هم‌زمانی

Appointment زمان شروع/پایان خدمت، Buffer قبل/بعد، زمان شروع/پایان اشغال، وضعیت، مهلت Hold، مبلغ و نسخهٔ سیاست را دارد. occupied_period ستون محاسبه‌شدهٔ دیتابیس از نوع tstzrange و نیمه‌باز [start,end) است؛ Client نمی‌تواند Range ناسازگار دیگری در آن بنویسد.

CHECKها مثبت‌بودن مدت، سازگاری پایان با Duration، سازگاری Buffer با بازهٔ اشغال و اطلاعات لازم Hold/Confirmation را کنترل می‌کنند. قید GiST Exclusion تداخل tenant_id + employee_id + occupied_period را در وضعیت‌های AWAITING_PAYMENT، CONFIRMED، COMPLETED و NO_SHOW ممنوع می‌کند. لاین جزء کلید تداخل نیست؛ متخصص مشترک بین دو لاین نیز نمی‌تواند هم‌زمان دو نوبت بگیرد. [پشتیبانی ExcludeConstraint در SQLAlchemy](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#sqlalchemy.dialects.postgresql.ExcludeConstraint)

یک Index یکتای شرطی، حداکثر یک Hold فعال برای هر مشتری در سالن را اعمال می‌کند. عبور ساعت به‌تنهایی Hold را از Index حذف نمی‌کند؛ Worker یا مسیر ثبت نوبت باید وضعیت Hold منقضی را EXPIRED کند. این رفتار صریحاً آزمون شده است.

در آزمایش رقابت بدون قفل هماهنگ، Exclusion از Double Booking جلوگیری کرد اما برخی تراکنش‌ها deadlock شدند. قرارداد نهایی برای پیاده‌سازی مرحلهٔ ۸ عبارت است از: قفل اشتراکی کنترل تقویم، قفل مشتری، قفل متخصصان به ترتیب ثابت، سپس نوبت و پرداخت. آزمون ۵۰ درخواست با همین قرارداد در PostgreSQL، یک موفقیت و ۴۹ رد تداخل داشته است. Service نهایی باید deadlock/serialization failure را نیز با retry محدود و idempotency مدیریت کند.

جابه‌جایی با UPDATE اتمیک بازه انجام‌پذیر است؛ اگر مقصد پر باشد، Rollback زمان قبلی را حفظ می‌کند. Snapshot هر قلم، original_employee_id و نام/قیمت/مدت زمان رزرو را نگه می‌دارد. متخصص فعلی در Appointment است؛ تغییر متخصص مجاز، Snapshot تجاری و فاکتور قبلی را تغییر نمی‌دهد. گزارش «به تفکیک متخصص هنگام فروش» از Snapshot و عملکرد اجرای نوبت از متخصص تخصیص‌یافته و تاریخچه استفاده خواهد کرد.

## Schema زمان‌بندی

Calendar چهار Scope دارد: SALON، LINE، EMPLOYEE و EMPLOYEE_LINE. CHECK شکل هدف را کنترل می‌کند؛ مثلاً Calendar سالن نباید employee_id داشته باشد. قید NULLS NOT DISTINCT از ساخت دو Calendar یکسان با مقادیر NULL جلوگیری می‌کند.

WeeklyPeriod روز هفته را با ISO، یعنی ۰=دوشنبه تا ۶=یکشنبه، و دقیقه از ابتدای روز محلی ذخیره می‌کند. بازهٔ معتبر دقیقه ۰ تا ۱۴۴۰ است؛ شیفت عبوری از نیمه‌شب به دو روز تقسیم می‌شود. تاریخ شروع اعتبار شامل و تاریخ پایان اعتبار خارج از بازه است. OPEN و BREAK از هم متمایزند.

DayOverride برای هر Calendar و تاریخ فقط یکی است: CLOSED یا REPLACE. SpecialPeriod فقط به REPLACE متصل می‌شود؛ FK اجازه نمی‌دهد یک روز CLOSED هم‌زمان ساعت باز داشته باشد. ScheduleBlock لحظه‌های دقیق، نوع مرخصی/تعطیلی/مسدودی و وضعیت درخواست یا تأیید را ثبت می‌کند. الگوریتم اشتراک تقویم‌ها و کنترل برخورد تغییر برنامه با نوبت‌ها مربوط به مرحلهٔ ۷ است.

## Schema پرداخت و مالی

PaymentIntent مبلغ مورد انتظار همان Appointment را با FK مرکب مبلغ/ارز/محیط کنترل می‌کند. PaymentAttempt نیز مبلغ مورد انتظار و حساب پذیرندهٔ درست را حمل می‌کند. Index شرطی مانع دو تلاش باز برای یک Intent می‌شود؛ حتی اگر درخواست‌ها کلیدهای متفاوت داشته باشند.

PaymentTransaction یک دریافت واقعیِ بررسی‌شده است. مرجع درگاه در محدودهٔ حساب پذیرنده یکتا است. در این نسخه، یک حساب پذیرنده با Provider، merchant_reference و محیط مشخص فقط به یک سالن متصل می‌شود. secret_ref صرفاً نشانی Secret خارج از دیتابیس است، نه API Key.

دریافت واقعی دوم یا دریافت با مبلغ نامنطبق قابل ثبت است تا واقعیت مالی گم نشود. **تخصیص آن به سفارش** در PaymentAllocation تنها وقتی ممکن است که هم مبلغ سفارش و هم مبلغ دریافت و ارز/محیط منطبق باشند؛ برای هر Intent تنها یک Allocation مجاز است. مبلغ نامنطبق به بررسی و Refund نیاز دارد و موجب تأیید نوبت نمی‌شود.

Refund به دریافت منبع متصل است و هر مبلغ مثبت نباید از دریافت منبع بیشتر باشد. کلید درخواست یکتا و زمان موفقیت برای وضعیت SUCCEEDED اجباری است. Receipt برای هر دریافت واقعی یکتا است. Invoice برای هر Appointment حداکثر یکی است؛ CreditNote به Refund متصل می‌شود و Invoice مرتبط از زنجیرهٔ پرداخت/نوبت قابل یافتن است.

FinancialEntry مبلغ مثبت با نوع CAPTURE یا REFUND دارد؛ علامت جمع گزارش از نوع تعیین می‌شود. این انتخاب، توضیح مفهومی مبلغ منفی مرحلهٔ ۱ را به نمایش صریح نوع و مقدار تبدیل می‌کند. مبلغ CAPTURE باید عین مبلغ دریافت باشد و مبلغ Refund به سند Refund متصل است. رویداد منبع نمی‌تواند دوبار در دفتر گردش ثبت شود. تمام زنجیره، is_test را حمل می‌کند؛ حساب Mock نمی‌تواند واقعی علامت‌گذاری شود.

**مواردی که CHECK تک‌ردیفی تضمین نمی‌کند:** مجموع Refundهای موفق و در حال اجرا، جمع اقلام فاکتور، جمع اقلام نوبت، اعتبار نتیجهٔ Verify، تطبیق زمان با برنامهٔ کاری و انتقال‌های مجاز وضعیت. این قواعد در Serviceهای تراکنشی مراحل ۷، ۸ و ۹ با قفل و آزمون جدا اجرا می‌شوند؛ مدل فعلی آمادگی آن‌ها را دارد و وجود Schema به معنی پیاده‌سازی این فرایندها نیست. [محدودهٔ کاربرد Constraintهای PostgreSQL](https://www.postgresql.org/docs/current/ddl-constraints.html)

## Index و حذف داده

علاوه بر PK و UNIQUE، Indexهای مسیرهای پرتکرار عبارت‌اند از: نوبت به تفکیک لاین/مشتری و زمان، Holdهای در انتظار انقضا، پرداخت‌های نیازمند استعلام، گردش مالی بر اساس محیط و تاریخ، Audit بر اساس Actor/Entity، اعلان خوانده‌نشده و Job موعدرسیده یا lease منقضی. FK بدون پوشش مناسب، Index قطعی دریافت می‌کند؛ Index هم‌پوشان با ابتدای PK/UNIQUE دوباره ساخته نمی‌شود.

Soft Delete برای users، employee_profiles، lines، services، line_services، employee_lines، employee_services و roles وجود دارد. کلیدهای تجاری و ایمیل حتی پس از حذف نرم قابل تصاحب مجدد نیستند؛ تاریخچه و پیوندهای قبلی حفظ می‌شوند. Serviceهای مراحل بعد باید deleted_at و is_active را در عملیات جدید بررسی کنند؛ RLS به‌عمد رکورد حذف‌شده را از گزارش تاریخی پنهان نمی‌کند.

تمام FKها ON DELETE RESTRICT دارند. Appointments و اسناد مالی DELETE عمومی ندارند. جدول‌های الحاقی مانند Audit، Snapshot اقلام، دریافت وجه و اسناد مالی علاوه بر Grant، Trigger منع UPDATE/DELETE دارند. پاک‌سازی دادهٔ موقت و نگهداری تاریخچه، با Job دارای سیاست Retention جدا انجام خواهد شد. این حفاظت در برابر تغییر عادی SQL است؛ DBA می‌تواند Trigger را غیرفعال کند و جایگزین Backup یا Audit خارج از میزبان نیست.

## ساختار فایل و علت محل قرارگیری

| مسیر | مسئولیت |
|---|---|
| backend/app/db/base.py | Base، زمان‌ها، TenantRecord، FK مرکب و قرارداد نام‌گذاری |
| backend/app/db/enums.py | وضعیت‌های ذخیره‌شده، بدون منطق انتقال وضعیت |
| backend/app/db/models.py | ثبت همهٔ مدل‌ها در یک Metadata و پوشش Index FKها |
| backend/app/modules/*/models.py | دادهٔ متعلق به همان حوزه؛ از یک فایل مدل بزرگ جلوگیری می‌کند |
| backend/alembic/env.py | گرفتن URL از محیط و اجرای migration آنلاین/آفلاین |
| backend/alembic/versions/0001_* | DDL صریح جدول‌ها، FKها، Indexها و Exclusion |
| backend/alembic/versions/0002_* | RLS، View عمومی محدود، Triggerهای هویت، زمان و اسناد |
| backend/sql/runtime_grants.sql | گروه دسترسی برنامه بدون Password یا مالکیت جدول |
| backend/tests/ | آزمون واقعی Schema، امنیت و هم‌زمانی |
| backend/scripts/postgres_lab.py | دیتابیس موقت تست با پورت محلی و Credential تصادفی |
| backend/scripts/export_schema_docs.py | خروجی قابل بازبینی SQL، ERD و فرهنگ داده |
| backend/uv.lock | نسخهٔ دقیق وابستگی‌ها برای اجرای تکرارپذیر |

migrationها مدل زنده را import نمی‌کنند و create_all ندارند؛ تغییر مدل آینده نباید تاریخچهٔ migration قدیمی را تغییر دهد. فهرست جدول‌های RLS در migration ثابت است. Alembic autogenerate جایگزین بازبینی RLS، Trigger، CHECK و تغییر Exclusion نیست. [مستند Autogenerate در Alembic](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

## اجرای مرحله

از PowerShell، برای آماده‌سازی محیط و آزمون دیتابیس موقت:

```powershell
cd G:\Projects\SalonBook\backend
uv sync --frozen --python 3.13
uv run --no-sync python -m pytest -q
```

Docker Desktop باید فعال باشد. آزمون‌ها Container اختصاصی PostgreSQL با نام تصادفی، پورت فقط روی 127.0.0.1 و Credential موقت می‌سازند و در پایان متوقف می‌کنند. Volume دائمی یا دیتابیس موجود شما استفاده نمی‌شود. اولین اجرا ممکن است Image را دانلود کند. اگر فرایند آزمون با قطع اجباری سیستم متوقف شود، Container دارای برچسب salonbook.purpose=stage02-tests برای تشخیص باقی‌مانده است؛ حذف منابع نامرتبط انجام نمی‌شود.

بررسی کیفیت و اسناد:

```powershell
uv run --no-sync python -m ruff check app scripts alembic tests
uv run --no-sync python -m ruff format --check app scripts alembic tests
uv run --no-sync python -m mypy app scripts alembic/env.py tests
uv run --no-sync python -m scripts.export_schema_docs --check
```

برای اجرای migration روی یک دیتابیس خالی که خودتان برای پروژه ایجاد کرده‌اید:

```powershell
$env:DATABASE_MIGRATION_URL = 'postgresql+psycopg://OWNER:PASSWORD@HOST:5432/salonbook'
uv run --no-sync python -m alembic upgrade head
uv run --no-sync python -m alembic current
uv run --no-sync python -m alembic check
```

عبارت URL بالا الگو است؛ مقادیر واقعی باید خارج از Git و با نقش migration وارد شوند. ابزار Alembic عمداً فایل .env را خودکار بارگذاری نمی‌کند. مدیر دیتابیس سپس sql/runtime_grants.sql را اجرا و Login جداگانهٔ برنامه را عضو salonbook_runtime می‌کند. مدیریت اتصال برنامه و تنظیمات Runtime در مرحلهٔ ۳ ساخته می‌شود.

در این دستگاه نصب اولیهٔ uv هنگام ساخت Launcher ویندوز با خطای دسترسی مواجه شد. همان نسخه‌های uv.lock با pip در همان محیط مجازی نصب شدند. راه جایگزین در صورت تکرار همان خطا:

```powershell
.\.venv\Scripts\python.exe -m ensurepip
uv export --frozen --no-hashes --no-emit-project --output-file "$env:TEMP\salonbook-requirements.txt"
.\.venv\Scripts\python.exe -m pip install -r "$env:TEMP\salonbook-requirements.txt"
.\.venv\Scripts\python.exe -m pytest -q
```

برای اجرای سریع آزمون‌های بدون دیتابیس می‌توان pytest -m 'not postgres' را اجرا کرد؛ این گزینه اثبات جداسازی، migration یا هم‌زمانی نیست.

## معیار Done و محدودیت تحویل

- مدل‌ها، روابط، Constraintها، Indexها و سیاست حذف مستند و قابل تولید مجدد هستند.
- migration از دیتابیس خالی اعمال، به base بازگردانده و دوباره بدون اختلاف Schema اجرا می‌شود.
- RLS با Login غیرمدیر، فقدان زمینهٔ Tenant و بازاستفادهٔ اتصال آزمایش می‌شود.
- FK بین‌سالنی، تداخل متخصص میان لاین‌ها، Buffer و هم‌زمانی ۵۰ درخواست بررسی می‌شوند.
- مبلغ سفارش، دریافت تکراری، تخصیص یکتا، اسناد تغییرناپذیر و تفکیک پرداخت آزمایشی آزمون دارند.
- Lint و Type Check و آزمون‌ها باید در گزارش نهایی موفق باشند.

این مرحله API، Login عملیاتی، Scheduling Engine، Payment Provider یا داشبورد ارائه نمی‌کند؛ این قابلیت‌ها دقیقاً به مراحل تأییدشدهٔ بعد تعلق دارند. تأیید مرحلهٔ ۲ مجوز آغاز مرحلهٔ ۳، یعنی Backend قابل اجرا با FastAPI، خواهد بود.
