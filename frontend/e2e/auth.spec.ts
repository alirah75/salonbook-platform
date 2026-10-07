import { test, expect } from "@playwright/test";
import { randomInt, randomUUID } from "node:crypto";

test("Persian mobile registration, real session, reload and logout", async ({
  page,
  context,
}) => {
  const phone = `0912${randomInt(1000000, 9999999)}`;
  const password = `Salon test ${randomUUID()}`;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.name));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      /hydrat|server rendered HTML/i.test(message.text())
    )
      errors.push("hydration error");
  });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(
    page.getByRole("heading", { name: "برای خودت، وقت بگذار." }),
  ).toBeVisible();
  await page.screenshot({
    caret: "initial",
    path: "../docs/frontend/stage-10-desktop.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "ساخت حساب جدید" }).click();
  await page.getByLabel("نام و نام خانوادگی").fill("کاربر آزمایشی");
  await page.getByLabel("شماره موبایل").fill(phone);
  await page.getByLabel("رمز عبور", { exact: true }).fill(password);
  await page.getByRole("button", { name: "ساخت حساب", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "یک قدم تا حساب شما" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "ورود به حساب", exact: true }).click();
  await page.getByLabel("شماره موبایل").fill(phone);
  await page.getByLabel("رمز عبور", { exact: true }).fill(password);
  await page.getByRole("button", { name: "ورود به حساب", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(
    page.getByRole("heading", { name: /کاربر آزمایشی، خوش آمدید/ }),
  ).toBeVisible();
  const cookies = await context.cookies();
  expect(
    cookies.find((cookie) => cookie.name === "salonbook-dev-session")?.httpOnly,
  ).toBe(true);
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "salonbook-dev-session",
  );
  expect(await page.evaluate(() => Object.keys(localStorage))).not.toContain(
    "session",
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: /کاربر آزمایشی، خوش آمدید/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "خروج از حساب" }).click();
  await expect(
    page.getByRole("heading", { name: "این فضا برای شماست" }),
  ).toBeVisible();
  await page.goto("/login");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "ورود به حساب", exact: true }).click();
  await expect(
    page.getByText("رمز عبور را وارد کنید.", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    caret: "initial",
    path: "../docs/frontend/stage-10-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: /تغییر پوسته/ }).click();
  await page.getByRole("button", { name: /تغییر پوسته/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({
    caret: "initial",
    path: "../docs/frontend/stage-10-dark.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "رمز عبور را فراموش کرده‌ام" }).click();
  await expect(
    page.getByText("در این نسخه کد پیامکی ارسال نمی‌شود."),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
