"""Offline tenant control plane. Credentials and passwords are never command-line arguments."""

import argparse
import os
from getpass import getpass
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.modules.identity.schemas import RegisterInput
from app.modules.identity.security import Security
from app.modules.tenancy.administration import TenantAdministration, TenantCreate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--hostname", required=True)
    create.add_argument("--manager-phone", required=True)
    create.add_argument("--manager-name", required=True)
    create.add_argument("--reason", required=True)
    show = commands.add_parser("show")
    show.add_argument("--tenant", type=UUID, required=True)
    bootstrap = commands.add_parser("bootstrap-manager")
    bootstrap.add_argument("--tenant", type=UUID, required=True)
    bootstrap.add_argument("--user", type=UUID, required=True)
    bootstrap.add_argument("--reason", required=True)
    status = commands.add_parser("status")
    status.add_argument("--tenant", type=UUID, required=True)
    status.add_argument("--status", choices=("ACTIVE", "SUSPENDED", "CLOSED"), required=True)
    status.add_argument("--reason", required=True)
    domain = commands.add_parser("domain")
    domain.add_argument("--tenant", type=UUID, required=True)
    domain.add_argument("--hostname", required=True)
    domain.add_argument("--operation", choices=("add", "activate", "disable"), required=True)
    domain.add_argument("--confirm-domain-control", action="store_true")
    domain.add_argument("--reason", required=True)
    args = parser.parse_args()
    url = os.environ.get("SALONBOOK_CONTROL_DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        parser.error(
            "Set SALONBOOK_CONTROL_DATABASE_URL to the dedicated control-plane connection."
        )
    if (
        args.command == "domain"
        and args.operation == "activate"
        and not args.confirm_domain_control
    ):
        parser.error(
            "Verify domain ownership and routing first, then use --confirm-domain-control."
        )
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=30000 -c lock_timeout=5000 -c search_path=public",
        },
    )
    try:
        service = TenantAdministration(engine, Security(Fernet.generate_key().decode()))
        if args.command == "create":
            password = getpass("Initial manager password (15+ characters): ")
            if password != getpass("Repeat password: "):
                raise ValueError("Passwords did not match.")
            payload = TenantCreate(
                name=args.name,
                hostname=args.hostname,
                manager=RegisterInput(
                    phone=args.manager_phone,
                    display_name=args.manager_name,
                    password=SecretStr(password),
                ),
            )
            tenant = service.create(payload, args.reason)
            print(f"Created tenant: {tenant}. Activate its domain after verification.")
        elif args.command == "show":
            print(service.show(args.tenant).model_dump_json())
        elif args.command == "status":
            service.status(args.tenant, args.status, args.reason)
            print("Salon status updated.")
        elif args.command == "bootstrap-manager":
            service.bootstrap_manager(args.tenant, args.user, args.reason)
            print("Initial manager assigned; a new login is required.")
        else:
            service.domain(args.tenant, args.hostname, args.operation, args.reason)
            print("Domain registration updated.")
    except AppError as error:
        raise SystemExit(error.public_message) from None
    except (ValidationError, ValueError):
        raise SystemExit(
            "Invalid input. Check names, mobile, hostname, reason and password length."
        ) from None
    except SQLAlchemyError:
        raise SystemExit(
            "Administration failed; no partial changes committed. Check privileges, schema and duplicate domain/mobile."
        ) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
