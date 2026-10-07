from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import Database, add, appointment_values, tenant_connection

pytestmark = pytest.mark.postgres


def test_payment_amount_must_match_reservation_snapshot(
    database: Database, tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    seed = tenants[0]
    with tenant_connection(database, seed["tenant"]) as connection:
        appointment = add(connection, "appointments", **appointment_values(seed))
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "payment_intents",
            tenant_id=seed["tenant"],
            appointment_id=appointment,
            amount=1,
            currency="IRR",
            is_test=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23503"


def test_concurrent_payment_creation_cannot_create_two_open_attempts(
    database: Database, paid_seed: dict[str, UUID]
) -> None:
    seed = paid_seed
    barrier = Barrier(2)

    def create_attempt(_: int) -> str:
        barrier.wait(timeout=10)
        try:
            with tenant_connection(database, seed["tenant"]) as connection:
                add(
                    connection,
                    "payment_attempts",
                    tenant_id=seed["tenant"],
                    intent_id=seed["intent"],
                    account_id=seed["account"],
                    request_key=uuid4().hex,
                    amount=1_000_000,
                    currency="IRR",
                    is_test=True,
                )
            return "success"
        except DBAPIError as exc:
            return str(getattr(exc.orig, "sqlstate", None))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create_attempt, range(2)))
    assert sorted(outcomes) == ["23505", "success"]


def test_same_gateway_receipt_cannot_be_recorded_twice(
    database: Database, paid_seed: dict[str, UUID]
) -> None:
    seed = paid_seed
    with tenant_connection(database, seed["tenant"]) as connection:
        reference = connection.scalar(
            text("SELECT gateway_transaction_id FROM payment_transactions WHERE id = :id"),
            {"id": seed["transaction"]},
        )
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "payment_transactions",
            tenant_id=seed["tenant"],
            attempt_id=seed["attempt"],
            intent_id=seed["intent"],
            account_id=seed["account"],
            gateway_transaction_id=reference,
            amount=1_000_000,
            currency="IRR",
            is_test=True,
            received_at=datetime.now(UTC),
            verified_at=datetime.now(UTC),
            evidence={},
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23505"


def test_real_second_receipt_survives_but_cannot_settle_twice(
    database: Database, paid_seed: dict[str, UUID]
) -> None:
    seed = paid_seed
    with tenant_connection(database, seed["tenant"]) as connection:
        duplicate_receipt = add(
            connection,
            "payment_transactions",
            tenant_id=seed["tenant"],
            attempt_id=seed["attempt"],
            intent_id=seed["intent"],
            account_id=seed["account"],
            gateway_transaction_id=uuid4().hex,
            amount=1_000_000,
            currency="IRR",
            is_test=True,
            received_at=datetime.now(UTC),
            verified_at=datetime.now(UTC),
            evidence={"reason": "duplicate actual capture"},
        )
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "payment_allocations",
            tenant_id=seed["tenant"],
            intent_id=seed["intent"],
            transaction_id=duplicate_receipt,
            amount=1_000_000,
            currency="IRR",
            is_test=True,
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23505"
    with tenant_connection(database, seed["tenant"]) as connection:
        assert connection.scalar(text("SELECT count(*) FROM payment_transactions")) == 2
        assert connection.scalar(text("SELECT count(*) FROM payment_allocations")) == 1


