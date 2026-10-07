# SalonBook

سیستم نوبت‌دهی سالن زیبایی؛ توسعه طبق قرارداد ۱۵مرحله‌ای و تأیید جداگانهٔ هر مرحله.

- مرحلهٔ ۱: [تحلیل و معماری تأییدشده](docs/architecture/stage-01.md)
- مرحلهٔ ۲: [مدل داده، تصمیم‌ها، آزمون و راهنمای اجرا](docs/architecture/stage-02.md)
- مرحلهٔ ۳: [Backend Foundation، راهنمای اجرا و تصمیم‌های معماری](docs/architecture/stage-03.md)
- مرحلهٔ ۴: [ورود با موبایل، نشست امن و مجوزها؛ بدون ایمیل](docs/architecture/stage-04.md)
- مرحلهٔ ۵: [مدیریت سالن، کاربران، کارکنان و نقش‌ها](docs/architecture/stage-05.md)
- مرحلهٔ ۶: [لاین‌ها، خدمات، قیمت و انتساب کارکنان](docs/architecture/stage-06.md)
- مرحلهٔ ۷: [ساعت کاری، مرخصی و محاسبهٔ وقت‌های آزاد](docs/architecture/stage-07.md)
- مرحلهٔ ۸: [ثبت نوبت، رزرو موقت، جابه‌جایی و کنترل هم‌زمانی](docs/architecture/stage-08.md)
- مرحلهٔ ۹: [پرداخت Mock، رسید، فاکتور و بازپرداخت](docs/architecture/stage-09.md)
- مرحلهٔ ۱۰: [رابط فارسی، ورود موبایلی و زیرساخت Frontend](docs/architecture/stage-10.md)
- مرحلهٔ ۱۱: [رابط رزرو مشتری، پرداخت و پیگیری نوبت](docs/architecture/stage-11.md)
- مرحلهٔ ۱۲: [پنل مدیر کل، مدیر سالن، مدیر لاین و کارمند](docs/architecture/stage-12.md)
- مرحلهٔ ۱۳: [گزارش مالی، نمودار، درآمد تفکیکی و مدیریت اسناد و بازپرداخت](docs/architecture/stage-13.md)
- مرحلهٔ ۱۴: [سخت‌سازی امنیت، CSP، محدودیت درخواست و آزمون‌های امنیت و هم‌زمانی](docs/architecture/stage-14.md)
- [ERD](docs/database/erd.md) · [فرهنگ داده](docs/database/schema-dictionary.md) · [SQL Schema](docs/database/schema.sql)

تا مرحلهٔ ۱۴ کامل شده است: رزرو و پرداخت مشتری، پنل مدیران و کارکنان، گزارش مالی و سخت‌سازی امنیت برنامه. **۳۹۲ آزمون Backend، ۲۹ آزمون Frontend و ۱۴ سناریوی مرورگر موفق‌اند**؛ [گزارش بررسی](docs/frontend/verification-stage-14.md). اسکن فعلی وابستگی‌های سرور و وابستگی‌های اجرایی رابط بدون یافتهٔ شناخته‌شده است؛ یک advisory بدون وصله در ابزار توسعه با محدودهٔ اثر و مهلت بازبینی ثبت شده است. ورود با موبایل و رمز است؛ ایمیل در جریان کار وجود ندارد و OTP بعداً اضافه می‌شود. مرحلهٔ بعد Docker، CI/CD، استقرار و آماده‌سازی اتصال درگاه واقعی است؛ انتشار عمومی هنوز انجام نشده است.

## اجرای رابط و Backend با هم

در ترمینال اول:

```powershell
cd backend
uv run --no-sync python -m scripts.dev --public-port 3000 --demo
```

