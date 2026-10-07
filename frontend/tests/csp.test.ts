// @vitest-environment node
import { expect, it } from "vitest";
import { contentSecurityPolicy } from "@/lib/csp";
import { proxy } from "@/proxy";
import { NextRequest } from "next/server";

it("production policy has nonce scripts, no eval or inline scripts, and no embedding", () => {
  const policy = contentSecurityPolicy("randomNonce", false);
  expect(policy).toContain(
    "script-src 'self' 'nonce-randomNonce' 'strict-dynamic';",
  );
  expect(policy).not.toContain("unsafe-eval");
  expect(policy).toContain("frame-ancestors 'none'");
  expect(policy).toContain("base-uri 'none'");
  expect(contentSecurityPolicy("randomNonce", true)).toContain("unsafe-eval");
});
it("uses independent server nonces and overwrites forged client CSP headers", () => {
  const request = new NextRequest("https://salon.example/dashboard", {
    headers: {
      "x-nonce": "attacker",
      "Content-Security-Policy": "script-src 'unsafe-inline'",
    },
  });
  const one = proxy(request),
    two = proxy(request);
  expect(one.headers.get("Content-Security-Policy")).not.toContain("attacker");
  expect(one.headers.get("Content-Security-Policy")).not.toEqual(
    two.headers.get("Content-Security-Policy"),
  );
  expect(one.headers.get("Cache-Control")).toBe("private, no-store");
  expect(one.headers.get("x-middleware-request-content-security-policy")).toBe(
    one.headers.get("Content-Security-Policy"),
  );
});
