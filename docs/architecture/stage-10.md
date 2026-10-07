# مرحلهٔ ۱۰ — زیرساخت رابط کاربری

Next.js 16.3.8، React 19.3.0 و TypeScript strict در `frontend` ایجاد شده‌اند. نسخهٔ بسته‌ها و package-lock ثابت‌اند؛ نصب تکرارپذیر با `npm ci` است. فونت Vazirmatn محلی است و درخواست فونت به سرویس خارجی ندارد.

Layout مشترک، فارسی/RTL، طراحی موبایل، پوستهٔ روشن/تیره/سیستم، ورود و ثبت‌نام موبایل/رمز، حساب واقعی، خروج، Toast، Loading و Error/404 آماده‌اند. ریشهٔ سایت صفحهٔ معرفی و ورود است؛ خدمات، متخصص‌ها، انتخاب وقت و پرداخت مشتری مرحلهٔ ۱۱ هستند. فراموشی رمز، نبود بازیابی خودکار و پیامک را توضیح می‌دهد؛ فرم ایمیل یا ارسال کد ساختگی ندارد.

`src/app` صفحات، `src/components` قطعات رابط و Providerها، `src/lib` قرارداد API/نشست/اعتبارسنجی و `src/styles/tokens.css` رنگ‌ها را نگه می‌دارند. تصویر تزئینی CSS است. فرم‌ها با React Hook Form/Zod اعتبارسنجی می‌شوند؛ موبایل با ارقام فارسی/عربی به لاتین تبدیل می‌شود. محدودیت نهایی و امنیت در Backend باقی می‌ماند.

## نشست و API

مرورگر فقط `/api/v1` روی همان دامنه را فراخوانی می‌کند. کلاینت API دارای timeout، credentials=same-origin، cache=no-store، CSRF، Idempotency-Key اختیاری و خطای ساختاری است؛ نوشتن خودکار تکرار نمی‌شود. متن خام خطای Backend نمایش داده نمی‌شود؛ پیام فارسی با code/status انتخاب می‌شود.

نشست از /auth/me بارگذاری و Cookie آن HttpOnly نگه داشته می‌شود. رمز، Session Token و CSRF در localStorage نیستند؛ فقط ترجیح پوسته ذخیره می‌شود. ورود/ثبت‌نام CSRF عمومی تازه می‌گیرند. خروج و 401 وضعیت را پاک می‌کنند؛ BroadcastChannel بدون انتقال اطلاعات حساس تغییر حساب را به تب‌های دیگر اعلام می‌کند. پاسخ دیرهنگام /me نشست باطل‌شده را احیا نمی‌کند. بازگشت به تب و پایان اعتبار، بررسی نشست را تکرار می‌کنند.

صفحهٔ حساب در Build فقط Loading عمومی دارد؛ اطلاعات شخصی در HTML استاتیک یا Cache مشترک نیستند. UI جای مجوز Backend را نمی‌گیرد و tenant، قیمت یا پرداخت را تعیین نمی‌کند.

## اجرای محلی

ترمینال اول از backend:

```powershell
uv run --no-sync python -m scripts.dev --public-port 3000
```

ترمینال دوم از frontend:

```powershell
npm ci
Copy-Item .env.example .env.local
npm run dev
```

رابط: [پورت ۳۰۰۰](http://127.0.0.1:3000)، مستندات API: [پورت ۸۰۰۰](http://127.0.0.1:8000/api/v1/docs). پیش‌نمایش دیتابیس موقت و Worker انقضا/پرداخت خودش را دارد؛ توقف فقط همان دیتابیس را حذف می‌کند. مدیر اولیه اختیاری است؛ --manager-phone رمز را مخفی می‌پرسد. ثبت‌نام عادی از رابط ممکن است.

public-port=3000، Origin مرورگر را تعیین می‌کند. در این حالت نوشتن احراز هویت از Swagger پورت ۸۰۰۰ Origin معتبر ندارد؛ برای استفادهٔ مستقیم Swagger، Backend را بدون این گزینه اجرا کنید. اجرای مستقل Backend مانند قبل حفظ شده است.

Bridge توسعه فقط localhost/127.0.0.1 و پورت مرورگر ۳۰۰۰ را می‌پذیرد. Host/Cookie/Origin/CSRF معتبر حفظ می‌شوند؛ X-Tenant-ID و X-Forwarded-* عبور نمی‌کنند. بدنه حداکثر ۶۴ کیلوبایت است و redirect دنبال نمی‌شود. در NODE_ENV=production، حتی با متغیر محیطی فعال، Bridge پاسخ 503 می‌دهد.

در استقرار ماندگار، Edge باید `/api/v1` را مستقیم به FastAPI و باقی مسیرها را به Next بفرستد. Build موفق به معنی راه‌اندازی Edge/TLS/CSP نهایی نیست؛ این تنظیمات در سخت‌سازی/استقرار تکمیل می‌شوند. `npm start` به‌تنهایی اتصال production را راه نمی‌اندازد.

## بررسی و ادامه

```powershell
npm run lint
npm run typecheck
npm test
npm run test:e2e
npm run build
npm audit --omit=dev
```

E2E به دو سرور محلی و Edge نیاز دارد و مشتری آزمایشی در دیتابیس موقت می‌سازد. محیط جاری Windows/Node 24 است؛ Playwright برای msedge تنظیم شده و در CI لینوکس باید مرورگر نصب‌شدهٔ آن محیط انتخاب شود.

مرحلهٔ بعد ۱۱، Customer Booking UI است: لاین/خدمت/متخصص، تقویم/وقت آزاد، تأیید، پرداخت Mock، نتیجه و نوبت‌های من. حفظ انتخاب‌ها هنگام ورود وسط رزرو در آن مرحله پیاده می‌شود.

مراجع: [راهنمای نصب Next.js](https://nextjs.org/docs/app/getting-started/installation)، [Route Handlers](https://nextjs.org/docs/app/getting-started/route-handlers) و اسناد نسخهٔ نصب‌شده در `frontend/node_modules/next/dist/docs`.