در ترمینال دوم، با Node.js 22.12 یا جدیدتر:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
npm run dev
```

[بازکردن رابط سالن‌بوک](http://127.0.0.1:3000). اتصال محلی API، اعتبار Origin و مرز استقرار Production در [راهنمای مرحلهٔ ۱۰](docs/architecture/stage-10.md) توضیح داده شده‌اند. نصب جاری با Node 24 آزمایش شده است.

با `--demo` سه خدمت، دو لاین، دو متخصص و وقت‌های آزاد در دیتابیس موقت ساخته می‌شود. برای امتحان رزرو از خود رابط حساب بسازید؛ پرداخت فقط آزمایشی است. جزئیات در [راهنمای مرحلهٔ ۱۱](docs/architecture/stage-11.md).

برای پیش‌نمایش پنل‌ها به‌جای `--demo` از `--dashboard-demo` استفاده کنید. [پنل سالن](http://127.0.0.1:3000/dashboard) و [پنل مدیر کل](http://127.0.0.1:3000/platform) آماده‌اند. شماره‌ها و رمزهای تصادفی همان اجرای موقت در `backend/.local/preview-accounts.md` و `backend/.local/dashboard-demo.json` ساخته می‌شوند و با اجرای دوباره عوض می‌شوند. پوشهٔ `.local` نباید منتشر شود. سرویس پلتفرم پورت ۸۰۰۱ و اتصال محدود جدا دارد؛ [راهنمای مرحلهٔ ۱۲](docs/architecture/stage-12.md).

## اجرای محلی Backend

پیش‌نیاز: Python 3.13، uv و Docker فعال.

```powershell
cd backend
uv sync --frozen --python 3.13
uv run --no-sync python -m scripts.dev
```

این فرمان PostgreSQL موقت را با حساب‌های جداگانهٔ migration و برنامه و یک سالن نمونه می‌سازد. Workerهای انقضای نوبت و پرداخت همان سالن نیز هر پنج ثانیه اجرا می‌شوند. رمزهای اتصال و کلید امضا تصادفی و در حافظه‌اند. هیچ ایمیل یا پیامکی ساخته یا ارسال نمی‌شود. با `Ctrl+C` برنامه و Workerها متوقف و همان دیتابیس موقت حذف می‌شوند.

- [مستندات تعاملی API](http://127.0.0.1:8000/api/v1/docs)
- [سلامت برنامه](http://127.0.0.1:8000/api/v1/health/live)
- [آمادگی دیتابیس](http://127.0.0.1:8000/api/v1/health/ready)

برای اتصال به دیتابیس ماندگار و تنظیم محیط، [راهنمای مرحلهٔ ۳](docs/architecture/stage-03.md) را ببینید.

برای آزمون کامل احراز هویت روی پیش‌نمایشِ در حال اجرا، در ترمینال دوم از پوشهٔ backend:

```powershell
uv run --no-sync python -m scripts.check_auth_preview
```

این بررسی ثبت‌نام موبایلی، ورود با قالب استاندارد شماره، تغییر رمز، ابطال نشست و خروج را با HTTP واقعی انجام می‌دهد؛ شماره، رمز و توکن را چاپ نمی‌کند. قرارداد CSRF، مهاجرت حساب قدیمی و مرز OTP آینده در [راهنمای مرحلهٔ ۴](docs/architecture/stage-04.md) آمده است.

برای پیش‌نمایش با مدیر اولیه، `python -m scripts.dev --manager-phone 09123456789` را اجرا کنید؛ رمز به‌صورت مخفی پرسیده می‌شود. پیش‌نمایش عادی مدیر از پیش تعیین‌شده ندارد. [راهنمای مرحلهٔ ۵](docs/architecture/stage-05.md) روش ساخت سالن ماندگار، تعیین مدیر سالن قدیمی، کنترل دامنه و تعلیق را توضیح می‌دهد.

آزمون خودکار مدیریت با HTTP واقعی در محیط موقت مستقل:

```powershell
uv run --no-sync python -m scripts.check_management_preview
uv run --no-sync python -m scripts.check_catalog_preview
uv run --no-sync python -m scripts.check_scheduling_preview
uv run --no-sync python -m scripts.check_appointments_preview
uv run --no-sync python -m scripts.check_payments_preview
```

آزمون دوم ساخت لاین و خدمت، قیمت‌گذاری، اتصال کارمند به لاین/خدمت، خروجی عمومی و حذف نرم را بررسی می‌کند. آزمون سوم ساعت کاری، وقت آزاد، درخواست/تأیید مرخصی و تعطیلی سالن را با HTTP واقعی بررسی می‌کند. مشاهدهٔ کاتالوگ و وقت آزاد عمومی به ورود نیاز ندارد. قواعد قیمت و انتساب در [راهنمای مرحلهٔ ۶](docs/architecture/stage-06.md) و برنامهٔ کاری و تداخل نوبت‌ها در [راهنمای مرحلهٔ ۷](docs/architecture/stage-07.md) آمده‌اند.

آزمون چهارم چرخهٔ نوبت و آزمون پنجم پرداخت Mock، فاکتور/رسید، بازپرداخت جزئی و بازپرداخت باقی‌مانده توسط Worker را کنترل می‌کنند. قرارداد نوبت در [مرحلهٔ ۸](docs/architecture/stage-08.md) و پرداخت/Worker در [مرحلهٔ ۹](docs/architecture/stage-09.md) آمده است. سرور ماندگار به Workerهای جداگانه نیاز دارد؛ `scripts.serve` به‌تنهایی Worker راه نمی‌اندازد.

## بررسی کیفیت

از پوشهٔ `backend`:

```powershell
uv run --no-sync python -m pytest -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app scripts tests alembic
uv run --no-sync python -m scripts.export_schema_docs --check
```

آزمون‌ها PostgreSQL موقت خود را اجرا و متوقف می‌کنند؛ به دیتابیس‌های موجود متصل نمی‌شوند. هر اجرا از صفر migrationها و مجوزها را بررسی می‌کند.
