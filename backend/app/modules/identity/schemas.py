from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.modules.identity.phone import normalize_mobile


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PhoneInput(InputModel):
    phone: str = Field(min_length=1, max_length=32, examples=["09123456789"])

    @field_validator("phone")
    @classmethod
    def canonical_phone(cls, value: str) -> str:
        return normalize_mobile(value)


class LoginInput(PhoneInput):
    password: SecretStr = Field(min_length=1, max_length=128)


class RegisterInput(LoginInput):
    display_name: str = Field(min_length=1, max_length=160)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 15:
            raise ValueError("Use at least 15 characters.")
        return value

    @field_validator("display_name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A name is required.")
        return value.strip()


class PasswordChangeInput(InputModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=15, max_length=128)


class MessageResponse(BaseModel):
    message: str = (
        "Registration request accepted. You can sign in with your mobile number and password."
    )


class CsrfResponse(BaseModel):
    csrf_token: str


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    phone: str | None
    phone_verified: bool
    display_name: str
    roles: list[str]


class SessionResponse(BaseModel):
    user: UserResponse
    csrf_token: str
    expires_at: datetime


class SessionItem(BaseModel):
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool


SessionList = Annotated[list[SessionItem], Field(max_length=100)]
