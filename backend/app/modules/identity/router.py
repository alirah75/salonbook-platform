from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.modules.identity.dependencies import (
    AuthDependency,
    ContextDependency,
    cookie_name,
    preauth_cookie_name,
    private_mutation,
    public_mutation,
    session_token,
)
from app.modules.identity.schemas import (
    CsrfResponse,
    LoginInput,
    MessageResponse,
    PasswordChangeInput,
    RegisterInput,
    SessionItem,
    SessionResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
PUBLIC = [Depends(public_mutation)]
PRIVATE = [Depends(private_mutation)]


def clear_session(response: Response, request: Request) -> None:
    response.delete_cookie(
        cookie_name(request),
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )


@router.get("/csrf", response_model=CsrfResponse)
def csrf(
    request: Request, response: Response, context: ContextDependency, auth: AuthDependency
) -> CsrfResponse:
    token = auth.security.preauth_csrf(context.tenant_id)
    response.set_cookie(
        preauth_cookie_name(request),
        token,
        max_age=600,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )
    return CsrfResponse(csrf_token=token)


@router.post("/register", response_model=MessageResponse, status_code=202, dependencies=PUBLIC)
def register(
    payload: RegisterInput, context: ContextDependency, auth: AuthDependency
) -> MessageResponse:
    auth.limiter.check(context, "register", payload.phone)
    auth.accounts.register(context, payload)
    return MessageResponse()


@router.post("/login", response_model=SessionResponse, dependencies=PUBLIC)
def login(
    payload: LoginInput,
    request: Request,
    response: Response,
    context: ContextDependency,
    auth: AuthDependency,
) -> SessionResponse:
    auth.limiter.check(context, "login", payload.phone)
    raw, result = auth.accounts.login(
        context,
        payload.phone,
        payload.password.get_secret_value(),
        session_token(request),
    )
    response.set_cookie(
        cookie_name(request),
        raw,
        max_age=max(1, int((result.expires_at - datetime.now(UTC)).total_seconds())),
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        preauth_cookie_name(request),
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )
    return result


@router.get("/me", response_model=SessionResponse)
def me(request: Request, context: ContextDependency, auth: AuthDependency) -> SessionResponse:
    return auth.sessions.current(context, session_token(request))


@router.post("/logout", status_code=204, dependencies=PRIVATE)
def logout(
    request: Request, response: Response, context: ContextDependency, auth: AuthDependency
) -> None:
    auth.sessions.revoke(context, session_token(request), request.headers["x-csrf-token"])
    clear_session(response, request)


@router.post("/logout-all", status_code=204, dependencies=PRIVATE)
def logout_all(
    request: Request, response: Response, context: ContextDependency, auth: AuthDependency
) -> None:
    auth.sessions.revoke(
        context, session_token(request), request.headers["x-csrf-token"], all_sessions=True
    )
    clear_session(response, request)


@router.get("/sessions", response_model=list[SessionItem])
def sessions(
    request: Request, context: ContextDependency, auth: AuthDependency
) -> list[SessionItem]:
    return auth.sessions.list_sessions(context, session_token(request))


@router.delete("/sessions/{identifier}", status_code=204, dependencies=PRIVATE)
def revoke_session(
    identifier: UUID, request: Request, context: ContextDependency, auth: AuthDependency
) -> None:
    auth.sessions.revoke(
        context, session_token(request), request.headers["x-csrf-token"], target=identifier
    )


@router.post("/change-password", status_code=204, dependencies=PRIVATE)
def change_password(
    payload: PasswordChangeInput,
    request: Request,
    response: Response,
    context: ContextDependency,
    auth: AuthDependency,
) -> None:
    auth.limiter.check(context, "change_password", session_token(request))
    auth.accounts.change_password(
        context,
        session_token(request),
        request.headers["x-csrf-token"],
        payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(),
    )
    clear_session(response, request)
