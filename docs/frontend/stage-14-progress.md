# وضعیت مرحلهٔ ۱۴ — کامل، ۲۰۲۶/۱۰/۰۷

- قرارداد و محدوده: `docs/architecture/stage-14.md`؛ شواهد: `docs/frontend/verification-stage-14.md`.
- Backend: middleware مشترک برای بدنهٔ واقعی ۶۴KiB، deadline ده‌ثانیه‌ای، query هشت‌کیلوبایتی، JSON-only و HTTPS در Production؛ headerهای امنیتی روی پاسخ‌ها و خطاها. limiter اتمیک PostgreSQL برای همهٔ مسیرهای tenant دارای context و کل API پلتفرم اضافه شده است. Retry-After متناسب با پنجره است.
- Mock در Production هنگام اعتبارسنجی تنظیمات رد می‌شود. cryptography برابر 50.0.2 است؛ `pyproject.toml` و `uv.lock` همگام‌اند. schema تغییر نکرده و head برابر `0011` است.
- Frontend: `src/proxy.ts` و `src/lib/csp.ts`، nonce سروری و CSP؛ root layout با `connection()` پویا است. API proxy توسعه در Production همچنان بسته است. static HTML/CDN caching با nonce مجاز نیست.
- کنترل‌ها: ۳۹۲ آزمون Backend، ۲۹ آزمون رابط، ۱۴ سناریوی Edge بدون skip، ساخت Production، typecheck/lint/format، Mypy/Ruff و schema همگی موفق. audit Python و npm production صفر است. advisory بدون وصلهٔ braces در ابزار lint با بازبینی تا ۲۰۲۶/۱۱/۰۶ مستند است.
- پیش‌نمایش اصلی API/پلتفرم از نو با `--dashboard-demo` راه‌اندازی شد؛ حساب‌های تصادفی جدید در `backend/.local/preview-accounts.md` و JSON کنار آن هستند. نام container فعلی با `salonbook-stage14-preview-` شروع می‌شود. سرویس‌های نامرتبط Docker دست‌نخورده‌اند. سرور ساخته‌شدهٔ Next روی ۳۰۰۱ فقط برای آزمون بود.
- مرحلهٔ بعد طبق درخواست اصلی: **۱۵ — Docker / CI/CD / Deployment / Payment Ready**. هنوز آغاز نشده است. باید proxy/TLS و trusted forwarding صریح، نرخ مرزی، تنظیمات واقعی، backup/restore و راهنمای اتصال درگاه را تکمیل کند؛ انتشار عمومی، OTP یا جابه‌جایی پول واقعی انجام نشده است.
