# بررسی مرحلهٔ ۱۰

نتیجهٔ نهایی، ۲۰۲۶-۱۰-۰۴:

| بررسی | نتیجه |
|---|---|
| ESLint | موفق |
| Next typegen + TypeScript strict | موفق |
| Vitest + Testing Library | ۱۳ آزمون موفق، 3.37s |
| Playwright با Edge واقعی | یک سناریوی کامل موفق، 6.7s |
| Next production build | موفق؛ ۸ خروجی مسیر |
| npm audit --omit=dev | صفر آسیب‌پذیری شناخته‌شده |
| Backend | ۳۵۲ آزمون موفق؛ گزارش مرحلهٔ ۹ |
| HTTP پرداخت پس از تغییر preview | موفق |

E2E ثبت‌نام، ورود، حساب، Cookie HttpOnly، reload با نشست، خروج، فرم نامعتبر، عرض ۳۹۰ پیکسل بدون scroll افقی، پوستهٔ تیره و حفظ آن، نبود ایمیل و نبود بازیابی پیامکی ساختگی را بررسی می‌کند. خطای JavaScript و hydration کنترل شد. تصاویر مرورگر بصری بررسی شدند: [دسکتاپ](stage-10-desktop.png)، [موبایل](stage-10-mobile.png)، [تیره](stage-10-dark.png).

تست‌های واحد مرز same-origin، عدم تکرار خودکار، پیام خطای امن، CSRF، پاک‌شدن نشست و عدم احیای آن با پاسخ دیرهنگام، فرم موبایل، Bridge محدود توسعه و بسته‌بودن آن در Production را پوشش می‌دهند.

محدودیت وابستگی توسعه: audit کامل پنج هشدار high در زنجیرهٔ eslint-config-next → @next/eslint-plugin-next → fast-glob → micromatch → braces دارد. ریشه، [braces و الگوی بسیار تو‌در‌تو](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) است؛ آخرین نسخهٔ موجود هنگام بررسی 3.0.3 و فاقد رفع این هشدار بود. پیشنهاد npm، downgrade بزرگ config به 14.2.35 بود که با Next 16 هم‌نسخه نیست و اعمال نشد. runtime بدون هشدار است. ESLint 9.39.5 با config جاری سازگار است؛ ESLint 10.12.0 به دلیل API حذف‌شدهٔ مورد استفادهٔ eslint-plugin-react خطا داشت. رفع این زنجیره و مهاجرت lint پیش از تأیید Production مرحلهٔ ۱۴ لازم است؛ ورودی glob نامطمئن به lint داده نشود.

Bridge محلی در production بسته است؛ Edge/TLS و سخت‌سازی نهایی مستقر نشده‌اند. این گزارش ادعای آمادگی انتشار عمومی ندارد.
