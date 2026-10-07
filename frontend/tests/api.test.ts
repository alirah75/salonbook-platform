import { afterEach, describe, expect, it, vi } from "vitest";
import { api, platformApi, ApiError, errorMessage } from "@/lib/api";
import { loginSchema, registerSchema } from "@/lib/forms";

afterEach(() => vi.unstubAllGlobals());
describe("API boundary", () => {
  it("separates platform routes and session expiry from salon authentication", async () => {
    const tenantExpired = vi.fn();
    const platformExpired = vi.fn();
    window.addEventListener("salonbook:session-expired", tenantExpired);
    window.addEventListener("salonbook:platform-expired", platformExpired);
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        Response.json({ error: { code: "unauthenticated" } }, { status: 401 }),
      );
    vi.stubGlobal("fetch", fetcher);
    try {
      await expect(platformApi("/salons")).rejects.toBeInstanceOf(ApiError);
      expect(fetcher.mock.calls[0][0]).toBe("/platform/api/v1/salons");
      expect(platformExpired).toHaveBeenCalledTimes(1);
      expect(tenantExpired).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("salonbook:session-expired", tenantExpired);
      window.removeEventListener("salonbook:platform-expired", platformExpired);
    }
  });
  it("sends cookies and CSRF only to the same-origin API and never retries a mutation", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetcher);
    await api("/auth/logout", {
      method: "POST",
      body: {},
      csrf: "test-csrf",
      idempotencyKey: "stable-key",
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [path, options] = fetcher.mock.calls[0];
    expect(path).toBe("/api/v1/auth/logout");
    expect(options).toMatchObject({
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      body: "{}",
    });
    expect(options.headers.get("X-CSRF-Token")).toBe("test-csrf");
    expect(options.headers.get("Idempotency-Key")).toBe("stable-key");
    await expect(api("//external.example/steal")).rejects.toThrow(
      "invalid_api_path",
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("keeps safe error details and never displays arbitrary backend text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json(
          {
            error: { code: "internal_error", message: "secret SQL details" },
          },
          { status: 500, headers: { "X-Request-ID": "safe-id" } },
        ),
      ),
    );
    const result = await api("/auth/me").catch((error: ApiError) => error);
    expect(result).toBeInstanceOf(ApiError);
    expect((result as ApiError).requestId).toBe("safe-id");
    expect(errorMessage(result)).not.toContain("secret");
  });
  it("invalidates auth on a private 401", async () => {
    const listener = vi.fn();
    window.addEventListener("salonbook:session-expired", listener);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json(
            { error: { code: "unauthenticated" } },
            { status: 401 },
          ),
        ),
    );
    await expect(api("/auth/sessions")).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener("salonbook:session-expired", listener);
  });
  it("reports transport failure without resubmitting", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    vi.stubGlobal("fetch", fetcher);
    await expect(
      api("/auth/register", { method: "POST", body: {} }),
    ).rejects.toMatchObject({ code: "network_error" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
describe("mobile forms", () => {
  it.each(["۰۹۱۲۳۴۵۶۷۸۹", "٠٩١٢٣٤٥٦٧٨٩", "0912 345 6789"])(
    "accepts and normalizes %s",
    (phone) => {
      expect(loginSchema.parse({ phone, password: "secret" }).phone).toBe(
        "09123456789",
      );
    },
  );
  it("rejects non-mobile input and short registration passwords", () => {
    expect(
      loginSchema.safeParse({ phone: "person@example.com", password: "secret" })
        .success,
    ).toBe(false);
    expect(
      registerSchema.safeParse({
        phone: "09123456789",
        password: "short",
        display_name: "نام",
      }).success,
    ).toBe(false);
    expect(
      registerSchema.parse({
        phone: "09123456789",
        password: "a very long passphrase",
        display_name: "  نام  ",
      }).display_name,
    ).toBe("نام");
  });
});
