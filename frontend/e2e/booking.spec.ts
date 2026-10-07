import { test, expect, type Page } from "@playwright/test";
import { randomInt, randomUUID } from "node:crypto";

async function choose(page: Page, service = "کوتاهی و فرم مو", days = 7) {
  await page.goto("/booking");
  if (service === "کوتاهی و فرم مو") {
    for (const name of ["کوتاهی و فرم مو", "براشینگ مو", "مشاورهٔ زیبایی"])
      await expect(
        page.getByRole("button", { name: new RegExp(name) }),
      ).toBeVisible();
    await page.screenshot({
      path: "../docs/frontend/stage-11-services.png",
      fullPage: true,
      caret: "initial",
    });
  }
  await page.getByRole("button", { name: new RegExp(service) }).click();
  await page.getByRole("button", { name: /استودیوی مو/ }).click();
  await page.getByRole("button", { name: /اولین وقت مناسب/ }).click();
  const config = await (
    await page.request.get("/api/v1/catalog/booking-settings")
  ).json();
  const day = new Date(Date.parse(`${config.today}T12:00Z`) + days * 86400000)
    .toISOString()
    .slice(0, 10);
  await page.getByLabel("انتخاب تاریخ دلخواه (میلادی)").fill(day);
  if (service === "مشاورهٔ زیبایی" && page.viewportSize()!.width < 700) {
    await expect(page.locator(".slot-choice").first()).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.getByRole("button", { name: /تغییر پوسته/ }).click();
    await page.getByRole("button", { name: /تغییر پوسته/ }).click();
    await page.screenshot({
      path: "../docs/frontend/stage-11-slots-dark-mobile.png",
      fullPage: true,
      caret: "initial",
    });
    await page.getByRole("button", { name: /تغییر پوسته/ }).click();
  }
  await page.locator(".slot-choice").first().click();
}
async function signup(page: Page) {
  const phone = `0912${randomInt(1000000, 9999999)}`;
  const password = `Booking test ${randomUUID()}`;
  await page.getByRole("link", { name: "ورود و ادامه" }).click();
  await page.getByRole("link", { name: "ثبت‌نام کنید" }).click();
  await page.getByLabel("نام و نام خانوادگی").fill("مشتری رزرو");
  await page.getByLabel("شماره موبایل").fill(phone);
  await page.getByLabel("رمز عبور", { exact: true }).fill(password);
  await page.getByRole("button", { name: "ساخت حساب", exact: true }).click();
  await page.getByRole("link", { name: "ورود به حساب", exact: true }).click();
  await page.getByLabel("شماره موبایل").fill(phone);
  await page.getByLabel("رمز عبور", { exact: true }).fill(password);
  await page.getByRole("button", { name: "ورود به حساب", exact: true }).click();
  await expect(page).toHaveURL(/\/booking$/);
}
test("guest resumes booking, paid receipt, reschedule, cancellation and refund", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await choose(page);
  await expect(
    page.getByRole("button", { name: "ثبت و ادامه به پرداخت" }),
  ).toHaveCount(0);
  await signup(page);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "همه‌چیز برای قرار شما آماده است؟" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "ثبت و ادامه به پرداخت" }),
  ).toBeEnabled();
  await page.screenshot({
    path: "../docs/frontend/stage-11-confirmation.png",
    fullPage: true,
    caret: "initial",
  });
  await page.getByRole("button", { name: "ثبت و ادامه به پرداخت" }).click();
  await expect(page).toHaveURL(/\/appointments\/[0-9a-f-]+$/);
  const appointmentUrl = page.url();
  await expect(
    page.getByRole("heading", { name: "یک قدم تا قطعی شدن نوبت" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "ادامه به پرداخت", exact: true })
    .click();
  await page.getByRole("button", { name: "پرداخت موفق آزمایشی" }).click();
  await expect(
    page.getByRole("heading", { name: "پرداخت و نوبت تأیید شد" }),
  ).toBeVisible();
  const paymentUrl = page.url();
  await expect(page.locator(".receipt-card")).toContainText(
    "اختصاص‌یافته به نوبت",
  );
  await page.screenshot({
    path: "../docs/frontend/stage-11-payment.png",
    fullPage: true,
    caret: "initial",
  });
  await page.goto(appointmentUrl);
  await page.getByRole("button", { name: "تغییر زمان نوبت" }).click();
  const config = await (
    await page.request.get("/api/v1/catalog/booking-settings")
  ).json();
  const nextDay = new Date(Date.parse(`${config.today}T12:00Z`) + 8 * 86400000)
    .toISOString()
    .slice(0, 10);
  await page.getByLabel("انتخاب تاریخ دلخواه (میلادی)").fill(nextDay);
  await page.locator(".slot-choice").first().click();
  await page.getByLabel("دلیل درخواست").fill("تغییر برنامهٔ روزانه");
  await page.getByRole("button", { name: "تأیید زمان جدید" }).click();
  await expect(page.getByLabel("دلیل درخواست")).toHaveCount(0);
  await page.getByRole("button", { name: "لغو نوبت", exact: true }).click();
  await page.getByLabel("دلیل درخواست").fill("آزمایش بازگشت مبلغ");
  await page.getByRole("button", { name: "تأیید لغو نوبت" }).click();
  await expect(page.locator(".status-pill")).toHaveText("لغو شده");
  await page.goto(paymentUrl);
  await expect(page.locator(".receipt-card")).toContainText("بازگشت مبلغ", {
    timeout: 20000,
  });
  await expect(
    page.getByRole("heading", { name: "پرداخت و نوبت تأیید شد" }),
  ).toHaveCount(0);
  await page.goto("/appointments");
  await expect(page.locator(".appointment-card")).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("free booking on mobile; slot conflict is handled without duplicate reservation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await choose(page, "مشاورهٔ زیبایی", 9);
  await signup(page);
  const draft = await page.evaluate(() =>
    JSON.parse(sessionStorage.getItem("salonbook:booking-draft")!),
  );
  const session = await (await page.request.get("/api/v1/auth/me")).json();
  const body = {
    line_id: draft.offer.line_id,
    service_ids: [draft.service.id],
    employee_id: draft.slot.employee_id,
    starts_at: draft.slot.starts_at,
  };
  const response = await page.request.post("/api/v1/appointments", {
    data: body,
    headers: {
      Origin: "http://127.0.0.1:3000",
      "X-CSRF-Token": session.csrf_token,
      "Idempotency-Key": randomUUID(),
    },
  });
  expect(response.status()).toBe(201);
  await page.getByRole("button", { name: "ثبت نوبت رایگان" }).click();
  await expect(page.locator(".form-error")).toContainText(
    "این وقت دیگر آزاد نیست",
  );
  await page.getByRole("button", { name: "تغییر ساعت" }).click();
  await page.locator(".slot-choice").first().click();
  await page.getByRole("button", { name: "ثبت نوبت رایگان" }).click();
  await expect(
    page.getByRole("heading", { name: "قرار شما ثبت شده است" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "ادامه به پرداخت", exact: true }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await expect(page.getByRole("button", { name: "بستن پیام" })).toHaveCount(0, {
    timeout: 10000,
  });
  await page.screenshot({
    path: "../docs/frontend/stage-11-mobile.png",
    fullPage: true,
    caret: "initial",
  });
});

test("failed attempt can retry; delayed payment reconciles after reload", async ({
  page,
}) => {
  test.setTimeout(90000);
  await choose(page, "براشینگ مو", 10);
  await signup(page);
  await page.getByRole("button", { name: "ثبت و ادامه به پرداخت" }).click();
  await page
    .getByRole("button", { name: "ادامه به پرداخت", exact: true })
    .click();
  await page.getByText("حالت‌های دیگر آزمایش", { exact: true }).click();
  await page
    .getByRole("button", { name: "پرداخت ناموفق", exact: true })
    .click();
  await expect(page.locator(".review-card")).toContainText("ناموفق");
  await page.getByRole("link", { name: "جزئیات نوبت", exact: true }).click();
  await page
    .getByRole("button", { name: "ادامه به پرداخت", exact: true })
    .click();
  await page.getByText("حالت‌های دیگر آزمایش", { exact: true }).click();
  await page.getByRole("button", { name: "پاسخ با تأخیر" }).click();
  await expect(
    page.getByRole("heading", { name: "منتظر نتیجهٔ پرداخت هستیم" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "پرداخت و نوبت تأیید شد" }),
  ).toBeVisible({ timeout: 45000 });
});

test("lost booking response retries the same command after reload", async ({
  page,
}) => {
  await choose(page, "مشاورهٔ زیبایی", 12);
  await signup(page);
  let firstKey: string | undefined;
  let createdId: string | undefined;
  await page.route("**/api/v1/appointments", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    firstKey = route.request().headers()["idempotency-key"];
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    createdId = (await response.json()).id;
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "ثبت نوبت رایگان" }).click();
  await expect(page.locator(".form-error")).toContainText("ارتباط برقرار نشد");
  await page.unroute("**/api/v1/appointments");
  await page.reload();
  const replay = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/v1/appointments"),
  );
  await page.getByRole("button", { name: "ثبت نوبت رایگان" }).click();
  const response = await replay;
  expect(response.request().headers()["idempotency-key"]).toBe(firstKey);
  expect(response.headers()["idempotency-replayed"]).toBe("true");
  await expect(page).toHaveURL(new RegExp(`/appointments/${createdId}$`));
  await page.goto("/appointments");
  await expect(page.locator(".appointment-card")).toHaveCount(1);
});
