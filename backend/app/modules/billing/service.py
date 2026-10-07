"""Append-only commercial documents; caller supplies the locked appointment/payment."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.appointments.models import Appointment, AppointmentItem
from app.modules.billing.models import CreditNote, FinancialEntry, Invoice, InvoiceItem, Receipt
from app.modules.identity.models import CustomerProfile, User
from app.modules.payments.models import PaymentTransaction, Refund
from app.modules.payments.schemas import InvoiceLine, InvoiceView
from app.modules.tenancy.models import Salon


def invoice(session: Session, appointment: Appointment) -> Invoice:
    existing = session.scalar(select(Invoice).where(Invoice.appointment_id == appointment.id))
    if existing:
        return existing
    seller = session.scalar(select(Salon.name).where(Salon.id == appointment.tenant_id))
    buyer = session.scalar(
        select(User.display_name)
        .join(CustomerProfile, CustomerProfile.user_id == User.id)
        .where(CustomerProfile.id == appointment.customer_id)
    )
    row = Invoice(
        tenant_id=appointment.tenant_id,
        appointment_id=appointment.id,
        number=f"{'TEST-' if appointment.is_test else ''}INV-{appointment.id}",
        total_amount=appointment.total_amount,
        currency=appointment.currency,
        is_test=appointment.is_test,
        issued_at=datetime.now(UTC),
        seller_snapshot={"name": seller},
        buyer_snapshot={"name": buyer},
    )
    session.add(row)
    session.flush()
    for item in session.scalars(
        select(AppointmentItem)
        .where(AppointmentItem.appointment_id == appointment.id)
        .order_by(AppointmentItem.position)
    ):
        session.add(
            InvoiceItem(
                tenant_id=row.tenant_id,
                invoice_id=row.id,
                appointment_id=appointment.id,
                appointment_item_id=item.id,
                position=item.position,
                description=item.service_name,
                amount=item.amount,
            )
        )
    session.flush()
    return row


def invoice_view(session: Session, row: Invoice) -> InvoiceView:
    return InvoiceView(
        id=row.id,
        appointment_id=row.appointment_id,
        number=row.number,
        total_amount=row.total_amount,
        currency=row.currency,
        is_test=row.is_test,
        issued_at=row.issued_at,
        seller=row.seller_snapshot,
        buyer=row.buyer_snapshot,
        items=[
            InvoiceLine(position=item.position, description=item.description, amount=item.amount)
            for item in session.scalars(
                select(InvoiceItem)
                .where(InvoiceItem.invoice_id == row.id)
                .order_by(InvoiceItem.position)
            )
        ],
    )


def capture(session: Session, transaction: PaymentTransaction) -> None:
    row = transaction
    session.add_all(
        [
            Receipt(
                tenant_id=row.tenant_id,
                transaction_id=row.id,
                number=f"{'TEST-' if row.is_test else ''}RCPT-{row.id}",
                amount=row.amount,
                currency=row.currency,
                is_test=row.is_test,
                issued_at=row.verified_at,
            ),
            FinancialEntry(
                tenant_id=row.tenant_id,
                kind="CAPTURE",
                transaction_id=row.id,
                captured_amount=row.amount,
                amount=row.amount,
                currency=row.currency,
                is_test=row.is_test,
                booked_at=row.verified_at,
            ),
        ]
    )


def credit(session: Session, row: Refund) -> None:
    session.add_all(
        [
            CreditNote(
                tenant_id=row.tenant_id,
                refund_id=row.id,
                number=f"{'TEST-' if row.is_test else ''}CR-{row.id}",
                issued_at=row.succeeded_at,
            ),
            FinancialEntry(
                tenant_id=row.tenant_id,
                kind="REFUND",
                transaction_id=row.transaction_id,
                refund_id=row.id,
                captured_amount=row.captured_amount,
                amount=row.amount,
                currency=row.currency,
                is_test=row.is_test,
                booked_at=row.succeeded_at,
            ),
        ]
    )
