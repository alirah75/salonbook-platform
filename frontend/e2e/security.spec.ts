import { test, expect } from "@playwright/test";
import { randomInt, randomUUID } from "node:crypto";

test("stored markup remains text and foreign-origin mutations are rejected", async ({
  page,
}) => {
  const name = '<img data-xss src=x onerror="window.__salonXss=1">';
  const phone = `0916${randomInt(1000000, 9999999)}`;
  const password = `Security test ${randomUUID()}`;
  const pre = await (await page.request.get("/api/v1/auth/csrf")).json();
  const headers = {
    Origin: "http://127.0.0.1:3000",
    "X-CSRF-Token": pre.csrf_token,
  };
  expect(
    (
      await page.request.post("/api/v1/auth/register", {
        headers,
        data: { phone, password, display_name: name },
      })
    ).status(),
  ).toBe(202);
  expect(
    (
      await page.request.post("/api/v1/auth/login", {
        headers,
        data: { phone, password },
      })
    ).status(),
  ).toBe(200);
  await page.goto("/account");
  await expect(page.getByText(name, { exact: true })).toBeVisible();
  await expect(page.locator("img[data-xss]")).toHaveCount(0);
  expect(
    await page.evaluate(() => Reflect.get(window, "__salonXss")),
  ).toBeUndefined();
  const session = await (await page.request.get("/api/v1/auth/me")).json();
  const rejected = await page.request.post("/api/v1/auth/logout", {
    headers: {
      Origin: "https://evil.example",
      "X-CSRF-Token": session.csrf_token,
    },
    data: {},
  });
  expect(rejected.status()).toBe(403);
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);
});

test("production CSP permits hydration but blocks injected script and uses fresh nonces", async ({
  page,
}) => {
  const origin = process.env.SALONBOOK_SECURITY_WEB_ORIGIN;
  test.skip(
    !origin,
    "Run a built Next server and set SALONBOOK_SECURITY_WEB_ORIGIN.",
  );
  const violations: string[] = [];
  page.on("console", (message) => {
    if (message.text().includes("Content Security Policy"))
      violations.push(message.text());
  });
  const first = await page.goto(origin!);
  const policy = first!.headers()["content-security-policy"];
  expect(policy).toContain("strict-dynamic");
  expect(policy).not.toContain("unsafe-eval");
  expect(first!.headers()["cache-control"]).toContain("no-store");
  expect(first!.headers()["x-powered-by"]).toBeUndefined();
  const nonce = policy.match(/'nonce-([^']+)'/)![1];
  const inline = await page
    .locator("script:not([src])")
    .evaluateAll((nodes) =>
      nodes.map((node) => (node as HTMLScriptElement).nonce),
    );
  expect(inline.length).toBeGreaterThan(0);
  expect(inline.every((value) => value === nonce)).toBe(true);
  await page.getByRole("button", { name: /تغییر پوسته/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(violations).toEqual([]);
  // Inject through the HTML parser. DevTools evaluation can inherit a trusted
  // script context and is not representative of stored/reflected HTML injection.
  await page.route(`${origin}/`, async (route) => {
    const response = await route.fetch();
    const html = await response.text();
    await route.fulfill({
      response,
      body: html.replace(
        "</head>",
        "<script>window.__injectedScriptRan = true</script></head>",
      ),
    });
  });
  const second = await page.reload();
  expect(
    await page.evaluate(() => Reflect.get(window, "__injectedScriptRan")),
  ).toBeUndefined();
  await expect.poll(() => violations.length).toBeGreaterThan(0);
  expect(second!.headers()["content-security-policy"]).not.toBe(policy);
});
