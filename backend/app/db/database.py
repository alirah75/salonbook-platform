"""Bounded connection pool and explicit tenant transaction boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Connection, bindparam, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Base
from app.db.schema import REQUIRED_SCHEMA_REVISION


class DatabaseNotReady(RuntimeError):
    """Carries a safe machine code, never a driver error message or URL."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


RUNTIME_ROLE_CHECK = text("""
    SELECT
        EXISTS (
            SELECT 1 FROM pg_roles r
            WHERE pg_has_role(current_user, r.oid, 'MEMBER')
              AND (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb)
        ) AS elevated,
        EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
              AND pg_has_role(current_user, c.relowner, 'MEMBER')
        ) AS owns_application_objects,
        has_schema_privilege(current_user, 'public', 'CREATE') AS can_create,
        has_table_privilege(current_user, 'public.tenant_domains', 'INSERT,UPDATE,DELETE')
          OR has_table_privilege(current_user, 'public.platform_audit_logs', 'INSERT')
          OR has_column_privilege(current_user, 'public.salons', 'status', 'UPDATE')
          AS has_control_plane_privileges
""")

RLS_CHECK = text("""
    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname IN :tables
""").bindparams(bindparam("tables", expanding=True))


class Database:
    """One pool per process; each service opens and finishes its own unit of work."""

    def __init__(self, settings: Settings) -> None:
        options = (
            "-c timezone=UTC -c search_path=public "
            f"-c statement_timeout={settings.db_statement_timeout_ms} "
            f"-c lock_timeout={settings.db_lock_timeout_ms} "
            f"-c idle_in_transaction_session_timeout={settings.db_idle_transaction_timeout_ms}"
        )
        self.engine = create_engine(
            settings.database_url.get_secret_value(),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_recycle=settings.db_pool_recycle_seconds,
            pool_pre_ping=True,
            hide_parameters=True,
            echo=False,
            connect_args={
                "connect_timeout": settings.db_connect_timeout_seconds,
                "application_name": "salonbook-api",
                "options": options,
            },
        )
        self._sessions = sessionmaker(
            self.engine, autoflush=False, expire_on_commit=False, autobegin=False
        )
        self._tenant_tables = {
            table.name
            for table in Base.metadata.tables.values()
            if "tenant_id" in table.c and table.name != "tenant_domains"
        } | {"salons"}

    def _verify(self, connection: Connection) -> None:
        role = connection.execute(RUNTIME_ROLE_CHECK).one()
        if any(role):
            raise DatabaseNotReady("unsafe_database_role")
        revisions = (
            connection.execute(text("SELECT version_num FROM public.app_schema_revision"))
            .scalars()
            .all()
        )
        if revisions != [REQUIRED_SCHEMA_REVISION]:
            raise DatabaseNotReady("schema_revision_mismatch")
        rows = connection.execute(RLS_CHECK, {"tables": sorted(self._tenant_tables)}).all()
        protected = {name for name, enabled, forced in rows if enabled and forced}
        if protected != self._tenant_tables:
            raise DatabaseNotReady("tenant_isolation_missing")

    def validate_ready(self) -> None:
        """Connectivity, effective role, migration version and mandatory RLS must agree."""
        try:
            with self.engine.connect() as connection:
                self._verify(connection)
        except SQLAlchemyError:
            raise DatabaseNotReady("database_unavailable") from None

    @contextmanager
    def transaction(self, tenant_id: UUID, *, read_only: bool = False) -> Iterator[Session]:
        """Commit before the service returns; roll back on any error, including commit errors.

        Tenant identifiers come from trusted resolution, never an unverified HTTP header.
        Services own this boundary. Repositories must neither commit nor change the tenant.
        """
        if not isinstance(tenant_id, UUID):
            raise TypeError("A resolved tenant UUID is required.")
        with self._sessions() as session, session.begin():
            if read_only:
                session.execute(text("SET TRANSACTION READ ONLY"))
            self._verify(session.connection())
            session.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenant_id)},
            )
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