@pytest.mark.parametrize(
    "table,key",
    [
        ("payment_transactions", "transaction"),
        ("payment_allocations", "allocation"),
        ("receipts", "receipt"),
        ("invoices", "invoice"),
        ("invoice_items", "invoice_item"),
        ("financial_entries", "entry"),
        ("appointment_items", "item"),
        ("audit_logs", "audit"),
    ],
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_evidence_is_immutable_even_for_owner_queries(
    database: Database, paid_seed: dict[str, UUID], table: str, key: str, operation: str
) -> None:
    seed = paid_seed
    # A privileged test connection avoids confusing ACL protection with trigger protection.
    query = (
        f'UPDATE "{table}" SET created_at = now() WHERE id = :id'
        if operation == "UPDATE"
        else f'DELETE FROM "{table}" WHERE id = :id'
    )
    with pytest.raises(DBAPIError) as caught, database.lab.admin.begin() as connection:
        connection.execute(text(query), {"id": seed[key]})
    assert getattr(caught.value.orig, "sqlstate", None) == "55000"


def test_refund_cannot_exceed_source_receipt(
    database: Database, paid_seed: dict[str, UUID]
) -> None:
    seed = paid_seed
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "refunds",
            tenant_id=seed["tenant"],
            transaction_id=seed["transaction"],
            captured_amount=1_000_000,
            amount=1_000_001,
            currency="IRR",
            is_test=True,
            request_key=uuid4().hex,
            reason="Invalid",
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"


def test_ledger_cannot_invent_capture_amount(
    database: Database, paid_seed: dict[str, UUID]
) -> None:
    seed = paid_seed
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "financial_entries",
            tenant_id=seed["tenant"],
            kind="CAPTURE",
            transaction_id=seed["transaction"],
            captured_amount=1_000_000,
            amount=5_000_000,
            currency="IRR",
            is_test=True,
            booked_at=datetime.now(UTC),
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"


def test_test_payment_cannot_use_live_account(
    database: Database, paid_seed: dict[str, UUID]
) -> None:
    seed = paid_seed
    with tenant_connection(database, seed["tenant"]) as connection:
        live = add(
            connection,
            "payment_accounts",
            tenant_id=seed["tenant"],
            provider="future-provider",
            merchant_reference=uuid4().hex,
            is_test=False,
        )
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "payment_attempts",
            tenant_id=seed["tenant"],
            intent_id=seed["intent"],
            account_id=live,
            request_key=uuid4().hex,
            amount=1_000_000,
            currency="IRR",
            is_test=True,
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23503"


def test_financial_data_is_tenant_isolated(
    database: Database, paid_seed: dict[str, UUID], tenants: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    with tenant_connection(database, tenants[1]["tenant"]) as connection:
        for table in (
            "appointments",
            "appointment_items",
            "payment_intents",
            "payment_attempts",
            "payment_transactions",
            "payment_allocations",
            "receipts",
            "invoices",
            "financial_entries",
            "audit_logs",
        ):
            assert connection.scalar(text(f'SELECT count(*) FROM "{table}"')) == 0


def test_mismatched_actual_receipt_is_preserved_but_not_allocatable(
    database: Database, paid_seed: dict[str, UUID]
) -> None:
    seed = paid_seed
    with tenant_connection(database, seed["tenant"]) as connection:
        values = appointment_values(seed)
        for key in ("starts_at", "ends_at", "occupied_starts_at", "occupied_ends_at"):
            values[key] += timedelta(hours=2)
        appointment = add(connection, "appointments", **values)
        intent = add(
            connection,
            "payment_intents",
            tenant_id=seed["tenant"],
            appointment_id=appointment,
            amount=1_000_000,
            currency="IRR",
            is_test=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        attempt = add(
            connection,
            "payment_attempts",
            tenant_id=seed["tenant"],
            intent_id=intent,
            account_id=seed["account"],
            request_key=uuid4().hex,
            amount=1_000_000,
            currency="IRR",
            is_test=True,
        )
        receipt = add(
            connection,
            "payment_transactions",
            tenant_id=seed["tenant"],
            attempt_id=attempt,
            intent_id=intent,
            account_id=seed["account"],
            gateway_transaction_id=uuid4().hex,
            amount=900_000,
            currency="IRR",
            is_test=True,
            received_at=datetime.now(UTC),
            verified_at=datetime.now(UTC),
            evidence={"reconciliation_required": True},
        )
    with (
        pytest.raises(DBAPIError) as caught,
        tenant_connection(database, seed["tenant"]) as connection,
    ):
        add(
            connection,
            "payment_allocations",
            tenant_id=seed["tenant"],
            intent_id=intent,
            transaction_id=receipt,
            amount=900_000,
            currency="IRR",
            is_test=True,
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23503"
