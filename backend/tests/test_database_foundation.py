from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import Settings
from app.db.database import Database as ApplicationDatabase
from app.db.database import DatabaseNotReady
from app.db.schema import REQUIRED_SCHEMA_REVISION
from app.main import create_app
from app.modules.catalog.models import Line
from tests.conftest import Database

pytestmark = pytest.mark.postgres


@pytest.fixture
def runtime_database(database: Database) -> Iterator[ApplicationDatabase]:
    instance = ApplicationDatabase(
        Settings(
            environment="test",
            database_url=SecretStr(database.lab.runtime_url),
            db_pool_size=1,
            db_max_overflow=0,
        )
    )
    try:
        yield instance
    finally:
        instance.dispose()


def test_ready_revision_and_restricted_version_view(
    database: Database, runtime_database: ApplicationDatabase
) -> None:
    assert ScriptDirectory.from_config(Config("alembic.ini")).get_current_head() == (
        REQUIRED_SCHEMA_REVISION
    )
    runtime_database.validate_ready()
    with database.runtime.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM app_schema_revision")) == (
            REQUIRED_SCHEMA_REVISION
        )
    for statement in (
        "SELECT * FROM alembic_version",
        "UPDATE app_schema_revision SET version_num = 'unauthorized'",
    ):
        with pytest.raises(DBAPIError), database.runtime.begin() as connection:
            connection.execute(text(statement))


@pytest.mark.parametrize("role", ["admin", "owner"])
def test_elevated_and_owner_logins_cannot_serve_requests(database: Database, role: str) -> None:
    engine = database.lab.admin if role == "admin" else database.lab.owner
    instance = ApplicationDatabase(
        Settings(database_url=SecretStr(engine.url.render_as_string(hide_password=False)))
    )
    try:
        with pytest.raises(DatabaseNotReady, match="unsafe_database_role"):
            instance.validate_ready()
    finally:
        instance.dispose()


def test_schema_mismatch_blocks_readiness_and_transactions(
    database: Database,
    runtime_database: ApplicationDatabase,
    tenants: tuple[dict[str, UUID], dict[str, UUID]],
) -> None:
    with database.lab.owner.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'outdated'"))
    try:
        with pytest.raises(DatabaseNotReady, match="schema_revision_mismatch"):
            runtime_database.validate_ready()
        with (
            pytest.raises(DatabaseNotReady, match="schema_revision_mismatch"),
            runtime_database.transaction(tenants[0]["tenant"]),
        ):
            pytest.fail("An incompatible schema must not open a service transaction")
    finally:
        with database.lab.owner.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": REQUIRED_SCHEMA_REVISION},
            )
    runtime_database.validate_ready()


def test_missing_force_rls_blocks_readiness(
    database: Database, runtime_database: ApplicationDatabase
) -> None:
    with database.lab.owner.begin() as connection:
        connection.execute(text("ALTER TABLE lines NO FORCE ROW LEVEL SECURITY"))
    try:
        with pytest.raises(DatabaseNotReady, match="tenant_isolation_missing"):
            runtime_database.validate_ready()
    finally:
        with database.lab.owner.begin() as connection:
            connection.execute(text("ALTER TABLE lines FORCE ROW LEVEL SECURITY"))
    runtime_database.validate_ready()


