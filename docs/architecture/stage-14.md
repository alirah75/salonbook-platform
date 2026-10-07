# مرحلهٔ ۱۴ — سخت‌سازی امنیت و آزمون

بررسی در ۲۰۲۶/۱۰/۰۷ روی کد مراحل ۱ تا ۱۳ انجام شد. این مرحله کنترل‌های برنامه و شواهد آزمون را تکمیل می‌کند؛ راه‌اندازی اینترنتی، TLS و reverse proxy، Docker/CI و backup/restore موضوع مرحلهٔ ۱۵ هستند. این گزارش گواهی امنیت یا تضمین نبود آسیب‌پذیری ناشناخته نیست.

## اصلاح‌های انجام‌شده

| مورد پیدا‌شده | نتیجه |
|---|---|
| سقف بدنه فقط در پل توسعه و API پلتفرم بود | `RequestLimitsMiddleware` مشترک، پیش از پارس JSON در هر دو API: سقف واقعی ۶۴KiB، مهلت خواندن ۱۰ ثانیه، کنترل chunked و Content-Length جعلی/تکراری، سقف query برابر ۸KiB |
| امکان ورود محتوای غیر JSON و بدنهٔ فشرده به مسیرهای فاقد نیاز | بدنهٔ غیرخالی فقط JSON؛ فشرده‌سازی درخواست و multipart رد می‌شوند؛ مسیر بارگذاری فایل وجود ندارد |
| محدودسازی فقط برای ورود و عملیات احراز هویت بود | سهمیهٔ مشترک همهٔ مسیرهای tenant دارای context، ۲۴۰ درخواست در ۶۰ ثانیه برای هر سالن و IP واقعی؛ پلتفرم ۶۰۰ درخواست در دقیقه در کل سرویس، علاوه بر محدودیت ورود قبلی |
| نبود CSP برای HTML | nonce تصادفی ۱۹۲بیتی برای هر درخواست، `strict-dynamic`، ممنوعیت script inline بدون nonce و eval در ساخت Production؛ جلوگیری از embedding و تغییر base و فرم خارجی |
| نبود حفاظت یکسان روی خطاهای پلتفرم | middleware بدنهٔ قبلی با نوع ASGI مشترک جایگزین شد؛ خطاهای ۴۱۳ هم JSON استاندارد، شناسهٔ درخواست و no-store دارند |
| پذیرش HTTP در بخش‌هایی از پلتفرم Production | کل هر دو API در Production اتصال غیر HTTPS را رد می‌کنند؛ HSTS و CSP محدود به داده برای پاسخ‌های Production اضافه شد |
| امکان روشن‌کردن شبیه‌ساز در محیط Production | ترکیب `environment=production` و `mock_payments_enabled=true` در راه‌اندازی رد می‌شود |
| هشدارهای وابستگی رمزنگاری | `cryptography` از 48.0.1 به 50.0.2، با بازهٔ `>=50,<51` و lockfile همگام ارتقا یافت؛ اسکن بعدی بدون مورد شناخته‌شده است |
| خطای تنظیمات پلتفرم | نمایش ورودی‌های تنظیمات در خطای اعتبارسنجی غیرفعال شد |

اندازهٔ واقعی بدنه مستقل از روش HTTP و ادعای Content-Length شمرده می‌شود؛ در نبود Content-Length هم محافظت برقرار است. header طول نامعتبر/تکراری ۴۰۰، عبور از سقف ۴۱۳، محتوای نامجاز ۴۱۵، query بلند ۴۱۴ و خواندن کند ۴۰۸ می‌گیرد. این سقف برای API فعلی کافی است؛ اضافه‌کردن upload در آینده قرارداد جداگانه، محدودیت ذخیره‌سازی و بررسی محتوای فایل می‌خواهد.

## محدودسازی و مرز شبکه

سهمیهٔ API سالن از همان زیرساخت PostgreSQL و جدول RLSدار `auth_throttles` با purpose مستقل `api` استفاده می‌کند. `INSERT ... ON CONFLICT` اتمیک است؛ تغییر مسیر یا اجرای چند worker سهمیه را جدا نمی‌کند. IP در کلید HMAC است و به‌صورت روشن در لاگ ذخیره نمی‌شود. محدودیت‌ها با `SALONBOOK_API_IP_LIMIT` و `SALONBOOK_API_WINDOW_SECONDS` قابل تنظیم‌اند. login همچنان سقف جداگانهٔ حساب و IP دارد؛ پلتفرم سقف ورود کل سرویس و حساب را نگه می‌دارد. پاسخ ۴۲۹، `Retry-After` محافظه‌کارانه متناسب با پنجره دارد.

