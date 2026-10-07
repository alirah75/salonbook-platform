"""Run a disposable API preview with mobile and password authentication."""

import argparse
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

import uvicorn
from alembic.config import Config
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings
from app.db.database import Database
from app.modules.access.service import provision_roles
from app.modules.appointments.expiry import ExpiryService
from app.modules.identity.schemas import RegisterInput
from app.modules.identity.security import Security
from app.modules.payments.processing import PaymentProcessor
from app.modules.payments.worker import PaymentWorker
from app.modules.tenancy.administration import TenantAdministration, TenantCreate
from app.modules.tenancy.models import CalendarControl, Salon, SalonSettings, TenantDomain
from app.platform.config import PlatformSettings
from app.platform.main import create_platform_app
from scripts.demo_booking import seed_booking_demo
from scripts.demo_dashboard import platform_login, staff_accounts, write_credentials
from scripts.platform_admin import bootstrap
from scripts.postgres_lab import execute_sql, temporary_postgres
from scripts.serve import run_server

BACKEND = Path(__file__).resolve().parents[1]


@contextmanager
def preview_environment(
    port: int,
    manager: RegisterInput | None = None,
    *,
    public_port: int | None = None,
    demo: bool = False,
    dashboard_demo: bool = False,
) -> Iterator[Settings]:
    with temporary_postgres("stage14-preview") as lab:
        with patch.dict("os.environ", {"DATABASE_MIGRATION_URL": lab.owner_url}):
            command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
        with lab.admin.begin() as connection:
            execute_sql(
                connection, (BACKEND / "sql/runtime_grants.sql").read_text(encoding="utf-8")
            )
            connection.exec_driver_sql("GRANT salonbook_runtime TO salonbook_test_runtime")
        key = Fernet.generate_key().decode()
        credentials: dict[str, dict[str, str]] = {}
        if dashboard_demo:
            manager = RegisterInput(
                phone="09120000001",
                display_name="مدیر سالن آزمایشی",
                password=SecretStr(secrets.token_urlsafe(24)),
            )
            credentials["salon_manager"] = {
                "phone": manager.phone,
                "password": manager.password.get_secret_value(),
                "name": manager.display_name,
            }
        if manager is not None:
            control = TenantAdministration(lab.owner, Security(key))
            tenant = control.create(
                TenantCreate(name="SalonBook Local Preview", hostname="127.0.0.1", manager=manager),
                "Disposable local preview",
                verified_local=True,
            )
            control.domain(tenant, "localhost", "add", "Loopback preview alias")
            control.domain(tenant, "localhost", "activate", "Verified loopback alias")
        else:
            with Session(lab.admin) as session, session.begin():
                salon = Salon(name="SalonBook Local Preview")
                session.add(salon)
                session.flush()
                tenant = salon.id
                session.add_all(
                    [SalonSettings(tenant_id=tenant), CalendarControl(tenant_id=tenant)]
                )
                for hostname in ("127.0.0.1", "localhost"):
                    session.add(
                        TenantDomain(
                            tenant_id=tenant,
                            hostname=hostname,
                            verified_at=datetime.now(UTC),
                            is_active=True,
                        )
                    )
                provision_roles(session, tenant)
        if demo or dashboard_demo:
            seed_booking_demo(lab.admin, tenant)
        platform_server = None
        platform_thread = None
        if dashboard_demo:
            credentials.update(staff_accounts(lab.admin, tenant, Security(key)))
            platform_user = RegisterInput(
                phone="09120000004",
                display_name="مدیر کل آزمایشی",
                password=SecretStr(secrets.token_urlsafe(24)),
            )
            bootstrap(lab.owner, platform_user, "Opt-in disposable dashboard preview")
            credentials["super_admin"] = {
                "phone": platform_user.phone,
                "password": platform_user.password.get_secret_value(),
                "name": platform_user.display_name,
            }
            platform_settings = PlatformSettings(
                environment="development",
                database_url=SecretStr(platform_login(lab)),
                auth_key=SecretStr(Fernet.generate_key().decode()),
                public_origin=f"http://127.0.0.1:{public_port or port}",
            )
            platform_server = uvicorn.Server(
                uvicorn.Config(
                    create_platform_app(platform_settings),
                    host="127.0.0.1",
                    port=8001,
                    proxy_headers=False,
                    access_log=False,
                    log_config=None,
                )
            )
            platform_thread = Thread(
                target=platform_server.run, daemon=True, name="salonbook-platform-preview"
            )
            platform_thread.start()
            local = BACKEND / ".local"
            write_credentials(local, credentials, public_port or port)
        settings = Settings(
            environment="development",
            database_url=SecretStr(lab.runtime_url),
            allowed_hosts=("127.0.0.1", "localhost"),
            cors_origins=(),
            docs_enabled=True,
            auth_key=SecretStr(key),
            auth_public_port=public_port or port,
            mock_payments_enabled=True,
        )
        worker_database = Database(settings)
        stop = Event()
        worker = Thread(
            target=ExpiryService(worker_database).run,
            args=(tenant, stop),
            daemon=True,
            name="salonbook-preview-expiry",
        )
        worker.start()
        payments = Thread(
            target=PaymentWorker(PaymentProcessor(worker_database, settings)).run,
            args=(tenant, stop),
            daemon=True,
            name="salonbook-preview-payments",
        )
        payments.start()
        try:
            yield settings
        finally:
            if platform_server is not None and platform_thread is not None:
                platform_server.should_exit = True
                platform_thread.join(timeout=15)
            stop.set()
            worker.join(timeout=30)
            payments.join(timeout=30)
            worker_database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--dashboard-demo",
        action="store_true",
        help="Generate random staff/platform accounts in this disposable preview; credentials in .local/dashboard-demo.json",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Seed demo booking catalog in this disposable database only",
    )
    parser.add_argument(
        "--public-port", type=int, help="Local browser origin port, e.g. 3000 for the frontend"
    )
    parser.add_argument(
        "--manager-phone",
        default=None,
        help="Optional initial salon manager; password is prompted privately",
    )
    parser.add_argument("--manager-name", default="Local manager")
    args = parser.parse_args()
    manager = None
    if args.manager_phone:
        manager = RegisterInput(
            phone=args.manager_phone,
            display_name=args.manager_name,
            password=SecretStr(getpass("Local manager password (15+ characters): ")),
        )
    with preview_environment(
        args.port,
        manager,
        public_port=args.public_port,
        demo=args.demo,
        dashboard_demo=args.dashboard_demo,
    ) as settings:
        print(f"Disposable preview: http://127.0.0.1:{args.port}/api/v1/docs", flush=True)
        print("Stop with Ctrl+C; only this preview database will be removed.", flush=True)
        run_server(settings, "127.0.0.1", args.port)


if __name__ == "__main__":
    main()