def test_commit_and_rollback_are_service_boundaries(
    runtime_database: ApplicationDatabase, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    tenant = tenants[0]["tenant"]
    committed_id, rolled_back_id = uuid4(), uuid4()
    with runtime_database.transaction(tenant) as session:
        session.add(Line(tenant_id=tenant, id=committed_id, name="Committed", slug="committed"))
    with (
        pytest.raises(RuntimeError, match="abort"),
        runtime_database.transaction(tenant) as session,
    ):
        session.add(Line(tenant_id=tenant, id=rolled_back_id, name="Aborted", slug="aborted"))
        session.flush()
        raise RuntimeError("abort")
    with runtime_database.transaction(tenant, read_only=True) as session:
        identifiers = set(session.scalars(select(Line.id)))
        assert committed_id in identifiers
        assert rolled_back_id not in identifiers


def test_pool_reuse_never_reuses_tenant_context(
    runtime_database: ApplicationDatabase, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    backend_pids = []
    for seed in (tenants[0], tenants[1], tenants[0]):
        with runtime_database.transaction(seed["tenant"], read_only=True) as session:
            backend_pids.append(session.scalar(text("SELECT pg_backend_pid()")))
            assert set(session.scalars(select(Line.tenant_id))) == {seed["tenant"]}
        with runtime_database.engine.connect() as connection:
            assert connection.scalar(text("SELECT current_setting('app.tenant_id', true)")) in (
                None,
                "",
            )
            assert connection.scalar(text("SELECT count(*) FROM lines")) == 0
    assert len(set(backend_pids)) == 1


def test_read_only_rejects_writes_and_pool_recovers(
    runtime_database: ApplicationDatabase, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    tenant = tenants[0]["tenant"]
    with pytest.raises(DBAPIError), runtime_database.transaction(tenant, read_only=True) as session:
        session.execute(text("UPDATE lines SET name = 'forbidden'"))
    with runtime_database.transaction(tenant) as session:
        assert session.scalar(select(Line.name)) == "Hair"


def test_cross_tenant_write_is_rejected(
    runtime_database: ApplicationDatabase, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    with pytest.raises(DBAPIError), runtime_database.transaction(tenants[0]["tenant"]) as session:
        session.add(Line(tenant_id=tenants[1]["tenant"], name="Forbidden", slug="forbidden"))


def test_commit_failure_rolls_back_all_pending_changes(
    runtime_database: ApplicationDatabase, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    tenant = tenants[0]["tenant"]
    with pytest.raises(IntegrityError), runtime_database.transaction(tenant) as session:
        session.add_all(
            [
                Line(tenant_id=tenant, name="First", slug="same"),
                Line(tenant_id=tenant, name="Second", slug="same"),
            ]
        )
    with runtime_database.transaction(tenant, read_only=True) as session:
        assert session.scalar(select(Line.id).where(Line.slug == "same")) is None


def test_commit_error_becomes_http_conflict_before_success_response(
    database: Database,
    runtime_database: ApplicationDatabase,
    tenants: tuple[dict[str, UUID], dict[str, UUID]],
) -> None:
    app = create_app(
        Settings(
            environment="test",
            database_url=SecretStr(database.lab.runtime_url),
            allowed_hosts=("testserver",),
        ),
        database=runtime_database,
    )

    @app.post("/__test__/commit", status_code=201)
    def commit_error() -> dict[str, bool]:
        with runtime_database.transaction(tenants[0]["tenant"]) as session:
            # No flush: the uniqueness error is raised when the service commits.
            session.add(Line(tenant_id=tenants[0]["tenant"], name="Duplicate", slug="hair"))
        return {"created": True}

    with TestClient(app) as client:
        response = client.post("/__test__/commit")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "data_conflict"
        assert "created" not in response.json()
        assert client.get("/api/v1/health/ready").status_code == 200


def test_startup_refuses_owner_and_disposes_pool(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Settings(database_url=SecretStr(database.lab.owner_url))
    instance = ApplicationDatabase(config)
    disposed = False
    original_dispose = instance.dispose

    def track_disposal() -> None:
        nonlocal disposed
        disposed = True
        original_dispose()

    monkeypatch.setattr(instance, "dispose", track_disposal)
    app = create_app(config, database=instance)
    with pytest.raises(RuntimeError, match="Database prerequisites failed"), TestClient(app):
        pytest.fail("An owner connection must not start the HTTP server")
    assert disposed


def test_bad_credentials_produce_safe_readiness_failure(database: Database) -> None:
    url = database.lab.owner.url.set(password="wrong-password-never-expose")
    instance = ApplicationDatabase(
        Settings(database_url=SecretStr(url.render_as_string(hide_password=False)))
    )
    try:
        with pytest.raises(DatabaseNotReady, match="^database_unavailable$") as caught:
            instance.validate_ready()
        assert "wrong-password" not in str(caught.value)
    finally:
        instance.dispose()
