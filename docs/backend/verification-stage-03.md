# گزارش بررسی مرحلهٔ ۳

تاریخ: ۲۰۲۶-۱۰-۰۱. محیط اجرا: Windows، Python 3.13.5 و PostgreSQL 18 موقت روی Docker. هیچ دیتابیس موجود کاربر برای آزمون یا migration استفاده نشد.

## نتیجهٔ خودکار

| بررسی | نتیجهٔ مشاهده‌شده |
|---|---|
| pytest، کل پروژه | 126 passed in 17.28s؛ بدون خطا، skip یا هشدار |
| Ruff check | All checks passed |
| Ruff format --check | 66 files already formatted |
| mypy strict روی app/scripts/tests/alembic | Success: no issues found in 65 source files |
| export_schema_docs --check | فرهنگ داده، ERD کامل و SQL Schema مطابق خروجی تولیدشده |
| migration head | 0003؛ ثابت مورد انتظار برنامه با head مقایسه شد |

## رفتارهای بررسی‌شده

- آزمون‌های ۸۳گانهٔ مرحلهٔ ۲ شامل FK و قیود مالی، تراکنش‌های هم‌زمان، RLS، Grantها و چرخهٔ migration همچنان موفق‌اند.
- ۱۹ حالت تنظیمات: اتصال PostgreSQL معتبر، پنهان‌ماندن رمز، بارگذاری متغیر محیط، Host/CORS محدود و سازگاری timeoutها.
- ۱۱ آزمون HTTP: سلامت، OpenAPI، خطاهای ۴۰۴/۴۰۵/۴۰۹/۴۲۲/۵۰۰/۵۰۳، Request ID، CORS، Host، سرآیندها، لاگ فاقد اطلاعات حساس و خاموش‌بودن Docs در production.
- ۱۳ حالت دیتابیس برنامه: حساب runtime معتبر، رد owner و superuser، نسخهٔ غلط، FORCE RLS غیرفعال، مجوز محدود View نسخه، commit/rollback، تراکنش read-only، جلوگیری از نوشتن برای سالن دیگر، بازیافت اتصال بدون نشت Tenant و توقف startup نامعتبر.
- آزمون واقعی commit: درج دارای slug تکراری تا commit نگه داشته شد؛ HTTP پاسخ ۴۰۹ داد و پاسخ موفق ارسال نشد.
- رمز اشتباه اتصال به خطای عمومی database_unavailable تبدیل شد. پایان ناموفق startup هم Pool را آزاد کرد.
- کنترل‌های نسخه و RLS که برای آزمون تغییر کردند با finally بازیابی شدند؛ محیط تست پس از اجرا متوقف و حذف شد.

## اجرای واقعی HTTP

Backend با `python -m scripts.dev --port 8000` اجرا شد. ساعت مشاهدهٔ startup برابر ۱۰:۴۹ UTC در تاریخ بالا بود. رمزهای موقت فقط در حافظه نگهداری شدند؛ Runtime از حساب محدود مجزا استفاده کرد.

| درخواست روی http://127.0.0.1:8000 | پاسخ |
|---|---|
| /api/v1/health/live | 200، application/json، status=ok و service=salonbook-api |
| /api/v1/health/ready | 200، application/json، status=ready |
| /api/v1/openapi.json | 200، application/json |
| /api/v1/docs | 200، text/html |

هر چهار پاسخ Request ID مستقل داشتند. این بررسی از طریق HTTP واقعی انجام شد، علاوه بر آزمون‌های درون‌پردازهٔ TestClient. فعال‌بودن این پیش‌نمایش وابسته به روشن‌ماندن process و Docker است؛ فرمان اجرای مجدد در [راهنمای مرحلهٔ ۳](../architecture/stage-03.md) آمده است.

## نسخه‌های ثبت‌شده در lockfile

FastAPI 0.142.2، Starlette 1.7.0، Uvicorn 0.54.0، Pydantic 2.13.5، Pydantic Settings 2.15.0، SQLAlchemy 2.0.54، Alembic 1.20.0، Psycopg 3.3.6 و HTTPX2 2.13.1.

این گزارش اثبات تکمیل زیرساخت مرحلهٔ ۳ است. تست امنیت Authentication، Authorization، CSRF، محدودسازی درخواست، عملیات تجاری و آماده‌سازی استقرار به مراحل مربوط تعلق دارند.
