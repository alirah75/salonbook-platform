# مرحلهٔ ۳ از ۱۵ — Backend Foundation

زیرساخت FastAPI ساخته و روی PostgreSQL واقعی اجرا شد. این مرحله پیکربندی، اتصال دیتابیس، مرز تراکنش، Pydantic، لاگ، خطاها، نسخه‌بندی API و Health Check را پوشش می‌دهد. مبنا، معماری تأییدشدهٔ مرحلهٔ ۱ و مدل دادهٔ مرحلهٔ ۲ است.

وضعیت: **مرحلهٔ ۳ تکمیل و ورود به مرحلهٔ ۴ توسط کاربر تأیید شد**. نتیجهٔ تاریخی تحویل این مرحله: ۱۲۶ آزمون موفق، بدون هشدار؛ بررسی نوع‌ها، قالب‌بندی، Lint و تطابق اسناد Schema موفق. نتیجهٔ اجرای واقعی و جزئیات آزمون‌ها در [گزارش بررسی](../backend/verification-stage-03.md) ثبت شده است. [تغییرات جدید مرحلهٔ ۴](stage-04.md) شامل نسخهٔ جدید Schema و تنظیمات احراز هویت است.

## چرا این ساختار؟

برنامه یک Modular Monolith است. Router قرارداد HTTP را نگه می‌دارد، Service رفتار کاربرد را اجرا می‌کند و Database مرز تراکنش و اتصال را مدیریت می‌کند. این تفکیک اجازه می‌دهد Authentication، Scheduling و Payment در مراحل بعد اضافه شوند، بدون اینکه تصمیم‌های تجاری داخل Routerها پخش شوند.

