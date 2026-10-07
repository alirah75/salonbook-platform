from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonObject, Mutable, TenantRecord, enum_type, tenant_fk
from app.db.enums import PaymentStatus, RefundStatus


class PaymentAccount(TenantRecord, Mutable, Base):
    __tablename__ = "payment_accounts"
    __table_args__ = (
        UniqueConstraint("id"),
        UniqueConstraint("provider", "merchant_reference", "is_test"),
        UniqueConstraint("tenant_id", "id", "is_test"),
        CheckConstraint("provider <> 'mock' OR is_test", name="mock_is_test"),
    )
    provider: Mapped[str] = mapped_column(String(40))
    merchant_reference: Mapped[str] = mapped_column(String(160))
    secret_ref: Mapped[str | None] = mapped_column(String(255))
    is_test: Mapped[bool] = mapped_column(Boolean)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class PaymentIntent(TenantRecord, Mutable, Base):
    __tablename__ = "payment_intents"
    __table_args__ = (
        tenant_fk(
            ("appointment_id", "amount", "currency", "is_test"),
            "appointments",
            ("id", "total_amount", "currency", "is_test"),
        ),
        UniqueConstraint("tenant_id", "appointment_id"),
        UniqueConstraint("tenant_id", "id", "amount", "currency", "is_test"),
        CheckConstraint("amount > 0 AND currency = 'IRR'", name="amount_currency"),
        CheckConstraint("expires_at > created_at", name="expiry"),
    )
    appointment_id: Mapped[UUID]
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    is_test: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[PaymentStatus] = mapped_column(
        enum_type(PaymentStatus, "payment_status"), server_default="CREATED"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentAttempt(TenantRecord, Mutable, Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        tenant_fk(
            ("intent_id", "amount", "currency", "is_test"),
            "payment_intents",
            ("id", "amount", "currency", "is_test"),
        ),
        tenant_fk(("account_id", "is_test"), "payment_accounts", ("id", "is_test")),
        UniqueConstraint("tenant_id", "intent_id", "request_key"),
        UniqueConstraint("tenant_id", "id", "intent_id", "account_id", "currency", "is_test"),
        UniqueConstraint("account_id", "gateway_order_id"),
        CheckConstraint("amount > 0 AND currency = 'IRR'", name="amount_currency"),
        Index(
            "uq_payment_attempts_open_intent",
            "tenant_id",
            "intent_id",
            unique=True,
            postgresql_where=text(
                "status IN ('CREATED', 'PENDING', 'VERIFYING', 'RECONCILIATION_REQUIRED')"
            ),
        ),
        Index(
            "ix_payment_attempts_reconcile",
            "tenant_id",
            "next_check_at",
            postgresql_where=text("status <> 'SUCCEEDED'"),
        ),
    )
    intent_id: Mapped[UUID]
    account_id: Mapped[UUID]
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    is_test: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[PaymentStatus] = mapped_column(
        enum_type(PaymentStatus, "attempt_status"), server_default="CREATED"
    )
    request_key: Mapped[str] = mapped_column(String(128))
    gateway_order_id: Mapped[str | None] = mapped_column(String(180))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    safe_response: Mapped[JsonObject] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class PaymentTransaction(TenantRecord, Base):
    """A verified actual receipt, including late or duplicate real receipts."""

    __tablename__ = "payment_transactions"
    __table_args__ = (
        tenant_fk(
            ("attempt_id", "intent_id", "account_id", "currency", "is_test"),
            "payment_attempts",
            ("id", "intent_id", "account_id", "currency", "is_test"),
        ),
        UniqueConstraint("account_id", "gateway_transaction_id"),
        UniqueConstraint("tenant_id", "id", "intent_id", "amount", "currency", "is_test"),
        UniqueConstraint("tenant_id", "id", "amount", "currency", "is_test"),
        CheckConstraint("amount > 0 AND currency = 'IRR'", name="amount_currency"),
        Index("ix_payment_transactions_received", "tenant_id", "received_at"),
    )
    attempt_id: Mapped[UUID]
    intent_id: Mapped[UUID]
    account_id: Mapped[UUID]
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    is_test: Mapped[bool] = mapped_column(Boolean)
    gateway_transaction_id: Mapped[str] = mapped_column(String(180))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[JsonObject] = mapped_column(JSONB)


class PaymentAllocation(TenantRecord, Base):
    """At most one full receipt is applied to the order; excess receipts survive."""

    __tablename__ = "payment_allocations"
    __table_args__ = (
        tenant_fk(
            ("intent_id", "amount", "currency", "is_test"),
            "payment_intents",
            ("id", "amount", "currency", "is_test"),
        ),
        tenant_fk(
            ("transaction_id", "intent_id", "amount", "currency", "is_test"),
            "payment_transactions",
            ("id", "intent_id", "amount", "currency", "is_test"),
        ),
        UniqueConstraint("tenant_id", "intent_id"),
        UniqueConstraint("tenant_id", "transaction_id"),
    )
    intent_id: Mapped[UUID]
    transaction_id: Mapped[UUID]
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    is_test: Mapped[bool] = mapped_column(Boolean)


class Refund(TenantRecord, Mutable, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        tenant_fk(
            ("transaction_id", "captured_amount", "currency", "is_test"),
            "payment_transactions",
            ("id", "amount", "currency", "is_test"),
        ),
        tenant_fk("requested_by_id", "users"),
        tenant_fk("approved_by_id", "users"),
        UniqueConstraint("tenant_id", "request_key"),
        UniqueConstraint("tenant_id", "transaction_id", "gateway_refund_id"),
        UniqueConstraint("tenant_id", "id", "transaction_id", "amount", "currency", "is_test"),
        CheckConstraint(
            "amount > 0 AND amount <= captured_amount AND currency = 'IRR'", name="amount_currency"
        ),
        CheckConstraint("status <> 'SUCCEEDED' OR succeeded_at IS NOT NULL", name="success_time"),
        Index(
            "ix_refunds_reconcile",
            "tenant_id",
            "next_check_at",
            postgresql_where=text(
                "status IN ('APPROVED', 'PROCESSING', 'RECONCILIATION_REQUIRED')"
            ),
        ),
    )
    transaction_id: Mapped[UUID]
    captured_amount: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    is_test: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[RefundStatus] = mapped_column(
        enum_type(RefundStatus, "refund_status"), server_default="REQUESTED"
    )
    request_key: Mapped[str] = mapped_column(String(128))
    gateway_refund_id: Mapped[str | None] = mapped_column(String(180))
    requested_by_id: Mapped[UUID | None]
    approved_by_id: Mapped[UUID | None]
    reason: Mapped[str] = mapped_column(Text)
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallbackEvent(TenantRecord, Base):
    __tablename__ = "callback_events"
    __table_args__ = (tenant_fk("attempt_id", "payment_attempts"),)
    attempt_id: Mapped[UUID]
    provider_event_id: Mapped[str | None] = mapped_column(String(180))
    outcome: Mapped[str] = mapped_column(String(32))
    safe_payload: Mapped[JsonObject] = mapped_column(JSONB)


class MockOrder(TenantRecord, Mutable, Base):
    """Durable simulator ledger, separate from the application's payment evidence."""

    __tablename__ = "mock_orders"
    __table_args__ = (
        tenant_fk("account_id", "payment_accounts"),
        UniqueConstraint("tenant_id", "account_id", "request_key"),
        CheckConstraint("amount > 0 AND currency = 'IRR'", name="amount_currency"),
        CheckConstraint("unknown_reads >= 0", name="unknown_reads"),
        CheckConstraint("status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'CANCELLED')", name="status"),
    )
    account_id: Mapped[UUID]
    request_key: Mapped[str] = mapped_column(String(128))
    merchant: Mapped[str] = mapped_column(String(160))
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), server_default="PENDING")
    scenario: Mapped[str | None] = mapped_column(String(32))
    unknown_reads: Mapped[int] = mapped_column(Integer, server_default="0")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MockRefund(TenantRecord, Base):
    __tablename__ = "mock_refunds"
    __table_args__ = (
        tenant_fk("order_id", "mock_orders"),
        UniqueConstraint("tenant_id", "order_id", "request_key"),
        CheckConstraint("amount > 0", name="amount"),
    )
    order_id: Mapped[UUID]
    request_key: Mapped[str] = mapped_column(String(128))
    amount: Mapped[int] = mapped_column(BigInteger)
