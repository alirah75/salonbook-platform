from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class PlatformSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SALONBOOK_PLATFORM_", extra="forbid", hide_input_in_errors=True
    )
    environment: Literal["development", "production"] = "production"
    database_url: SecretStr
    auth_key: SecretStr
    public_origin: str

    @model_validator(mode="after")
    def safe(self) -> Self:
        from cryptography.fernet import Fernet

        Fernet(self.auth_key.get_secret_value().encode())
        origin = urlsplit(self.public_origin)
        if origin.path or origin.query or origin.fragment or origin.username or not origin.hostname:
            raise ValueError("Use an exact origin without a path or credentials.")
        if origin.scheme != "https" and not (
            self.environment == "development"
            and origin.scheme == "http"
            and origin.hostname in {"127.0.0.1", "localhost"}
        ):
            raise ValueError("Platform console requires HTTPS outside loopback development.")
        if make_url(self.database_url.get_secret_value()).drivername != "postgresql+psycopg":
            raise ValueError("Use the dedicated PostgreSQL psycopg platform login.")
        return self

    @property
    def cookie_name(self) -> str:
        return "__Secure-sb_platform" if self.environment == "production" else "sb_platform"
