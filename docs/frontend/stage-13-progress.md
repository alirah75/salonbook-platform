# وضعیت مرحلهٔ ۱۳ — کامل، ۲۰۲۶/۱۰/۰۶

- مسیر آماده: `/dashboard/finance` در پیش‌نمایش `http://127.0.0.1:3000`؛ API روی ۸۰۰۰ و API مستقل پلتفرم روی ۸۰۰۱.
- پیش‌نمایش با `uv run --no-sync python -m scripts.dev --public-port 3000 --dashboard-demo` اجرا شده است. حساب‌ها و رمزهای تصادفی فقط در `backend/.local/preview-accounts.md` و فایل JSON کنار آن هستند. ورود موبایلی بدون ایمیل باقی مانده است. درگاه فقط Mock است.
- ماژول جدید Backend: `app/modules/finance/{schemas,queries,service,router}.py`؛ مسیرها در API اصلی ثبت شده‌اند. هیچ migration جدیدی وجود ندارد؛ head برابر `0011` است.
- `finance.read` به مجوزهای ورود به فضای کاری و منوی مالی اضافه شده است. رابط جدید `src/components/dashboard/finance.tsx` و ابزار دقیق ریالی `src/lib/finance.ts` هستند. مسیر بازگشت امن ورود، finance را می‌پذیرد.
- دفتر قطعی، تفکیک test/live، روزهای محلی شامل پایان بازه، حداکثر ۳۶۶ روز، رشتهٔ عدد صحیح در JSON، BigInt در رابط، انتساب به snapshot کارمند اولیه، بازپرداخت ترتیبی اقلام و جداسازی دریافت تخصیص‌نیافته در قرارداد معماری توضیح داده شده‌اند.
- همهٔ کنترل‌ها موفق: ۳۷۶ آزمون سرور، بازاجرای ۱۲ آزمون مالی با بررسی دو سالن، ۲۷ آزمون رابط، ۱۲ سناریوی واقعی Edge، TypeScript، ESLint، Prettier، ساخت Production، Mypy، Ruff و تطابق اسناد schema.
- لاگ‌ها و تصاویر در `docs/backend/stage-13-*` و `docs/frontend/stage-13-*` و توضیح پوشش در `verification-stage-13.md` هستند. خروجی پیش‌نمایش موقت است؛ سرویس‌های Docker نامرتبط دست‌نخورده‌اند.
- گام بعد طبق قرارداد اصلی **مرحلهٔ ۱۴: Security / Testing / Production Hardening** است. این مرحله هنوز شروع نشده است. OTP، درگاه واقعی و انتشار عمومی انجام نشده‌اند.