Health و Host نامعتبر وارد شمارندهٔ tenant نمی‌شوند؛ شمارنده پس از تشخیص سالن اجرا می‌شود. محافظت DDoS، اتصال‌های باز، هدرهای بزرگ و محدودیت پیش از DB باید در مرز شبکهٔ مرحلهٔ ۱۵ هم اعمال شود. اعتماد به `X-Forwarded-*` هنوز خاموش است؛ قبل از انتشار باید proxy مورد اعتماد صریحاً تنظیم شود. اگر همهٔ کاربران از یک proxy دیده شوند، سهمیهٔ IP مشترک خواهد بود. header ارسالی کاربر برای IP، نقش یا tenant پذیرفته نمی‌شود.

## سیاست اجرای صفحه

`frontend/src/proxy.ts` nonce را در سرور می‌سازد و CSP/nonce ارسالی کاربر را بازنویسی می‌کند. Root layout با `connection()` برای هر درخواست render می‌شود؛ HTML دارای nonce نباید static یا CDN-cache شود و پاسخ `private, no-store` است. دارایی‌های ثابت و مسیرهای API از این proxy کنار گذاشته شده‌اند. Next، nonce را به اسکریپت‌های تولیدشده می‌زند.

Production از eval و script inline عمومی استفاده نمی‌کند. در توسعه، eval و اتصال WebSocket صرفاً برای ابزار توسعه مجاز است. style attribute برای نمودارهای React مجاز مانده است؛ این استثنا به script یا event handler تعمیم ندارد. stylesheet و font محلی‌اند. HSTS یک‌ساله بدون `includeSubDomains` یا `preload` است تا همهٔ دامنه‌های سفارشی ناخواسته تحت سیاست دائمی قرار نگیرند. ارائهٔ HTTPS و redirect در مرحلهٔ استقرار تکمیل می‌شود.

## مرور کنترل‌ها و پوشش شواهد

| حوزه | کنترل و آزمون |
|---|---|
| Authentication و Password Security | موبایل+رمز، Argon2id با ۶۴MiB و time cost 3، طول ۱۵ تا ۱۲۸، dummy hash برای حساب ناموجود، حداکثر چهار محاسبهٔ هش هم‌زمان در هر فرایند، نشست تصادفی هش‌شده، انقضای مطلق/بی‌کاری، خروج و ابطال با تغییر رمز/مجوز؛ مجموعه‌های authentication و mobile_identity |
| Authorization / tenant isolation | tenant از Host ثبت‌شده، بررسی فعال‌بودن سالن و مجوز در تراکنش، scope لاین، RLS اجباری و نقش DB محدود؛ مجموعه‌های isolation، tenant_management، platform و finance |
| SQL Injection | ورودی‌ها bind شده‌اند؛ قطعه‌های پویا مثل بعد گزارش فقط از whitelist ثابت می‌آیند؛ نام نقش/جدول از متادیتا یا ابزار آفلاین است. جعل شناسه و scope در آزمون‌ها رد می‌شود |
| XSS | نمایش متن با React، نبود sink از نوع dangerouslySetInnerHTML یا eval در کد محصول، CSP با nonce؛ نام ذخیره‌شدهٔ حاوی img/onerror متن باقی می‌ماند و script تزریقی در HTML واقعی Production مسدود می‌شود |
| CSRF / CORS | Origin دقیق، JSON، token پیش از ورود و token نشست، cookie مخصوص هر سرویس، CORS originهای صریح؛ آزمون فرم Origin خارجی نشست را از بین نمی‌برد و API آن را رد می‌کند |
| Headers / Secrets | nosniff، DENY، no-referrer در API، Permissions-Policy، no-store، CSP/HSTS؛ لاگ allowlist بدون بدنه، header، query و متن exception؛ `.env` و `.local` و فایل‌های اعتبار آزمایشی مستثنا از کنترل نسخه‌اند |
| File Upload | مسیر upload یا ذخیرهٔ فایل کاربر وجود ندارد؛ multipart و payload بزرگ قبل از endpoint رد می‌شوند. اضافه‌کردن upload در آینده نیازمند طراحی مستقل است |
| Audit Logs | رویدادهای مدیر، نوبت، دریافت، بازپرداخت و پلتفرم با عامل و دلیل؛ مدارک مالی append-only؛ آزمون‌های database/financial constraints و management/platform |
| Race Conditions | آزمون ۵۰ مشتری هم‌زمان روی یک ظرفیت: دقیقاً یک رزرو و ۴۹ تعارض؛ کلید یکسان ده درخواست: یک اثر؛ حذف هم‌زمان آخرین مدیر، تعارض برنامه/رزرو و verify هم‌زمان پرداخت پوشش دارند |
| Payment Security | مبلغ/واحد/حساب از snapshot سرور؛ callback غیرمعتبر فقط inquiry را زمان‌بندی می‌کند؛ موفقیت از verify؛ تراکنش/رسید یکتا، حفظ دریافت دیررس، بازپرداخت با رزرو مانده و کلید idempotency؛ mock در Production رد می‌شود |