| مسیر در backend | مسئولیت و دلیل محل قرارگیری |
|---|---|
| app/main.py | ساخت برنامه و lifecycle؛ import کردن ماژول اتصال شبکه ایجاد نمی‌کند |
| app/core/config.py | تنظیمات نوع‌دار و معتبر؛ خطای محیط پیش از پذیرش درخواست مشخص می‌شود |
| app/core/logging.py | خروجی JSON و شناسهٔ درخواست؛ اطلاعات محرمانه در متن لاگ کپی نمی‌شود |
| app/core/errors.py | قرارداد مشترک خطا و نگاشت خطاهای Service/HTTP/SQLAlchemy |
| app/core/middleware.py | شناسهٔ درخواست، سرآیندهای پاسخ و مرز خطای غیرمنتظره |
| app/core/runtime.py | وابستگی‌های همان نمونهٔ برنامه؛ قابل جایگزینی در آزمون |
| app/db/database.py | Pool، Session و تراکنش متعلق به سالن |
| app/db/schema.py | نسخهٔ Schema مورد انتظار این نسخهٔ برنامه |
| app/dependencies/runtime.py | دریافت وابستگی نوع‌دار از برنامه، بدون متغیر عمومی دیتابیس |
| app/api/v1/router.py | نقطهٔ اتصال ماژول‌ها به نسخهٔ اول API |
| app/modules/health | Router نازک، Service سلامت و مدل‌های پاسخ Pydantic |
| app/modules/*/models.py | مدل‌های دامنهٔ مرحلهٔ ۲؛ بدون تغییر قواعد تجاری در این مرحله |
| alembic/versions/0003_readonly_schema_revision.py | مشاهدهٔ محدود نسخهٔ migration توسط اتصال برنامه |
| scripts/serve.py | اجرای برنامه با تنظیمات واقعی از محیط یا فایل مشخص‌شده |
| scripts/dev.py | پیش‌نمایش محلی با PostgreSQL موقت و رمزهای درون حافظه |
| tests/test_configuration.py | اعتبارسنجی تنظیمات و جلوگیری از نمایش رمز |
| tests/test_api_foundation.py | رفتار HTTP، خطا، لاگ، CORS و محیط production |
| tests/test_database_foundation.py | تراکنش، بازیافت اتصال، کنترل نقش و نسخه و fail-fast |

ساخت برنامه با `create_app()` انجام می‌شود. منابع در lifespan بررسی و در پایان آزاد می‌شوند؛ این محل با الگوی رسمی [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) سازگار است. اجرای تست می‌تواند تنظیمات و Database مخصوص خود را به factory بدهد.

## انتخاب اتصال همگام

SQLAlchemy 2 و Psycopg 3 در این مرحله همگام هستند. Endpointهایی که دیتابیس را صدا می‌زنند با `def` تعریف شده‌اند تا FastAPI آن‌ها را در thread pool اجرا کند؛ بررسی آغاز برنامه نیز از event loop به thread pool منتقل می‌شود. ترکیب تصادفی عملیات مسدودکننده با `async def` باعث توقف رسیدگی به درخواست‌های دیگر خواهد شد.

Pool هر process به‌طور پیش‌فرض ۵ اتصال ثابت و حداکثر ۵ اتصال اضافه دارد. انتظار Pool سه ثانیه است؛ اتصال خراب پیش از استفاده بررسی می‌شود. زمان انتظار قفل ۲ ثانیه، هر statement حداکثر ۵ ثانیه و نشست رهاشده داخل تراکنش ۱۵ ثانیه است. این اعداد تنظیمات عملیاتی‌اند و از محیط تغییر می‌کنند. زمان statement سقف کل درخواست نیست؛ برای deadline کل درخواست در مرحلهٔ استقرار تنظیم جدا لازم است.

افزایش workerها تعداد اتصال‌های کل را هم افزایش می‌دهد. مثلاً چهار process با تنظیم پیش‌فرض تا ۴۰ اتصال می‌خواهند؛ ظرفیت PostgreSQL باید هم‌زمان با ظرفیت وب تنظیم شود. این مرحله سرور تک‌پردازهٔ محلی دارد؛ سیاست worker، reverse proxy و ظرفیت نهایی در مرحلهٔ ۱۵ تعیین می‌شود.

## مرز تراکنش متعلق به Service

هر Service از `Database.transaction(resolved_tenant_id)` استفاده می‌کند. شناسه باید UUID حل‌شده از مسیر معتبر باشد؛ تبدیل رشتهٔ دلخواه یا اعتماد به Header مرورگر در این لایه انجام نمی‌شود. ابتدا پیش‌نیازهای اتصال کنترل می‌شوند، سپس `app.tenant_id` فقط برای تراکنش جاری تنظیم می‌شود.

در خروج موفق از بلوک، commit کامل می‌شود؛ در هر خطا rollback و بستن Session انجام می‌شود. `autobegin=False` از شروع ضمنی تراکنش خارج از قرارداد جلوگیری می‌کند. Repositoryهای آینده مجاز نیستند commit کنند یا زمینهٔ سالن را عوض کنند. این قرارداد بر [مدیریت تراکنش SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html) بنا شده است.

این مرز داخل Service قرار دارد تا **خطای commit پیش از پاسخ موفق HTTP رخ دهد**. اگر ثبت داده را به پاک‌سازی یک dependency پس از ارسال پاسخ بسپاریم، کاربر ممکن است پاسخ موفق بگیرد درحالی‌که داده ذخیره نشده است. آزمون واقعی این مرحله دو رکورد ناسازگار را تا commit نگه می‌دارد و پاسخ ۴۰۹ و rollback را بررسی می‌کند.

برای خواندن از `read_only=True` استفاده می‌شود؛ تلاش برای نوشتن در آن تراکنش را خود PostgreSQL رد می‌کند. زمینهٔ سالن با `SET LOCAL` معادل `set_config(..., true)` است، بنابراین با بازگشت اتصال به Pool باقی نمی‌ماند. آزمون سه تراکنش متوالی با دو سالن و همان اتصال فیزیکی این رفتار را بررسی می‌کند.

RLS صرفاً جداسازی سالن را اعمال می‌کند. تشخیص کاربر، مجوز نقش، محدودیت Line و مالکیت رکورد، مسئولیت مراحل ۴ و ۵ است؛ UUID معتبر به‌تنهایی مجوز دسترسی نیست.

## کنترل آماده‌بودن دیتابیس

Startup و پیش از تراکنش Service این موارد بررسی می‌شوند:

1. اتصال برنامه عضو نقش superuser، bypass RLS، سازندهٔ role یا database نباشد.
2. مالک اشیای برنامه یا عضو نقش مالک نباشد و مجوز ساخت شیء در public نداشته باشد.
3. نسخهٔ Schema دقیقاً `0003` باشد.
4. همهٔ ۴۳ جدول متعلق به سالن، RLS و FORCE RLS فعال داشته باشند.

کنترل عضویت از توابع اطلاعات دسترسی PostgreSQL استفاده می‌کند؛ [مرجع رسمی](https://www.postgresql.org/docs/current/functions-info.html). بررسی عضویت باعث می‌شود فقط پرچم حساب مستقیم معیار نباشد. این کنترل، بررسی کامل همهٔ Grantها یا درستی متن Policyها نیست؛ آزمون‌های Schema آن موارد را جداگانه بررسی می‌کنند.

این بررسی‌ها چند query کوتاه روی catalog اجرا می‌کنند. در این مرحله بررسی ابتدای هر تراکنش انتخاب شده تا تغییر اشتباه مجوزها یا RLS بعد از startup نیز تشخیص داده شود. بهینه‌سازی یا cache کردن آن باید همراه با سنجش هزینه و حفظ همین ضمانت انجام شود.

برنامه با حساب migration اجرا نمی‌شود و migration خودکار در startup ندارد. برای مشاهدهٔ نسخه، migration جدید `0003` یک View به نام `app_schema_revision` ایجاد می‌کند و فقط SELECT آن را به گروه runtime می‌دهد. اتصال برنامه همچنان به جدول `alembic_version` دسترسی ندارد. دو migration قبلی دست‌نخورده‌اند و تعداد جداول تجاری همان ۵۱ است.

## تنظیمات محیط

پیشوند تنظیمات برنامه `SALONBOOK_` است. Pydantic Settings مقدارها را می‌خواند و نوع، محدوده و سازگاری آن‌ها را بررسی می‌کند؛ [مرجع رسمی تنظیمات](https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/). فایل `.env` خودکار بارگذاری نمی‌شود؛ فقط با `--env-file` مسیر آن صریحاً انتخاب می‌شود. متغیر محیط بر مقدار همان کلید در فایل اولویت دارد.

نمونهٔ بدون رمز در [backend/.env.example](../../backend/.env.example) قرار دارد:

| متغیر | کاربرد / پیش‌فرض |
|---|---|
| SALONBOOK_DATABASE_URL | الزامی؛ آدرس postgresql+psycopg مربوط به حساب runtime |
| DATABASE_MIGRATION_URL | فقط Alembic؛ حساب مالک مجزا؛ برنامه آن را مصرف نمی‌کند |
| SALONBOOK_ENVIRONMENT | development، test یا production؛ پیش‌فرض development |
| SALONBOOK_ALLOWED_HOSTS | آرایهٔ JSON؛ پیش‌فرض localhost و 127.0.0.1؛ بدون scheme و port |
| SALONBOOK_CORS_ORIGINS | آرایهٔ JSON از originهای دقیق؛ پیش‌فرض خالی |
| SALONBOOK_DOCS_ENABLED | در توسعه پیش‌فرض true؛ در production فعال‌کردن رد می‌شود |
| SALONBOOK_LOG_LEVEL | INFO؛ مقادیر DEBUG، WARNING و ERROR نیز معتبرند |
| SALONBOOK_DB_POOL_SIZE / DB_MAX_OVERFLOW | ۵ / ۵؛ پیشوند SALONBOOK_ برای هر دو کلید |
| SALONBOOK_DB_POOL_TIMEOUT_SECONDS | ۳ |
| SALONBOOK_DB_POOL_RECYCLE_SECONDS | ۹۰۰ |
| SALONBOOK_DB_CONNECT_TIMEOUT_SECONDS | ۳ |
| SALONBOOK_DB_STATEMENT_TIMEOUT_MS | ۵۰۰۰ |
| SALONBOOK_DB_LOCK_TIMEOUT_MS | ۲۰۰۰؛ کمتر از statement timeout |
| SALONBOOK_DB_IDLE_TRANSACTION_TIMEOUT_MS | ۱۵۰۰۰؛ بیشتر از statement timeout |

در production میزبان‌ها باید صریح تعیین شوند و CORS فقط HTTPS را می‌پذیرد. Wildcard سراسری Host یا CORS مجاز نیست. الگوی دامنهٔ مشخص مانند `*.salon.example` قابل استفاده است؛ محدودیت واقعی دامنه‌های هر سالن در resolver مرحلهٔ ۵ اعمال می‌شود. CORS جای احراز هویت یا CSRF را نمی‌گیرد.

رمز اتصال در `SecretStr` نگهداری و از نمایش تنظیمات حذف می‌شود؛ پیام اعتبارسنجی تنظیمات ورودی خام را چاپ نمی‌کند. فایل واقعی `.env` در `.gitignore` است. تنظیم URL و Pool در لاگ چاپ نمی‌شود و SQL echo خاموش است.

## قرارداد HTTP و خطا

| مسیر | رفتار |
|---|---|
| GET /api/v1/health/live | پاسخ ۲۰۰، زنده‌بودن برنامه؛ بدون query دیتابیس |
| GET /api/v1/health/ready | پاسخ ۲۰۰ پس از کنترل دیتابیس؛ در اختلال پاسخ عمومی ۵۰۳ |
| GET /api/v1/docs | مستندات تعاملی در توسعه |
| GET /api/v1/openapi.json | قرارداد OpenAPI در توسعه |

اختلال دیتابیس بعد از startup، readiness را ناموفق می‌کند ولی liveness را پایین نمی‌آورد؛ مانیتور می‌تواند اختلال وابستگی را از توقف process تشخیص دهد. اگر پیش‌نیازها از ابتدا نامعتبر باشند برنامه شروع نمی‌شود.

خطاهای برنامه یک ساختار مشترک دارند:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "request_id": "00000000-0000-4000-8000-000000000000",
    "details": [
      {"field": "body.amount", "code": "int_parsing", "message": "Invalid value."}
    ]
  }
}
```

مقدار request_id در این مثال صرفاً نمونه است. در هر درخواست سرور UUID جدید تولید می‌کند و همان مقدار در Header پاسخ و لاگ می‌آید؛ مقدار ورودی کاربر معتبر فرض نمی‌شود. پیام‌های HTTP فعلاً انگلیسی و کدها پایدارند؛ نمایش فارسی در Frontend با کد خطا قابل نگاشت خواهد بود.

| نوع خطا | پاسخ |
|---|---|
| اعتبارسنجی ورودی | ۴۲۲؛ نام فیلد و کد مشکل، بدون مقدار ورودی و متن exception |
| مسیر یا متد نامعتبر | ۴۰۴ / ۴۰۵ با همان قرارداد |
| تعارض قید دیتابیس | ۴۰۹ عمومی؛ بدون SQL، پارامتر یا نام قید |
| نبود اتصال یا پایان مهلت Pool | ۵۰۳ عمومی و Retry-After |
| خطای پیش‌بینی‌شدهٔ Service | AppError با پیام عمومیِ عمدی |
| خطای غیرمنتظره یا پاسخ نامعتبر | ۵۰۰ عمومی؛ جزئیات امن برای بررسی در لاگ |

Exception handlerهای FastAPI برای خطاهای شناخته‌شده ثبت شده‌اند؛ [مرجع رسمی](https://fastapi.tiangolo.com/tutorial/handling-errors/). یک middleware مرز خطاهای غیرمنتظره را قبل از ارسال پاسخ نگه می‌دارد. پاسخ‌های مستقیم middleware مربوط به Host نامعتبر و CORS preflight نامعتبر، خطای پروتکل ساده هستند و envelope بالا را ندارند؛ شناسهٔ درخواست و سرآیندهای ایمنی روی آن‌ها نیز اعمال می‌شود.

اگر پاسخ streaming آغاز شده باشد امکان تبدیل آن به پاسخ JSON جدید وجود ندارد؛ اتصال با خطای عمومی قطع می‌شود و جزئیات داخلی از مسیر خطا عبور نمی‌کند. Endpoint تجاری streaming در این مرحله وجود ندارد.

## لاگ و سرآیندها

لاگ‌ها JSON روی stdout هستند و timestamp به UTC، event، سطح، شناسهٔ درخواست، متد، الگوی Route، وضعیت و مدت را دارند. مسیر واقعی کاربر، Query String، Body، Cookie، Authorization، متن exception و پارامترهای SQL ثبت نمی‌شوند. Stack خطا فقط نام فایل، نام تابع و شمارهٔ خط دارد و متن کد یا متغیرهای محلی را نمی‌نویسد.

این انتخاب از نشت token یا رمز در لاگ خطا جلوگیری می‌کند؛ در مقابل متن آزاد خطای driver در خروجی نیست. رخدادهای readiness یک کد امن مانند `schema_revision_mismatch` دارند تا علت عملیاتی قابل تشخیص باشد. رویدادهای درخواست مثل `request.completed` و `request.failed` برای اتصال گزارش کاربر به trace استفاده می‌شوند. لاگ خام access سرور خاموش است.

پاسخ‌ها `X-Request-ID`، `Cache-Control: no-store`، `X-Content-Type-Options: nosniff`، `X-Frame-Options: DENY` و `Referrer-Policy: no-referrer` دارند. اعتماد به proxy header در runner فعلاً خاموش است؛ تنظیم proxy و HTTPS در مرحلهٔ ۱۵ انجام می‌شود. HSTS برای سرور HTTP محلی فعال نشده است.

## اجرای سریع محلی

پیش‌نیاز: Python 3.13، uv و Docker فعال. از ریشهٔ پروژه:

```powershell
cd backend
uv sync --frozen --python 3.13
uv run --no-sync python -m scripts.dev
```

این فرمان فقط برای پیش‌نمایش است: PostgreSQL 18 با image دارای digest ثابت، پورت تصادفی دیتابیس روی loopback و حساب‌های مستقل ایجاد می‌شود. migrationها و Grantها روی همان دیتابیس تازه اعمال می‌شوند؛ API با حساب runtime محدود و روی `127.0.0.1:8000` اجرا می‌شود. رمزها تصادفی‌اند و فایل تنظیمات واقعی نوشته نمی‌شود.

صفحهٔ [API Docs](http://127.0.0.1:8000/api/v1/docs) و [Readiness](http://127.0.0.1:8000/api/v1/health/ready) را باز کنید. برای پورت دیگر، `--port 8001` بدهید. دارایی‌های رابط Swagger از CDN پیش‌فرض کتابخانه دریافت می‌شوند؛ قرارداد JSON مستقل از آن از مسیر OpenAPI در دسترس است.

برای توقف `Ctrl+C` بزنید. برنامه Pool را می‌بندد و فقط کانتینر با شناسهٔ ساخته‌شده توسط همان اجرا متوقف و حذف می‌شود. این دیتابیس ماندگار نیست. در توقف اجباری process یا قطع سیستم ممکن است cleanup اجرا نشود؛ کانتینرهای پیش‌نمایش label برابر `salonbook.purpose=stage03-preview` دارند و پیش از توقف دستی باید شناسهٔ همان پیش‌نمایش بررسی شود.

## اجرای با دیتابیس ماندگار

این مسیر از دیتابیس ازپیش‌آماده استفاده می‌کند. حساب migration و runtime را طبق [قرارداد migration](../../backend/alembic/README.md) جدا بسازید. `salonbook_runtime` یک گروه NOLOGIN است؛ حساب LOGIN محدود جداگانه به آن عضو می‌شود. رمز در فایل نمونه وجود ندارد و باید از محیط یا secret manager واقعی تأمین شود.

پس از تنظیم `DATABASE_MIGRATION_URL` در محیطِ اجرای migration:

```powershell
uv run --no-sync python -m alembic upgrade head
```

مدیر دیتابیس Grantهای [runtime_grants.sql](../../backend/sql/runtime_grants.sql) و عضویت حساب برنامه را اعمال می‌کند. سپس `SALONBOOK_DATABASE_URL` متعلق به runtime و تنظیمات Host/CORS را در محیط اجرای برنامه تنظیم کنید:

```powershell
uv run --no-sync python -m scripts.serve --host 127.0.0.1 --port 8000
```

برای توسعه با فایل محلی مشخص، از `--env-file .env` استفاده کنید. کپی سادهٔ `.env.example` کافی نیست؛ URL خالی باید با اتصال واقعی runtime تکمیل شود. Alembic فایل `.env` را خودکار نمی‌خواند. سرور برنامه هیچ‌گاه حساب migration را انتخاب یا مجوز دیتابیس را اصلاح نمی‌کند.

## آزمون و معیار اتمام

```powershell
uv run --no-sync python -m pytest -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app scripts tests alembic
uv run --no-sync python -m scripts.export_schema_docs --check
```

۱۲۶ آزمون شامل ۸۳ آزمون مرحلهٔ ۲ و ۴۳ آزمون جدید است. PostgreSQL تست با owner و runtime جداگانه اجرا می‌شود؛ SQLite جایگزین نشده است. ارتقا، downgrade و ارتقای مجدد هم فقط روی دیتابیس موقت جدا انجام می‌شود. `httpx2` وابستگی توسعهٔ TestClient متناسب با Starlette نصب‌شده است؛ مسیر اجرای API به آن وابسته نیست. نسخهٔ دقیق همهٔ وابستگی‌ها در `uv.lock` قفل است.

اجرای واقعی روی پورت ۸۰۰۰ چهار پاسخ HTTP ۲۰۰ از liveness، readiness، OpenAPI و Docs داد. **معیار «Backend باید اجرا شود» این مرحله انجام شده است.**

Authentication، RBAC، resolver سالن، API تجاری، frontend و استقرار production در این مرحله پیاده نشده‌اند. کنترل‌های فعلی پایهٔ مراحل بعد هستند؛ ادعای آماده‌بودن محصول کامل برای production نمی‌شود. گام بعدی با تأیید کارفرما، مرحلهٔ ۴: احراز هویت و مجوزهاست.
