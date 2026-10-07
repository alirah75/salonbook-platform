"""Stable HTTP error shapes; internal failure messages never become API content."""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.core.logging import logger, request_id_context


class FieldIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    code: str
    message: str = "Invalid value."


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    request_id: UUID
    details: list[FieldIssue] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail


class AppError(Exception):
    """Services may expose only deliberate, non-sensitive, user-facing messages."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        *,
        details: list[FieldIssue] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.public_message = message
        self.status_code = status_code
        self.details = details or []
        self.retry_after = retry_after


def error_response(
    code: str,
    message: str,
    status_code: int,
    *,
    details: list[FieldIssue] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    identifier = request_id_context.get()
    if identifier is None:
        raise RuntimeError("Request context middleware is required.")
    body = ErrorResponse(
        error=ErrorDetail(
            code=code, message=message, request_id=UUID(identifier), details=details or []
        )
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code, headers=headers)


async def application_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(
        exc.code,
        exc.public_message,
        exc.status_code,
        details=exc.details,
        headers={"Retry-After": str(exc.retry_after or 60)} if exc.status_code == 429 else None,
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    try:
        phrase = HTTPStatus(exc.status_code).phrase
    except ValueError:
        phrase = "Request failed"
    return error_response(f"http_{exc.status_code}", phrase, exc.status_code, headers=exc.headers)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Never echo Pydantic's input, ctx or a validator's exception message.
    details = [
        FieldIssue(field=".".join(str(part) for part in item["loc"]), code=item["type"])
        for item in exc.errors()
    ]
    return error_response("validation_error", "Request validation failed.", 422, details=details)


async def database_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning(
        "database.conflict", extra={"event": "database.conflict", "error_type": type(exc).__name__}
    )
    return error_response("data_conflict", "The operation conflicts with existing data.", 409)


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "database.unavailable",
        extra={"event": "database.unavailable", "error_type": type(exc).__name__},
    )
    return error_response(
        "service_unavailable",
        "The service is temporarily unavailable.",
        503,
        headers={"Retry-After": "5"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, application_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, database_conflict_handler)
    app.add_exception_handler(OperationalError, database_unavailable_handler)
    app.add_exception_handler(TimeoutError, database_unavailable_handler)


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in (
        (400, "Invalid request"),
        (401, "Authentication required"),
        (403, "Access denied"),
        (409, "Data conflict"),
        (422, "Validation failed"),
        (429, "Too many attempts"),
        (500, "Unexpected error"),
        (503, "Service unavailable"),
    )
}
