"""A disposable PostgreSQL lab. It never connects to an existing user database."""

import os
import secrets
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

POSTGRES_IMAGE = (
    "postgres:18-bookworm@sha256:3725f4e2499eef5134592b3b4ab79a543ed7f8e533b05b5b637af926630f6650"
)


@dataclass(frozen=True)
class PostgresLab:
    admin: Engine
    owner: Engine
    owner_url: str = field(repr=False)
    runtime_url: str = field(repr=False)


def _docker(*args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=180, env=env
    ).stdout.strip()


def execute_sql(connection: Connection, script: str) -> None:
    """Execute a trusted multi-statement migration/bootstrap script through psycopg."""
    connection.exec_driver_sql(script, execution_options={"no_parameters": True})


@contextmanager
def temporary_postgres(
    purpose: Literal[
        "stage02-tests",
        "stage03-preview",
        "stage04-preview",
        "stage05-preview",
        "stage06-preview",
        "stage07-preview",
        "stage08-preview",
        "stage09-preview",
        "stage10-preview",
        "stage11-preview",
        "stage12-preview",
        "stage14-preview",
    ] = "stage02-tests",
) -> Iterator[PostgresLab]:
    """Use a random loopback port, ephemeral credentials and a uniquely owned container."""
    name = f"salonbook-{purpose}-{uuid4().hex[:12]}"
    password = secrets.token_urlsafe(32)
    container_env = dict(os.environ, POSTGRES_PASSWORD=password)
    container_id = _docker(
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--label",
        f"salonbook.purpose={purpose}",
        "--publish",
        "127.0.0.1::5432",
        "--env",
        "POSTGRES_PASSWORD",
        "--env",
        "POSTGRES_DB=salonbook_test",
        POSTGRES_IMAGE,
        env=container_env,
    )
    admin: Engine | None = None
    owner: Engine | None = None
    try:
        port = int(_docker("port", container_id, "5432/tcp").rsplit(":", 1)[1])
        admin_url = URL.create(
            "postgresql+psycopg",
            username="postgres",
            password=password,
            host="127.0.0.1",
            port=port,
            database="salonbook_test",
        )
        admin = create_engine(admin_url, pool_pre_ping=True)
        deadline = time.monotonic() + 60
        while True:
            try:
                with admin.connect() as connection:
                    connection.execute(text("SELECT 1"))
                break
            except OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Disposable PostgreSQL did not become ready") from None
                time.sleep(0.25)
        # Generated base64url secrets are quoted by the driver's SQL-literal adapter.
        from psycopg import sql

        with admin.begin() as connection:
            for role in ("salonbook_test_owner", "salonbook_test_runtime"):
                statement = sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
                connection.exec_driver_sql(statement.as_string())
            connection.exec_driver_sql(
                "GRANT CREATE ON DATABASE salonbook_test TO salonbook_test_owner"
            )
            connection.exec_driver_sql("GRANT CREATE ON SCHEMA public TO salonbook_test_owner")
        owner_url = admin_url.set(username="salonbook_test_owner").render_as_string(
            hide_password=False
        )
        runtime_url = admin_url.set(username="salonbook_test_runtime").render_as_string(
            hide_password=False
        )
        owner = create_engine(owner_url)
        yield PostgresLab(admin, owner, owner_url, runtime_url)
    finally:
        if owner is not None:
            owner.dispose()
        if admin is not None:
            admin.dispose()
        _docker("stop", "--time", "3", container_id)
