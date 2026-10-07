import { test, expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { randomInt, randomUUID } from "node:crypto";

const file = "../backend/.local/dashboard-demo.json";
const demo = existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : {};
test.skip(
  !demo.salon_manager,
  "Start the disposable --dashboard-demo preview first.",
);
async function login(page: Page, role: string) {
  await page.goto("/login?returnTo=%2Fdashboard%2Ffinance");
  await page.getByLabel("شماره موبایل", { exact: true }).fill(demo[role].phone);
  await page.getByLabel("رمز عبور", { exact: true }).fill(demo[role].password);
  await page.getByRole("button", { name: "ورود به حساب", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard\/finance$/);
}
async function screenshot(page: Page, name: string) {
  await expect(page.getByRole("button", { name: "بستن پیام" })).toHaveCount(0, {
    timeout: 10000,
  });
  await page.getByRole("heading", { level: 1 }).click();
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: `../docs/frontend/stage-13-${name}.png`,
    fullPage: true,
    caret: "initial",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
}

test("manager reports real mock evidence, requests and approves partial refund, reads invoice", async ({
  page,
  browser,
}) => {
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const customer = await browser.newContext({
    baseURL: "http://127.0.0.1:3000",
  });
  const request = customer.request;
  const phone = `0915${randomInt(1000000, 9999999)}`;
  const password = `Financial demo ${randomUUID()}`;
  const pre = await (await request.get("/api/v1/auth/csrf")).json();
  const headers = {
    Origin: "http://127.0.0.1:3000",
    "X-CSRF-Token": pre.csrf_token,
  };
  expect(
    (
      await request.post("/api/v1/auth/register", {
        headers,
        data: { phone, password, display_name: "مشتری گزارش مالی" },
      })
    ).status(),
  ).toBe(202);
  const signed = await request.post("/api/v1/auth/login", {
    headers,
    data: { phone, password },
  });
  expect(signed.status()).toBe(200);
  headers["X-CSRF-Token"] = (await signed.json()).csrf_token;
  const settings = await (
    await request.get("/api/v1/catalog/booking-settings")
  ).json();
  const day = new Date(Date.parse(`${settings.today}T12:00Z`) + 11 * 86400000)
    .toISOString()
    .slice(0, 10);
  const until = new Date(Date.parse(`${day}T12:00Z`) + 86400000)
    .toISOString()
    .slice(0, 10);
  const offers = await (
    await request.get(
      `/api/v1/catalog/lines/${demo.scope.line_id}/services?limit=100`,
    )
  ).json();
  const service = offers.items.find((o: { is_free: boolean }) => !o.is_free);
  const slots = await (
    await request.get(
      `/api/v1/scheduling/availability?line_id=${demo.scope.line_id}&service_ids=${service.service_id}&employee_id=${demo.scope.employee_id}&date_from=${day}&date_until=${until}&limit=100`,
    )
  ).json();
  expect(slots.items.length).toBeGreaterThan(0);
  const booked = await request.post("/api/v1/appointments", {
    headers: { ...headers, "Idempotency-Key": randomUUID() },
    data: {
      line_id: demo.scope.line_id,
      service_ids: [service.service_id],
      employee_id: demo.scope.employee_id,
      starts_at: slots.items[0].starts_at,
    },
  });
  expect(booked.status()).toBe(201);
  const appointment = await booked.json();
  const payment = await request.post("/api/v1/payments", {
    headers: { ...headers, "Idempotency-Key": randomUUID() },
    data: { appointment_id: appointment.id },
  });
  expect(payment.status()).toBe(201);
  const finished = await request.post(
    `/api/v1/payments/${(await payment.json()).id}/mock-checkout`,
    { headers, data: { scenario: "success" } },
  );
  expect(finished.status()).toBe(200);
  const receipt = (await finished.json()).transactions[0];
  await customer.close();
  await login(page, "salon_manager");
  await expect(page.locator(".finance-metrics")).toContainText(
    "خالص دریافتی خدمات",
  );
  const row = page
    .locator(".finance-document")
    .filter({ hasText: receipt.receipt_number });
  await expect(row).toBeVisible();
  await row.getByText("درخواست بازپرداخت", { exact: true }).click();
  const reason = `بازپرداخت جزئی ${randomUUID().slice(0, 8)}`;
  await row.getByLabel("مبلغ بازپرداخت (ریال)").fill("12345");
  await row.getByLabel("دلیل بازپرداخت").fill(reason);
  await row.getByLabel("مبلغ و دلیل را بررسی کردم").check();
  await row
    .getByRole("button", { name: "ثبت درخواست بازپرداخت", exact: true })
    .click();
  await expect(
    page.getByText("درخواست ثبت شد؛ برای تأیید به فهرست بازپرداخت‌ها بروید."),
  ).toBeVisible();
  await page.getByLabel("نوع سند").selectOption("refunds");
  const refund = page.locator(".finance-document").filter({ hasText: reason });
  await expect(refund).toContainText("در انتظار تأیید");
  await refund.getByLabel(/بازپرداخت .* را تأیید می‌کنم/).check();
  await refund.getByRole("button", { name: "تأیید و اجرای بازپرداخت" }).click();
  await expect(refund).toContainText("موفق", { timeout: 20000 });
  await expect(
    refund.getByRole("button", { name: "تأیید و اجرای بازپرداخت" }),
  ).toHaveCount(0);
  await page.getByLabel("نوع سند").selectOption("invoices");
  const invoice = page
    .locator(".finance-document")
    .filter({ hasText: appointment.id });
  await invoice.getByRole("button", { name: "مشاهدهٔ فاکتور" }).click();
  await expect(invoice.locator(".finance-invoice")).toContainText(
    "مشتری گزارش مالی",
  );
  await expect(invoice.locator(".finance-invoice")).toContainText(
    service.service_name,
  );
  await page.getByLabel("نوع گزارش").selectOption("month");
  await expect(page.locator(".finance-chart-day")).toHaveCount(
    new Date(
      Date.UTC(
        Number(settings.today.slice(0, 4)),
        Number(settings.today.slice(5, 7)),
        0,
      ),
    ).getUTCDate(),
  );
  await page.getByLabel("تفکیک بر اساس").selectOption("service");
  await expect(page.getByRole("region", { name: "تفکیک درآمد" })).toContainText(
    service.service_name,
  );
  await screenshot(page, "manager");
  await page.getByLabel("نوع مبالغ").selectOption("false");
  await expect(page.locator(".finance-metrics strong")).toHaveText([
    "۰ ریال",
    "۰ ریال",
    "۰ ریال",
    "۰ ریال",
  ]);
  await expect(page.locator(".finance-document")).toHaveCount(0);
  await page.getByLabel("نوع مبالغ").selectOption("true");
  await page.getByLabel("نوع گزارش").selectOption("custom");
  await page.getByLabel("از تاریخ (میلادی)").fill("2025-01-01");
  await expect(page.locator(".form-error[role=alert]")).toContainText(
    "حداکثر ۳۶۶ روز",
  );
  await page.getByLabel("از تاریخ (میلادی)").fill(settings.today);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: /تغییر پوسته/ }).click();
  await page.getByRole("button", { name: /تغییر پوسته/ }).click();
  await expect(page.locator(".finance-metrics")).toBeVisible();
  await screenshot(page, "mobile-dark");
  expect(errors).toEqual([]);
});

test("line manager has scoped read-only finance and employees cannot enter", async ({
  page,
}) => {
  await login(page, "line_manager");
  await expect(
    page.getByRole("heading", { name: "گزارش مالی.", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("لاین گزارش").locator("option")).toHaveCount(2);
  await expect(page.locator(".finance-metrics")).toBeVisible();
  await expect(
    page.getByText("درخواست بازپرداخت", { exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("نوع سند").selectOption("refunds");
  await expect(
    page.getByRole("button", { name: "تأیید و اجرای بازپرداخت" }),
  ).toHaveCount(0);
  await screenshot(page, "line-manager");
  await page.goto("/account");
  await page.getByRole("button", { name: "خروج از حساب", exact: true }).click();
  await login(page, "employee");
  await expect(
    page.getByRole("link", { name: "گزارش مالی", exact: true }),
  ).toHaveCount(0);
  const today = (
    await (await page.request.get("/api/v1/catalog/booking-settings")).json()
  ).today;
  expect(
    (
      await page.request.get(
        `/api/v1/finance/report?start=${today}&end=${today}`,
      )
    ).status(),
  ).toBe(403);
  await expect(page.locator(".finance-metrics")).toHaveCount(0);
});
