"""Validated environment configuration; secrets never appear in repr or errors."""

from typing import Literal, Self
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SALONBOOK_",
        env_file=None,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = Field(repr=False)
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    cors_origins: tuple[str, ...] = ()
    docs_enabled: bool | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_timeout_seconds: int = Field(default=3, ge=1, le=30)
    db_pool_recycle_seconds: int = Field(default=900, ge=60, le=3600)
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=10)
    db_statement_timeout_ms: int = Field(default=5000, ge=100, le=30000)
    db_lock_timeout_ms: int = Field(default=2000, ge=100, le=10000)
    db_idle_transaction_timeout_ms: int = Field(default=15000, ge=1000, le=60000)
    auth_key: SecretStr | None = Field(default=None, repr=False)
    auth_public_port: int | None = Field(default=None, ge=1, le=65535)
    auth_session_hours: int = Field(default=24, ge=1, le=168)
    auth_idle_minutes: int = Field(default=120, ge=5, le=240)
    auth_staff_session_hours: int = Field(default=8, ge=1, le=24)
    auth_staff_idle_minutes: int = Field(default=30, ge=5, le=60)
    auth_attempt_limit: int = Field(default=10, ge=3, le=100)
    auth_ip_limit: int = Field(default=50, ge=10, le=1000)
    auth_window_seconds: int = Field(default=900, ge=60, le=3600)
    api_ip_limit: int = Field(default=240, ge=10, le=10000)
    api_window_seconds: int = Field(default=60, ge=10, le=300)
    mock_payments_enabled: bool = False
    payments_mode: Literal["test", "live"] = "test"

    @field_validator("auth_key")
    @classmethod
    def valid_auth_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            try:
                Fernet(value.get_secret_value().encode("ascii"))
            except (ValueError, UnicodeError):
                raise ValueError("Use a generated Fernet key for authentication secrets.") from None
        return value

    @field_validator("database_url")
    @classmethod
    def valid_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = url.drivername == "postgresql+psycopg" and bool(
                url.host and url.username and url.database
            )
            _ = url.port
        except (ValueError, TypeError, ArgumentError):
            valid = False
        if not valid:
            raise ValueError("Use a complete postgresql+psycopg URL for the runtime login.")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def valid_hosts(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        if not hosts:
            raise ValueError("At least one explicit host is required.")
        normalized = tuple(host.lower() for host in hosts)
        for host in normalized:
            if not host or host == "*" or any(char in host for char in "/: @\\\r\n"):
                raise ValueError("Hosts must be explicit names without schemes or ports.")
            if "*" in host and not (
                host.startswith("*.") and host.count("*") == 1 and len(host) > 2
            ):
                raise ValueError("Only explicit subdomain patterns are accepted.")
        return tuple(dict.fromkeys(normalized))

    @field_validator("cors_origins")
    @classmethod
    def valid_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
                or any(char in origin for char in " \r\n\\")
            ):
                raise ValueError(
                    "CORS origins must be exact http(s) origins without paths or credentials."
                )
            try:
                _ = parsed.port
            except ValueError:
                raise ValueError("Invalid CORS origin port.") from None
        return tuple(dict.fromkeys(origins))

    @model_validator(mode="after")
    def coherent_settings(self) -> Self:
        if self.db_lock_timeout_ms >= self.db_statement_timeout_ms:
            raise ValueError("Lock timeout must be below statement timeout.")
        if self.db_idle_transaction_timeout_ms <= self.db_statement_timeout_ms:
            raise ValueError("Idle transaction timeout must exceed statement timeout.")
        if self.environment == "production":
            if self.mock_payments_enabled:
                raise ValueError("The mock payment simulator is disabled in production.")
            if self.auth_key is None:
                raise ValueError("Production requires an authentication encryption key.")
            if self.auth_public_port is not None:
                raise ValueError("Production public origin uses the standard HTTPS port.")
            if self.docs_enabled is True:
                raise ValueError("Public interactive documentation is disabled in production.")
            if any(host in ("localhost", "127.0.0.1", "testserver") for host in self.allowed_hosts):
                raise ValueError("Production requires explicitly configured salon hosts.")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production CORS origins require HTTPS.")
        return self

    @property
    def documentation_enabled(self) -> bool:
        return (
            self.docs_enabled if self.docs_enabled is not None else self.environment != "production"
        )
