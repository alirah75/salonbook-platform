// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import { devProxy } from "@/lib/dev-proxy";
const environment = {
  NODE_ENV: "development",
  SALONBOOK_DEV_API_ORIGIN: "http://127.0.0.1:8000",
} as NodeJS.ProcessEnv;
afterEach(() => vi.unstubAllGlobals());
it("uses the separate platform upstream and keeps its bridge closed in production", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ items: [] }));
  vi.stubGlobal("fetch", fetcher);
  const request = new Request("http://127.0.0.1:3000/platform/api/v1/salons", {
    headers: { Host: "127.0.0.1:3000" },
  });
  const config = {
    ...environment,
    SALONBOOK_DEV_PLATFORM_ORIGIN: "http://127.0.0.1:8001",
  };
  expect((await devProxy(request, ["salons"], config, true)).status).toBe(200);
  expect(String(fetcher.mock.calls[0][0])).toBe(
    "http://127.0.0.1:8001/platform/api/v1/salons",
  );
  expect(
    (
      await devProxy(
        request,
        ["salons"],
        { ...config, NODE_ENV: "production" },
        true,
      )
    ).status,
  ).toBe(503);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("forwards the validated browser host and CSRF, dropping untrusted tenant and proxy headers", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    Response.json(
      { ok: true },
      {
        headers: {
          "Set-Cookie":
            "salonbook-dev-session=test; HttpOnly; Path=/; SameSite=Lax",
        },
      },
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  const result = await devProxy(
    new Request("http://localhost:3000/api/v1/auth/login", {
      method: "POST",
      body: "{}",
      headers: {
        Host: "localhost:3000",
        Origin: "http://localhost:3000",
        "X-CSRF-Token": "token",
        "X-Tenant-ID": "fake",
        "X-Forwarded-Host": "evil.example",
      },
    }),
    ["auth", "login"],
    environment,
  );
  expect(result.status).toBe(200);
  expect(result.headers.get("Cache-Control")).toContain("no-store");
  expect(result.headers.get("Set-Cookie")).toContain("HttpOnly");
  const headers = fetcher.mock.calls[0][1].headers as Headers;
  expect(headers.get("Host")).toBe("localhost:3000");
  expect(headers.get("Origin")).toBe("http://localhost:3000");
  expect(headers.get("X-Tenant-ID")).toBeNull();
  expect(headers.get("X-Forwarded-Host")).toBeNull();
});
it("rejects cross-origin mutations and disables the bridge in production", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const request = new Request("http://localhost:3000/api/v1/auth/login", {
    method: "POST",
    headers: { Host: "localhost:3000", Origin: "https://evil.example" },
  });
  expect((await devProxy(request, ["auth", "login"], environment)).status).toBe(
    403,
  );
  expect(
    (
      await devProxy(request, ["auth", "login"], {
        ...environment,
        NODE_ENV: "production",
      })
    ).status,
  ).toBe(503);
  expect(
    (
      await devProxy(request, ["auth"], {
        ...environment,
        SALONBOOK_DEV_API_ORIGIN: "http://external.example",
      })
    ).status,
  ).toBe(503);
  expect(fetcher).not.toHaveBeenCalled();
});
