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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonObject, TenantRecord, tenant_fk


class Invoice(TenantRecord, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        tenant_fk(
            ("appointment_id", "total_amount", "currency", "is_test"),
            "appointments",
            ("id", "total_amount", "currency", "is_test"),
        ),
        UniqueConstraint("tenant_id", "number"),
        UniqueConstraint("tenant_id", "appointment_id"),
        UniqueConstraint("tenant_id", "id", "appointment_id"),
        CheckConstraint("total_amount >= 0 AND currency = 'IRR'", name="amount_currency"),
    )
    appointment_id: Mapped[UUID]
    number: Mapped[str] = mapped_column(String(64))
    total_amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    is_test: Mapped[bool] = mapped_column(Boolean)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seller_snapshot: Mapped[JsonObject] = mapped_column(JSONB)
    buyer_snapshot: Mapped[JsonObject] = mapped_column(JSONB)


class InvoiceItem(TenantRecord, Base):
    __tablename__ = "invoice_items"
    __table_args__ = (
        tenant_fk(("invoice_id", "appointment_id"), "invoices", ("id", "appointment_id")),
        tenant_fk(
            ("appointment_item_id", "appointment_id"), "appointment_items", ("id", "appointment_id")
        ),
        UniqueConstraint("tenant_id", "invoice_id", "position"),
        UniqueConstraint("tenant_id", "invoice_id", "appointment_item_id"),
        CheckConstraint("amount >= 0 AND position > 0", name="values"),
    )
    invoice_id: Mapped[UUID]
    appointment_id: Mapped[UUID]
    appointment_item_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))
    amount: Mapped[int] = mapped_column(BigInteger)


class Receipt(TenantRecord, Base):
    __tablename__ = "receipts"
    __table_args__ = (
        tenant_fk(
            ("transaction_id", "amount", "currency", "is_test"),
            "payment_transactions",
            ("id", "amount", "currency", "is_test"),
        ),
        UniqueConstraint("tenant_id", "number"),
        UniqueConstraint("tenant_id", "transaction_id"),
    )
    transaction_id: Mapped[UUID]
    number: Mapped[str] = mapped_column(String(64))
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    is_test: Mapped[bool] = mapped_column(Boolean)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CreditNote(TenantRecord, Base):
    __tablename__ = "credit_notes"
    __table_args__ = (
        tenant_fk("refund_id", "refunds"),
        UniqueConstraint("tenant_id", "number"),
        UniqueConstraint("tenant_id", "refund_id"),
    )
    refund_id: Mapped[UUID]
    number: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FinancialEntry(TenantRecord, Base):
    """Positive capture or positive refund magnitude; sign follows kind in reports."""

    __tablename__ = "financial_entries"
    __table_args__ = (
        tenant_fk(
            ("transaction_id", "captured_amount", "currency", "is_test"),
            "payment_transactions",
            ("id", "amount", "currency", "is_test"),
        ),
        tenant_fk(
            ("refund_id", "transaction_id", "amount", "currency", "is_test"),
            "refunds",
            ("id", "transaction_id", "amount", "currency", "is_test"),
        ),
        CheckConstraint(
            "amount > 0 AND amount <= captured_amount AND currency = 'IRR' AND (kind <> 'CAPTURE' OR amount = captured_amount)",
            name="amount_currency",
        ),
        CheckConstraint(
            "(kind = 'CAPTURE' AND refund_id IS NULL) OR (kind = 'REFUND' AND refund_id IS NOT NULL)",
            name="kind_source",
        ),
        Index(
            "uq_financial_entries_capture",
            "tenant_id",
            "transaction_id",
            unique=True,
            postgresql_where=text("kind = 'CAPTURE'"),
        ),
        Index(
            "uq_financial_entries_refund",
            "tenant_id",
            "refund_id",
            unique=True,
            postgresql_where=text("kind = 'REFUND'"),
        ),
        Index("ix_financial_entries_booked", "tenant_id", "is_test", "booked_at"),
    )
    kind: Mapped[str] = mapped_column(String(8))
    transaction_id: Mapped[UUID]
    captured_amount: Mapped[int] = mapped_column(BigInteger)
    refund_id: Mapped[UUID | None]
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    is_test: Mapped[bool] = mapped_column(Boolean)
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
