"""Pure ASGI request context and safe exception boundary."""

import asyncio
import time
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response
from app.core.logging import logger, request_id_context


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, production: bool = False) -> None:
        self.app = app
        self.production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        token = request_id_context.set(request_id)
        start = time.perf_counter()
        status = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Cache-Control"] = "no-store"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                if self.production:
                    headers["Content-Security-Policy"] = (
                        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                    )
                    if scope.get("scheme") == "https":
                        headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        finally:
            route = getattr(scope.get("route"), "path", "<unmatched>")
            method = scope.get("method", "OTHER")
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
                method = "OTHER"
            logger.info(
                "request.completed",
                extra={
                    "event": "request.completed",
                    "method": method,
                    "route": route,
                    "status_code": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            request_id_context.reset(token)


class RequestLimitsMiddleware:
    """Bound actual ASGI bytes before JSON parsing, including chunked requests.

    No upload endpoint exists. Bodies are bounded independently of Content-Type,
    HTTP method and caller-supplied Content-Length. Slow body reads have a deadline.
    """

    def __init__(
        self,
        app: ASGIApp,
        production: bool = False,
        max_bytes: int = 65536,
        body_seconds: float = 10,
    ) -> None:
        self.app, self.production = app, production
        self.max_bytes, self.body_seconds = max_bytes, body_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def reject(code: str, status: int) -> None:
            await error_response(code, "Request rejected.", status)(scope, receive, send)

        if self.production and scope.get("scheme") != "https":
            await reject("https_required", 400)
            return
        lengths = [v for k, v in scope["headers"] if k.lower() == b"content-length"]
        if len(lengths) > 1 or (lengths and (not lengths[0].isdigit() or len(lengths[0]) > 10)):
            await reject("invalid_content_length", 400)
            return
        if lengths and int(lengths[0]) > self.max_bytes:
            await reject("payload_too_large", 413)
            return
        headers = {k.lower(): v.lower() for k, v in scope["headers"]}
        if headers.get(b"content-encoding", b"identity") != b"identity":
            await reject("unsupported_media_type", 415)
            return
        if len(scope.get("query_string", b"")) > 8192:
            await reject("uri_too_long", 414)
            return
        chunks = []
        size = 0
        try:
            async with asyncio.timeout(self.body_seconds):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    size += len(chunk)
                    if size > self.max_bytes:
                        await reject("payload_too_large", 413)
                        return
                    chunks.append(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await reject("request_timeout", 408)
            return
        if size and headers.get(b"content-type", b"").split(b";")[0].strip() != b"application/json":
            await reject("unsupported_media_type", 415)
            return
        body = b"".join(chunks)
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class SafeExceptionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def track_response(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response)
        except Exception:
            logger.exception("request.failed", extra={"event": "request.failed"})
            if started:
                # A streamed response cannot be replaced. Do not forward the private exception.
                raise RuntimeError("Response interrupted") from None
            response = error_response("internal_error", "An unexpected error occurred.", 500)
            await response(scope, receive, send)
