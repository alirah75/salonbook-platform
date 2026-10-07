import { test, expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { randomInt, randomUUID } from "node:crypto";

const file = "../backend/.local/dashboard-demo.json";
type Credentials = Record<
  string,
  { phone: string; password: string; name: string }
>;
const credentials: Credentials = existsSync(file)
  ? JSON.parse(readFileSync(file, "utf8"))
  : {};
test.skip(
  !credentials.salon_manager,
  "Start the opt-in disposable --dashboard-demo preview first.",
);
async function login(page: Page, role: string) {
  await page.goto("/login?returnTo=%2Fdashboard");
  await page
    .getByLabel("شماره موبایل", { exact: true })
    .fill(credentials[role].phone);
  await page
    .getByLabel("رمز عبور", { exact: true })
    .fill(credentials[role].password);
  await page.getByRole("button", { name: "ورود به حساب", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(
    page.getByRole("heading", { name: "امروز، با برنامه." }),
  ).toBeVisible();
}
async function screenshot(page: Page, name: string) {
  await expect(page.getByRole("button", { name: "بستن پیام" })).toHaveCount(0, {
    timeout: 10000,
  });
  await page.getByRole("heading", { level: 1 }).click();
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    caret: "initial",
    path: `../docs/frontend/stage-12-${name}.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
}
test("manager manages staff, custom role, catalog and calendar through real API", async ({
  page,
}) => {
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.name));
  await login(page, "salon_manager");
  await expect(
    page
      .getByRole("navigation", { name: "بخش‌های فضای کاری" })
      .getByRole("link"),
  ).toHaveCount(9);
  await screenshot(page, "manager");
  const nonce = randomUUID().slice(0, 8);
  const userName = `همکار آزمون ${nonce}`;
  await page.getByRole("link", { name: "حساب‌های سالن", exact: true }).click();
  await page.getByText("ساخت حساب جدید", { exact: true }).click();
  const create = page.locator("form").filter({
    has: page.getByRole("button", { name: "ساخت حساب", exact: true }),
  });
  await create.getByLabel("نام و نام خانوادگی").fill(userName);
  await create
    .getByLabel("شماره موبایل", { exact: true })
    .fill(`0913${randomInt(1000000, 9999999)}`);
  await create
    .getByLabel("رمز عبور اولیه", { exact: true })
    .fill(`Staff demo ${randomUUID()}`);
  await create.getByLabel("نوع حساب").selectOption("employee");
  await create.getByRole("button", { name: "ساخت حساب", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: userName, exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "نقش‌ها و دسترسی", exact: true })
    .click();
  await page.getByText("ساخت نقش اختصاصی", { exact: true }).click();
  await page.getByLabel("نام نقش", { exact: true }).fill(`پذیرش ${nonce}`);
  await page.getByLabel("کد لاتین نقش").fill(`reception_${nonce}`);
  await page.getByLabel("دیدن نوبت‌های کاری", { exact: true }).check();
  await page.getByLabel("مجوزهای انتخاب‌شده را بررسی کردم").check();
  await page.getByRole("button", { name: "ساخت نقش", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: `پذیرش ${nonce}` }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "لاین‌ها و خدمات", exact: true })
    .click();
  await page.getByText("ساخت لاین جدید", { exact: true }).click();
  const lineForm = page.locator("form").filter({
    has: page.getByRole("button", { name: "ساخت لاین", exact: true }),
  });
  await lineForm
    .getByLabel("نام لاین", { exact: true })
    .fill(`لاین آزمون ${nonce}`);
  await lineForm.getByLabel("شناسهٔ لاتین لاین").fill(`test-${nonce}`);
  await lineForm
    .getByRole("button", { name: "ساخت لاین", exact: true })
    .click();
  await expect(
    page.getByLabel("انتخاب لاین").locator("option:checked"),
  ).toHaveText(`لاین آزمون ${nonce}`);
  await page.getByText("تعریف خدمت جدید", { exact: true }).click();
  const serviceForm = page.locator("form").filter({
    has: page.getByRole("button", { name: "ساخت خدمت", exact: true }),
  });
  await serviceForm
    .getByLabel("نام خدمت", { exact: true })
    .fill(`خدمت آزمون ${nonce}`);
  await serviceForm.getByLabel("کد لاتین خدمت").fill(`test-${nonce}`);
  await serviceForm
    .getByRole("button", { name: "ساخت خدمت", exact: true })
    .click();
  await expect(
    page.getByText(`خدمت آزمون ${nonce} · فعال`, { exact: true }),
  ).toBeVisible();
  await page.getByText("افزودن خدمت به لاین", { exact: true }).click();
  const offer = page.locator("form").filter({
    has: page.getByRole("button", { name: "افزودن خدمت", exact: true }),
  });
  await expect(
    offer
      .getByLabel("خدمت", { exact: true })
      .locator("option")
      .filter({ hasText: `خدمت آزمون ${nonce}` }),
  ).toHaveCount(1);
  await offer
    .getByLabel("خدمت", { exact: true })
    .selectOption({ label: `خدمت آزمون ${nonce}` });
  await offer.getByLabel("قیمت (ریال)").fill("1500000");
  await offer.getByRole("button", { name: "افزودن خدمت", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: `خدمت آزمون ${nonce}` }),
  ).toBeVisible();
  await page.getByRole("link", { name: "تیم و مهارت‌ها", exact: true }).click();
  await page
    .getByLabel("لاین تیم")
    .selectOption({ label: `لاین آزمون ${nonce}` });
  await page.getByText("افزودن کارمند به این لاین", { exact: true }).click();
  await page
    .getByLabel("انتخاب کارمند", { exact: true })
    .selectOption({ label: userName });
  await page
    .getByRole("button", { name: "افزودن به تیم", exact: true })
    .click();
  const colleague = page.locator("article").filter({
    has: page.getByRole("heading", { name: userName, exact: true }),
  });
  await expect(colleague).toBeVisible();
  await colleague.getByText("مهارت‌ها و وضعیت همکاری", { exact: true }).click();
  await colleague
    .getByLabel("خدمت قابل ارائه", { exact: true })
    .selectOption({ label: `خدمت آزمون ${nonce}` });
  await colleague
    .getByRole("button", { name: "افزودن مهارت", exact: true })
    .click();
  await expect(
    colleague.getByLabel(`خدمت آزمون ${nonce}`, { exact: true }),
  ).toBeChecked();
  await page.getByRole("link", { name: "برنامه و مرخصی", exact: true }).click();
  await page.getByText("ایجاد تقویم کاری", { exact: true }).click();
  await page.getByLabel("نوع تقویم").selectOption("LINE");
  await page
    .getByLabel("لاین تقویم")
    .selectOption({ label: `لاین آزمون ${nonce}` });
  await page.getByRole("button", { name: "ایجاد تقویم", exact: true }).click();
  await expect(
    page
      .getByLabel("تقویم کاری")
      .locator("option")
      .filter({ hasText: `لاین آزمون ${nonce}` }),
  ).toHaveCount(1);
  await page
    .getByLabel("تقویم کاری")
    .selectOption({ label: `لاین · لاین آزمون ${nonce}` });
  await page.getByRole("button", { name: "افزودن بازه", exact: true }).click();
  await page
    .getByLabel("برنامهٔ هفتگی و بازه‌های حذف‌شده را بررسی کردم")
    .check();
  await page
    .getByRole("button", { name: "ذخیرهٔ برنامهٔ هفتگی", exact: true })
    .click();
  await expect(
    page.getByText("تغییرات ذخیره شد.", { exact: true }).last(),
  ).toBeVisible();
  await page.reload();
  await page
    .getByLabel("تقویم کاری")
    .selectOption({ label: `لاین · لاین آزمون ${nonce}` });
  await expect(page.getByLabel("شروع بازه 1", { exact: true })).toHaveValue(
    "09:00",
  );
  expect(errors).toEqual([]);
});
test("line manager sees only their line and cannot access tenant accounts", async ({
  page,
}) => {
  await login(page, "line_manager");
  const nav = page.getByRole("navigation", { name: "بخش‌های فضای کاری" });
  await expect(nav.getByRole("link", { name: "حساب‌های سالن" })).toHaveCount(0);
  await page
    .getByRole("link", { name: "لاین‌ها و خدمات", exact: true })
    .click();
  await expect(page.getByLabel("انتخاب لاین").locator("option")).toHaveCount(1);
  await expect(page.getByText("ساخت لاین جدید", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByLabel("انتخاب لاین").locator("option:checked"),
  ).toHaveText("استودیوی مو");
  await screenshot(page, "line-manager");
  await page.goto("/dashboard/users");
  await expect(
    page.getByRole("heading", { name: "به این بخش دسترسی ندارید" }),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/users")).status()).toBe(403);
});
test("employee requests leave and manager approves it", async ({
  page,
  browser,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "employee");
  const nav = page.getByRole("navigation", { name: "بخش‌های فضای کاری" });
  await expect(nav.getByRole("link")).toHaveCount(3);
  await page.getByRole("link", { name: "برنامه و مرخصی", exact: true }).click();
  await expect(page.getByText("ایجاد تقویم کاری", { exact: true })).toHaveCount(
    0,
  );
  const day = new Date(Date.now() + 86400000 * 7).toISOString().slice(0, 10);
  const reason = `مرخصی آزمون ${randomUUID().slice(0, 8)}`;
  await page.getByText("درخواست مرخصی جدید", { exact: true }).click();
  await page.getByLabel("شروع به وقت سالن (میلادی)").fill(`${day}T21:00`);
  await page.getByLabel("پایان به وقت سالن (میلادی)").fill(`${day}T22:00`);
  await page.getByLabel("دلیل مرخصی یا مسدودی").fill(reason);
  await page
    .getByRole("button", { name: "ارسال درخواست مرخصی", exact: true })
    .click();
  await expect(
    page
      .locator("article")
      .filter({ hasText: reason })
      .getByText("در انتظار تأیید", { exact: true }),
  ).toBeVisible();
  await page.getByText("درخواست مرخصی جدید", { exact: true }).click();
  await screenshot(page, "employee-mobile");
  const manager = await browser.newContext({
    baseURL: "http://127.0.0.1:3000",
  });
  const managerPage = await manager.newPage();
  try {
    await login(managerPage, "salon_manager");
    await managerPage
      .getByRole("link", { name: "برنامه و مرخصی", exact: true })
      .click();
    await managerPage
      .getByLabel("تقویم کاری")
      .selectOption({ label: `کارمند · ${credentials.employee.name}` });
    const block = managerPage.locator("article").filter({ hasText: reason });
    await block.getByLabel("وضعیت جدید").selectOption("APPROVED");
    await block.getByRole("button", { name: "ثبت وضعیت", exact: true }).click();
    await expect(block.getByText("تأیید شده", { exact: true })).toBeVisible();
  } finally {
    await manager.close();
  }
  await page.reload();
  await expect(
    page
      .locator("article")
      .filter({ hasText: reason })
      .getByText("تأیید شده", { exact: true }),
  ).toBeVisible();
});
test("platform mobile login creates and suspends a salon with audit", async ({
  page,
  context,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.name));
  await page.goto("/platform");
  await page
    .getByLabel("شماره موبایل مدیر کل")
    .fill(credentials.super_admin.phone);
  await page
    .getByLabel("رمز عبور مدیر کل", { exact: true })
    .fill(credentials.super_admin.password);
  await page
    .getByRole("button", { name: "ورود به مدیریت پلتفرم", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "سالن‌های پلتفرم" }),
  ).toBeVisible();
  const cookie = (await context.cookies("http://127.0.0.1:3000/platform")).find(
    (c) => c.name === "sb_platform",
  );
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.path).toBe("/platform");
  const nonce = randomUUID().slice(0, 8);
  const name = `سالن آزمون ${nonce}`;
  await page.getByText("ایجاد سالن جدید", { exact: true }).click();
  await page.getByLabel("نام سالن جدید").fill(name);
  await page.getByLabel("دامنهٔ سالن").fill(`salon-${nonce}.example.test`);
  await page.getByLabel("نام مدیر سالن", { exact: true }).fill("مدیر آزمون");
  await page
    .getByLabel("شماره موبایل مدیر سالن")
    .fill(`0915${randomInt(1000000, 9999999)}`);
  await page
    .getByLabel("رمز اولیهٔ مدیر سالن", { exact: true })
    .fill(`Initial demo ${randomUUID()}`);
  await page.getByLabel("دلیل ایجاد سالن").fill("آزمون چرخهٔ مدیریت سالن");
  await page
    .getByRole("button", { name: "ایجاد سالن و حساب مدیر", exact: true })
    .click();
  const card = page
    .locator("article")
    .filter({ has: page.getByRole("heading", { name, exact: true }) });
  await expect(card).toBeVisible();
  await expect(
    card.getByText("نیازمند بررسی مالکیت", { exact: true }),
  ).toBeVisible();
  await card.getByText("تغییر وضعیت فعالیت", { exact: true }).click();
  await card.getByLabel("دلیل تغییر وضعیت").fill(`توقف آزمایشی ${nonce}`);
  await card.getByLabel(`تعلیق ${name} را تأیید می‌کنم`).check();
  await card
    .getByRole("button", { name: "ثبت وضعیت سالن", exact: true })
    .click();
  await expect(card.getByText("تعلیق شده", { exact: true })).toBeVisible();
  await page.getByText("ایجاد سالن جدید", { exact: true }).click();
  await screenshot(page, "platform");
  await page
    .getByRole("button", { name: "تاریخچهٔ عملیات", exact: true })
    .click();
  await expect(
    page.getByText(`توقف آزمایشی ${nonce}`, { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "خروج مدیر کل", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "ورود مدیر کل پلتفرم" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("staff booking workflow keeps employee amounts private and supports manager reschedule and cancel", async ({
  page,
  browser,
}) => {
  const scope = JSON.parse(readFileSync(file, "utf8")).scope as {
    employee_id: string;
    line_id: string;
  };
  const customer = await browser.newContext({
    baseURL: "http://127.0.0.1:3000",
  });
  const request = customer.request;
  const phone = `0914${randomInt(1000000, 9999999)}`;
  const password = `Customer demo ${randomUUID()}`;
  const name = `مشتری نوبت کاری ${randomUUID().slice(0, 8)}`;
  const pre = await request.get("/api/v1/auth/csrf");
  const csrf = (await pre.json()).csrf_token;
  const headers = { Origin: "http://127.0.0.1:3000", "X-CSRF-Token": csrf };
  expect(
    (
      await request.post("/api/v1/auth/register", {
        headers,
        data: { phone, password, display_name: name },
      })
    ).status(),
  ).toBe(202);
  const signed = await request.post("/api/v1/auth/login", {
    headers,
    data: { phone, password },
  });
  expect(signed.status()).toBe(200);
  const session = await signed.json();
  const settings = await (
    await request.get("/api/v1/catalog/booking-settings")
  ).json();
  const day = new Date(Date.parse(`${settings.today}T12:00:00Z`) + 3 * 86400000)
    .toISOString()
    .slice(0, 10);
  const until = new Date(Date.parse(`${day}T12:00:00Z`) + 86400000)
    .toISOString()
    .slice(0, 10);
  const offers = await (
    await request.get(
      `/api/v1/catalog/lines/${scope.line_id}/services?limit=100`,
    )
  ).json();
  const service = offers.items.find((o: { is_free: boolean }) => o.is_free);
  expect(service).toBeTruthy();
  const path = `/api/v1/scheduling/availability?line_id=${scope.line_id}&service_ids=${service.service_id}&employee_id=${scope.employee_id}&date_from=${day}&date_until=${until}&limit=100`;
  const slots = await (await request.get(path)).json();
  expect(slots.items.length).toBeGreaterThan(3);
  const booked = await request.post("/api/v1/appointments", {
    headers: {
      Origin: "http://127.0.0.1:3000",
      "X-CSRF-Token": session.csrf_token,
      "Idempotency-Key": randomUUID(),
    },
    data: {
      line_id: scope.line_id,
      service_ids: [service.service_id],
      employee_id: scope.employee_id,
      starts_at: slots.items[0].starts_at,
    },
  });
  expect(booked.status()).toBe(201);
  const appointment = await booked.json();
  await customer.close();
  await login(page, "employee");
  await page.getByLabel("روز کاری (میلادی)").fill(day);
  const row = page
    .locator("article")
    .filter({ has: page.getByRole("heading", { name, exact: true }) });
  await expect(row).toBeVisible();
  expect(
    (
      await (
        await page.request.get(`/api/v1/dashboard/overview?day=${day}`)
      ).json()
    ).appointments.items.find((a: { id: string }) => a.id === appointment.id)
      .total_amount,
  ).toBeNull();
  await row.getByText("مدیریت این نوبت", { exact: true }).click();
  await expect(row.getByLabel("عملیات نوبت").locator("option")).toHaveCount(2);
  await row.getByLabel("دلیل یا توضیح").fill("بررسی محدودیت زمانی");
  await row.getByLabel("اطلاعات و عملیات انتخاب‌شده را بررسی کردم").check();
  await row
    .getByRole("button", { name: "ثبت تغییر نوبت", exact: true })
    .click();
  await expect(row.getByRole("alert")).toContainText(
    "هنوز زمان ثبت این وضعیت نرسیده است",
  );
  await page.goto("/account");
  await page.getByRole("button", { name: "خروج از حساب", exact: true }).click();
  await login(page, "salon_manager");
  await page.getByLabel("روز کاری (میلادی)").fill(day);
  await expect(row).toBeVisible();
  await row.getByText("مدیریت این نوبت", { exact: true }).click();
  await row.getByLabel("عملیات نوبت").selectOption("reschedule");
  const replacement = new Date(
    Date.parse(slots.items[3].starts_at) + 3.5 * 3600000,
  )
    .toISOString()
    .slice(0, 16);
  await row.getByLabel("زمان جدید به وقت سالن (میلادی)").fill(replacement);
  await row.getByLabel("دلیل یا توضیح").fill("جابه‌جایی با هماهنگی مشتری");
  await row.getByLabel("اطلاعات و عملیات انتخاب‌شده را بررسی کردم").check();
  await row
    .getByRole("button", { name: "ثبت تغییر نوبت", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/v1/appointments/${appointment.id}`)
          ).json()
        ).version,
    )
    .toBe(2);
  await expect(row.locator(".work-appointment-time strong")).toHaveText(
    new Intl.DateTimeFormat("fa-IR", {
      timeZone: "Asia/Tehran",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(slots.items[3].starts_at)),
  );
  await row.getByText("مدیریت این نوبت", { exact: true }).click();
  await row.getByLabel("عملیات نوبت").selectOption("cancel");
  await row.getByLabel("دلیل یا توضیح").fill("لغو آزمایشی با هماهنگی مشتری");
  await row.getByLabel("اطلاعات و عملیات انتخاب‌شده را بررسی کردم").check();
  await row
    .getByRole("button", { name: "ثبت تغییر نوبت", exact: true })
    .click();
  await expect(row.getByText("لغو شده", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: /تغییر پوسته/ }).click();
  await page.getByRole("button", { name: /تغییر پوسته/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await screenshot(page, "appointments-dark-mobile");
});
