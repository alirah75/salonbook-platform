"""Persistent mock gateway. Every call owns an independent short transaction."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.database import Database
from app.modules.payments.models import MockOrder, MockRefund
from app.modules.payments.providers import Capabilities, Order, RefundResult, Verification
from app.modules.tenancy.locks import tenant_lock


class MockPaymentProvider:
    capabilities = Capabilities()

    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, session: Session, order: Order) -> MockOrder:
        row = session.scalar(
            select(MockOrder)
            .where(
                MockOrder.account_id == order.account, MockOrder.request_key == order.request_key
            )
            .with_for_update()
        )
        if row is None:
            raise AppError("mock_order_missing", "Test checkout is not ready.", 409)
        return row

    def create(self, order: Order) -> str:
        with self.database.transaction(order.tenant) as session:
            tenant_lock(session, order.tenant, f"mock-create:{order.account}:{order.request_key}")
            row = session.scalar(
                select(MockOrder).where(
                    MockOrder.account_id == order.account,
                    MockOrder.request_key == order.request_key,
                )
            )
            if row is None:
                row = MockOrder(
                    tenant_id=order.tenant,
                    account_id=order.account,
                    request_key=order.request_key,
                    merchant=order.merchant,
                    amount=order.amount,
                    currency=order.currency,
                )
                session.add(row)
                session.flush()
            return str(row.id)

    def simulate(self, order: Order, scenario: str) -> None:
        with self.database.transaction(order.tenant) as session:
            row = self.get(session, order)
            if row.scenario is not None:
                if row.scenario != scenario:
                    raise AppError(
                        "mock_already_resolved", "This test checkout already has a result.", 409
                    )
                return
            row.scenario = scenario
            row.status = {"failure": "FAILED", "cancel": "CANCELLED"}.get(scenario, "SUCCEEDED")
            if row.status == "SUCCEEDED":
                row.received_at = datetime.now(UTC)
            if scenario == "timeout":
                row.unknown_reads = 1
            if scenario == "amount_mismatch":
                row.amount += 1

    def verify(self, order: Order, gateway_order_id: str) -> Verification:
        result = self.status(order)
        if result.order_id != gateway_order_id:
            raise AppError("mock_order_mismatch", "Test checkout does not match.", 409)
        return result

    def status(self, order: Order) -> Verification:
        with self.database.transaction(order.tenant) as session:
            row = self.get(session, order)
            unknown = row.unknown_reads > 0
            if row.status == "PENDING" and order.expires_at <= datetime.now(UTC):
                row.status = "CANCELLED"
            if unknown:
                row.unknown_reads -= 1
            outcome = "UNKNOWN" if unknown else row.status
            assert outcome in {"UNKNOWN", "PENDING", "SUCCEEDED", "FAILED", "CANCELLED"}
            return Verification(
                outcome=outcome,  # type: ignore[arg-type]
                merchant=row.merchant,
                order_id=str(row.id),
                amount=row.amount,
                currency=row.currency,
                transaction_id=f"mock-tx-{row.id}" if row.status == "SUCCEEDED" else None,
                received_at=row.received_at,
            )

    def refund_status(self, order: Order, key: str) -> RefundResult:
        with self.database.transaction(order.tenant) as session:
            row = self.get(session, order)
            refund = session.scalar(
                select(MockRefund).where(
                    MockRefund.order_id == row.id, MockRefund.request_key == key
                )
            )
            return self.refund_result(row, refund) if refund else RefundResult("PENDING")

    def refund(self, order: Order, transaction_id: str, key: str, amount: int) -> RefundResult:
        with self.database.transaction(order.tenant) as session:
            row = self.get(session, order)
            refund = session.scalar(
                select(MockRefund).where(
                    MockRefund.order_id == row.id, MockRefund.request_key == key
                )
            )
            if refund:
                if refund.amount != amount:
                    raise AppError(
                        "mock_refund_conflict", "Test refund key has different terms.", 409
                    )
                return self.refund_result(row, refund)
            used = (
                session.scalar(
                    select(func.coalesce(func.sum(MockRefund.amount), 0)).where(
                        MockRefund.order_id == row.id
                    )
                )
                or 0
            )
            if (
                row.status != "SUCCEEDED"
                or transaction_id != f"mock-tx-{row.id}"
                or amount <= 0
                or used + amount > row.amount
            ):
                return RefundResult("FAILED")
            refund = MockRefund(
                tenant_id=order.tenant, order_id=row.id, request_key=key, amount=amount
            )
            session.add(refund)
            session.flush()
            return self.refund_result(row, refund)

    @staticmethod
    def refund_result(order: MockOrder, refund: MockRefund) -> RefundResult:
        return RefundResult(
            "SUCCEEDED",
            f"mock-refund-{refund.id}",
            order.merchant,
            f"mock-tx-{order.id}",
            refund.amount,
            order.currency,
        )
