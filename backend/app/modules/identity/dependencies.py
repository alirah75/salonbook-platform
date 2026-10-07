from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from app.core.errors import AppError
from app.dependencies.runtime import RuntimeDependency
from app.modules.access.service import Principal
from app.modules.identity.context import AuthContext, resolve_context
from app.modules.identity.runtime import AuthRuntime


def get_auth(runtime: RuntimeDependency) -> AuthRuntime:
    if runtime.auth is None:
        raise AppError("auth_unavailable", "Authentication is not configured.", 503)
    return runtime.auth


AuthDependency = Annotated[AuthRuntime, Depends(get_auth)]


def get_context(request: Request, runtime: RuntimeDependency, auth: AuthDependency) -> AuthContext:
    context = resolve_context(request, runtime.database, runtime.settings)
    auth.limiter.check_api(context)
    return context


ContextDependency = Annotated[AuthContext, Depends(get_context)]


def cookie_name(request: Request) -> str:
    return "__Host-salonbook-session" if request.url.scheme == "https" else "salonbook-dev-session"


def preauth_cookie_name(request: Request) -> str:
    return "__Host-salonbook-preauth" if request.url.scheme == "https" else "salonbook-dev-preauth"


def session_token(request: Request) -> str:
    return request.cookies.get(cookie_name(request), "")


def check_origin(request: Request, context: AuthContext) -> None:
    if (
        request.headers.get("origin") != context.origin
        or request.url.scheme != context.origin.split(":", 1)[0]
    ):
        raise AppError("csrf_failed", "Request verification failed.", 403)
    if (
        request.method != "DELETE"
        and request.headers.get("content-type", "").split(";")[0].strip() != "application/json"
    ):
        raise AppError("unsupported_media_type", "Use application/json.", 415)


def public_mutation(
    request: Request,
    context: ContextDependency,
    auth: AuthDependency,
    csrf_token: Annotated[
        str | None, Header(alias="X-CSRF-Token", description="Token from GET /auth/csrf")
    ] = None,
) -> None:
    check_origin(request, context)
    if not auth.security.valid_preauth(
        context.tenant_id,
        request.cookies.get(preauth_cookie_name(request), ""),
        csrf_token or "",
    ):
        raise AppError("csrf_failed", "Request verification failed.", 403)


def private_mutation(
    request: Request,
    context: ContextDependency,
    csrf_token: Annotated[
        str | None,
        Header(alias="X-CSRF-Token", description="Session CSRF token from login or GET /auth/me"),
    ] = None,
) -> None:
    check_origin(request, context)
    if len(csrf_token or "") != 64:
        raise AppError("csrf_failed", "Request verification failed.", 403)


def get_principal(request: Request, context: ContextDependency, auth: AuthDependency) -> Principal:
    return auth.sessions.principal(context, session_token(request))


PrincipalDependency = Annotated[Principal, Depends(get_principal)]


def require_permission(
    permission: str,
    *,
    line_parameter: str | None = None,
    owner_parameter: str | None = None,
    verified: bool = False,
) -> Callable[..., Principal]:
    """HTTP guard; services must re-check permissions within their write transaction."""

    def dependency(request: Request, principal: PrincipalDependency) -> Principal:
        try:
            line = UUID(str(request.path_params[line_parameter])) if line_parameter else None
            owner = UUID(str(request.path_params[owner_parameter])) if owner_parameter else None
        except (ValueError, KeyError):
            raise AppError("forbidden", "Access denied.", 403) from None
        if verified:
            principal.require_verified()
        principal.require(permission, line_id=line, owner_id=owner)
        return principal

    return dependency
