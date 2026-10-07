const forwarded = [
  "content-type",
  "cookie",
  "origin",
  "x-csrf-token",
  "x-request-id",
  "idempotency-key",
  "accept",
];
const MAX_BODY = 65536;
function failure(status: number, code: string) {
  return Response.json(
    { error: { code, message: "Request unavailable", details: [] } },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

export async function devProxy(
  request: Request,
  path: string[],
  environment = process.env,
  platform = false,
) {
  const configuredOrigin = platform
    ? environment.SALONBOOK_DEV_PLATFORM_ORIGIN
    : environment.SALONBOOK_DEV_API_ORIGIN;
  // This loopback bridge is never a production tenant router or a trust-all proxy.
  if (environment.NODE_ENV === "production" || !configuredOrigin)
    return failure(503, "development_proxy_disabled");
  let upstream: URL;
  try {
    upstream = new URL(configuredOrigin);
  } catch {
    return failure(503, "invalid_development_upstream");
  }
  if (
    upstream.protocol !== "http:" ||
    !["127.0.0.1", "localhost"].includes(upstream.hostname) ||
    upstream.username ||
    upstream.password ||
    upstream.pathname !== "/" ||
    upstream.search ||
    upstream.hash
  )
    return failure(503, "invalid_development_upstream");
  const host = request.headers.get("host") ?? "";
  if (!/^(127\.0\.0\.1|localhost):3000$/.test(host))
    return failure(400, "invalid_development_host");
  if (
    path.length === 0 ||
    path.some(
      (segment) =>
        !/^[a-zA-Z0-9_.-]{1,160}$/.test(segment) ||
        segment === "." ||
        segment === "..",
    )
  )
    return failure(400, "invalid_api_path");
  const mutation = !["GET", "HEAD"].includes(request.method);
  if (mutation && request.headers.get("origin") !== `http://${host}`)
    return failure(403, "csrf_failed");
  const headers = new Headers();
  for (const name of forwarded) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("Host", host);
  let body: ArrayBuffer | undefined;
  if (mutation && request.body) {
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.length;
      if (size > MAX_BODY) {
        await reader.cancel();
        return failure(413, "payload_too_large");
      }
      chunks.push(part.value);
    }
    const combined = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      combined.set(chunk, offset);
      offset += chunk.length;
    }
    body = combined.buffer;
  }
  const target = new URL(
    `${platform ? "/platform" : ""}/api/v1/${path.map(encodeURIComponent).join("/")}`,
    upstream,
  );
  target.search = new URL(request.url).search;
  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(15000),
    });
    if (response.status >= 300 && response.status < 400)
      return failure(502, "unexpected_redirect");
    const output = new Headers({ "Cache-Control": "private, no-store" });
    for (const name of [
      "content-type",
      "x-request-id",
      "idempotency-replayed",
      "retry-after",
    ]) {
      const value = response.headers.get(name);
      if (value) output.set(name, value);
    }
    for (const cookie of response.headers.getSetCookie())
      output.append("Set-Cookie", cookie);
    return new Response(response.body, {
      status: response.status,
      headers: output,
    });
  } catch {
    return failure(503, "network_error");
  }
}