ایمیل و OTP اضافه نشده‌اند. کاربر بدون شمارهٔ تأییدشده همچنان فقط از روش موبایل+رمزِ مرحلهٔ ۴ استفاده می‌کند؛ این کار اثبات مالکیت شماره نیست و افزودن OTP تصمیم مستقلی است. درگاه واقعی هنوز پیاده‌سازی نشده؛ زیرساخت انتشار و اتصال آن در مرحلهٔ بعد بررسی می‌شود.

## وابستگی‌ها و استثنای ثبت‌شده

`pip-audit` روی محیط واقعی نصب‌شده پس از ارتقا، هیچ آسیب‌پذیری شناخته‌شده‌ای گزارش نکرد. `npm audit --omit=dev` نیز صفر است. اسکن کامل npm پنج مسیر وابستگی با severity بالا گزارش می‌کند که همگی از **یک advisory** در `braces <=3.0.3` منشأ می‌گیرند: `GHSA-vfj7-8cjw-p6xm`. در تاریخ بررسی نسخهٔ وصله‌شده منتشر نشده و آخرین نسخهٔ registry همان 3.0.3 است. پیشنهاد خودکار npm برای downgrade کردن Next lint config به نسل ۱۴ اجرا نشد.

مسیر اثر در این پروژه `eslint-config-next → @next/eslint-plugin-next → fast-glob → micromatch → braces` و فقط ابزار توسعه است؛ ورودی آن فایل‌ها و الگوهای پیکربندی مورد اعتماد مخزن است. این بسته در وابستگی‌های Production نیست. استثنا فقط برای این advisory و این استفاده ثبت می‌شود؛ کد یا الگوی ناشناس نباید با دسترسی secrets در lint/CI اجرا شود. بازبینی تا **۲۰۲۶/۱۱/۰۶** یا هنگام انتشار وصله لازم است. هیچ advisory از خروجی audit حذف یا پنهان نشده است.

## اجرای دوباره

از backend:

```powershell
uv sync --frozen
uv run --no-sync pytest -q --tb=short --show-capture=no
uv run --no-sync ruff check app scripts tests alembic
uv run --no-sync mypy app scripts tests alembic
uvx pip-audit --path .venv/Lib/site-packages
```

مسیر site-packages بالا برای Windows است؛ در Linux از Python محیط مجازی یا مسیر متناظر استفاده شود. ابزار audit جدا از وابستگی اجرایی نصب می‌شود.

از frontend، پس از شروع پیش‌نمایش `--dashboard-demo` و dev server روی ۳۰۰۰:

```powershell
npm run test
npm run typecheck
npm run lint
npm run format:check
npm audit --omit=dev
npm run build
# در ترمینالی جدا، برای آزمون CSP روی ساخت Production:
npx next start --hostname 127.0.0.1 --port 3001
# در ترمینال آزمون:
$env:SALONBOOK_SECURITY_WEB_ORIGIN='http://127.0.0.1:3001'
npm run test:e2e
```

سرور ۳۰۰۱ فقط برای بررسی HTML/CSP ساخت Production است؛ پل API توسعه عمداً در Production بسته می‌ماند. E2E عملیات واقعی با API آزمایشی روی ۳۰۰۰ انجام می‌شود. بدون متغیر سرور ساخته‌شده، آزمون مخصوص CSP صریحاً skip می‌شود؛ اجرای ثبت‌شدهٔ این مرحله باید بدون skip باشد.

شواهد نهایی در [گزارش بررسی](../frontend/verification-stage-14.md) هستند.

## منابع معیار

- [OWASP REST Security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html): محدودیت بدنه، نوع محتوا و کنترل دسترسی هر endpoint.
- [OWASP HTTP Headers](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html): سیاست headerها متناسب با API و HTML.
- [Next.js CSP](https://nextjs.org/docs/app/guides/content-security-policy): nonce و render پویا؛ راهنمای نصب‌شدهٔ Next 16.3.8 نیز پیش از تغییر خوانده شد.
- [هشدار braces](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm): دامنهٔ نسخه‌های آسیب‌پذیر و نبود نسخهٔ وصله‌شده در تاریخ بررسی.
