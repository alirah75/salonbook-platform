from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, insert, text

from alembic import command
from app.db.models import Base
from scripts.postgres_lab import PostgresLab, execute_sql, temporary_postgres


@dataclass(frozen=True)
class Database:
    lab: PostgresLab
    runtime: Engine


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    with temporary_postgres() as lab:
        with patch.dict("os.environ", {"DATABASE_MIGRATION_URL": lab.owner_url}):
            command.upgrade(Config("alembic.ini"), "head")
        with lab.admin.begin() as connection:
            execute_sql(connection, Path("sql/runtime_grants.sql").read_text(encoding="utf-8"))
            connection.exec_driver_sql("GRANT salonbook_runtime TO salonbook_test_runtime")
        runtime = create_engine(lab.runtime_url, pool_size=5, max_overflow=60)
        try:
            yield Database(lab, runtime)
        finally:
            runtime.dispose()


@contextmanager
def tenant_connection(database: Database, tenant_id: UUID) -> Iterator[Connection]:
    with database.runtime.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)}
        )
        yield connection


def add(connection: Connection, table: str, **values: Any) -> UUID:
    identifier = values.setdefault("id", uuid4())
    assert isinstance(identifier, UUID)
    connection.execute(insert(Base.metadata.tables[table]).values(**values))
    return identifier


def appointment_values(seed: dict[str, UUID], **overrides: Any) -> dict[str, Any]:
    start = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=7)
    values: dict[str, Any] = dict(
        tenant_id=seed["tenant"],
        customer_id=seed["customer"],
        employee_id=seed["employee"],
        line_id=seed["line"],
        starts_at=start,
        ends_at=start + timedelta(minutes=30),
        occupied_starts_at=start,
        occupied_ends_at=start + timedelta(minutes=30),
        duration_minutes=30,
        total_amount=1_000_000,
        currency="IRR",
        is_test=True,
        hold_expires_at=datetime.now(UTC) + timedelta(minutes=10),
        policy_snapshot={"version": 1},
    )
    values.update(overrides)
    return values


def seed_tenant(connection: Connection) -> dict[str, UUID]:
    seed: dict[str, UUID] = {}
    tenant = seed["tenant"] = add(connection, "salons", name="Test salon")
    common = {"tenant_id": tenant}
    add(connection, "salon_settings", **common)
    add(connection, "calendar_controls", **common)
    for key in ("customer_user", "employee_user"):
        seed[key] = add(
            connection,
            "users",
            **common,
            email_normalized=f"{key}@example.test",
            password_hash="test-only-hash-placeholder",
            display_name=key,
        )
    seed["customer"] = add(connection, "customer_profiles", **common, user_id=seed["customer_user"])
    seed["employee"] = add(
        connection,
        "employee_profiles",
        **common,
        user_id=seed["employee_user"],
        public_name="Test employee",
    )
    seed["line"] = add(connection, "lines", **common, name="Hair", slug="hair")
    seed["service"] = add(connection, "services", **common, code="cut", name="Haircut")
    add(
        connection,
        "line_services",
        **common,
        line_id=seed["line"],
        service_id=seed["service"],
        price_amount=1_000_000,
        duration_minutes=30,
    )
    add(connection, "employee_lines", **common, employee_id=seed["employee"], line_id=seed["line"])
    add(
        connection,
        "employee_services",
        **common,
        employee_id=seed["employee"],
        line_id=seed["line"],
        service_id=seed["service"],
    )
    seed["calendar"] = add(connection, "calendars", **common, scope="SALON")
    seed["role"] = add(connection, "roles", **common, code="customer", name="Customer")
    return seed


@pytest.fixture
def tenants(database: Database) -> tuple[dict[str, UUID], dict[str, UUID]]:
    with database.lab.admin.begin() as connection:
        return seed_tenant(connection), seed_tenant(connection)


@pytest.fixture
def paid_seed(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> dict[str, UUID]:
    seed = dict(tenants[0])
    common = {"tenant_id": seed["tenant"]}
    now = datetime.now(UTC)
    with database.lab.admin.begin() as connection:
        seed["appointment"] = add(
            connection,
            "appointments",
            **appointment_values(seed, status="CONFIRMED", confirmed_at=now),
        )
        seed["item"] = add(
            connection,
            "appointment_items",
            **common,
            appointment_id=seed["appointment"],
            original_employee_id=seed["employee"],
            line_id=seed["line"],
            service_id=seed["service"],
            position=1,
            service_name="Haircut",
            line_name="Hair",
            employee_name="Test employee",
            duration_minutes=30,
            amount=1_000_000,
        )
        money = dict(amount=1_000_000, currency="IRR", is_test=True)
        seed["intent"] = add(
            connection,
            "payment_intents",
            **common,
            appointment_id=seed["appointment"],
            expires_at=now + timedelta(minutes=10),
            status="SUCCEEDED",
            **money,
        )
        seed["account"] = add(
            connection,
            "payment_accounts",
            **common,
            provider="mock",
            merchant_reference=uuid4().hex,
            is_test=True,
        )
        seed["attempt"] = add(
            connection,
            "payment_attempts",
            **common,
            intent_id=seed["intent"],
            account_id=seed["account"],
            request_key=uuid4().hex,
            status="SUCCEEDED",
            **money,
        )
        seed["transaction"] = add(
            connection,
            "payment_transactions",
            **common,
            attempt_id=seed["attempt"],
            intent_id=seed["intent"],
            account_id=seed["account"],
            gateway_transaction_id=uuid4().hex,
            received_at=now,
            verified_at=now,
            evidence={"verified": True},
            **money,
        )
        seed["allocation"] = add(
            connection,
            "payment_allocations",
            **common,
            intent_id=seed["intent"],
            transaction_id=seed["transaction"],
            **money,
        )
        seed["receipt"] = add(
            connection,
            "receipts",
            **common,
            transaction_id=seed["transaction"],
            number=uuid4().hex,
            issued_at=now,
            **money,
        )
        seed["invoice"] = add(
            connection,
            "invoices",
            **common,
            appointment_id=seed["appointment"],
            number=uuid4().hex,
            total_amount=1_000_000,
            currency="IRR",
            is_test=True,
            issued_at=now,
            seller_snapshot={"name": "Salon"},
            buyer_snapshot={"name": "Customer"},
        )
        seed["invoice_item"] = add(
            connection,
            "invoice_items",
            **common,
            invoice_id=seed["invoice"],
            appointment_id=seed["appointment"],
            appointment_item_id=seed["item"],
            position=1,
            description="Haircut",
            amount=1_000_000,
        )
        seed["entry"] = add(
            connection,
            "financial_entries",
            **common,
            kind="CAPTURE",
            transaction_id=seed["transaction"],
            captured_amount=1_000_000,
            booked_at=now,
            **money,
        )
        seed["audit"] = add(
            connection,
            "audit_logs",
            **common,
            actor_kind="USER",
            actor_id=seed["customer_user"],
            action="appointment.confirmed",
            entity_type="appointment",
            entity_id=seed["appointment"],
            event_data={},
        )
    return seed
