from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from app.core.config import Settings

TEST_URL = "postgresql+psycopg://runtime:configuration-test-secret@127.0.0.1/salonbook_test"


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr(TEST_URL),
        "auth_key": SecretStr(Fernet.generate_key().decode()),
    }
    values.update(overrides)
    return Settings(**values)


def test_environment_settings_are_loaded_and_secrets_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SALONBOOK_DATABASE_URL", TEST_URL)
    monkeypatch.setenv("SALONBOOK_DB_POOL_SIZE", "7")
    monkeypatch.setenv("SALONBOOK_ALLOWED_HOSTS", '["localhost","salon.example"]')
    config = Settings()
    assert config.db_pool_size == 7
    assert config.allowed_hosts == ("localhost", "salon.example")
    assert "configuration-test-secret" not in repr(config)
    assert "configuration-test-secret" not in config.model_dump_json()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///unsafe.db",
        "postgresql://runtime:secret@localhost/db",
        "not-a-url-with-secret",
        "postgresql+psycopg://",
    ],
)
def test_invalid_database_urls_fail_without_echoing_secret(url: str) -> None:
    with pytest.raises(ValidationError) as caught:
        settings(database_url=SecretStr(url))
    assert url not in str(caught.value)


@pytest.mark.parametrize(
    "hosts", [(), ("*",), ("https://salon.example",), ("salon.example:8000",), ("salon.*",)]
)
def test_hosts_must_be_explicit(hosts: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        settings(allowed_hosts=hosts)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://salon.example/path",
        "https://user:secret@salon.example",
        "https://salon.example?secret=x",
        "https://salon.example/",
    ],
)
def test_cors_requires_exact_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        settings(cors_origins=(origin,))


def test_production_requires_explicit_hosts_https_origins_and_private_docs() -> None:
    with pytest.raises(ValidationError):
        settings(environment="production")
    with pytest.raises(ValidationError):
        settings(
            environment="production",
            allowed_hosts=("salon.example",),
            cors_origins=("http://salon.example",),
        )
    with pytest.raises(ValidationError):
        settings(environment="production", allowed_hosts=("salon.example",), docs_enabled=True)
    config = settings(environment="production", allowed_hosts=("salon.example",))
    assert config.documentation_enabled is False


@pytest.mark.parametrize(
    "overrides",
    [{"db_pool_size": 0}, {"db_lock_timeout_ms": 6000}, {"db_idle_transaction_timeout_ms": 1000}],
)
def test_connection_limits_are_validated(overrides: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        settings(**overrides)
