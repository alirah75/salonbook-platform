from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.enums import AppointmentStatus, PaymentStatus, RefundStatus
from app.modules.appointments import domain
from app.modules.appointments.models import IdempotencyRecord
from app.modules.billing import service as billing
from app.modules.billing.models import CreditNote, Invoice, Receipt
from app.modules.catalog.common import missing
from app.modules.identity.context import AuthContext, require_active_context
from app.modules.identity.sessions import SessionService
from app.modules.payments import common
from app.modules.payments.mock import MockPaymentProvider
from app.modules.payments.models import (
    CallbackEvent,
    PaymentAccount,
    PaymentAllocation,
    PaymentAttempt,
    PaymentIntent,
    PaymentTransaction,
    Refund,
)
from app.modules.payments.processing import OPEN, PaymentProcessor
from app.modules.payments.schemas import (
    CreditNoteView,
    InvoiceView,
    PaymentView,
    RefundInput,
    RefundView,
    TransactionView,
)


def view(session: Session, row: PaymentAttempt) -> PaymentView:
    intent = common.intent(session, row)
    appointment = common.appointment(session, intent.appointment_id)
    transactions = []
    for transaction in session.scalars(
        select(PaymentTransaction)
        .where(PaymentTransaction.attempt_id == row.id)
        .order_by(PaymentTransaction.created_at)
    ):
        receipt = session.scalar(select(Receipt).where(Receipt.transaction_id == transaction.id))
        assert receipt is not None
        transactions.append(
            TransactionView(
                id=transaction.id,
                amount=transaction.amount,
                currency=transaction.currency,
                is_test=transaction.is_test,
                received_at=transaction.received_at,
                allocated=session.scalar(
                    select(PaymentAllocation.id).where(
                        PaymentAllocation.transaction_id == transaction.id
                    )
                )
                is not None,
                receipt_number=receipt.number,
                refunds=[
                    RefundView.model_validate(refund)
                    for refund in session.scalars(
                        select(Refund)
                        .where(Refund.transaction_id == transaction.id)
                        .order_by(Refund.created_at)
                    )
                ],
            )
        )
    return PaymentView(
        id=row.id,
        appointment_id=intent.appointment_id,
        appointment_status=appointment.status.value,
        intent_id=intent.id,
        intent_status=intent.status,
        status=row.status,
        amount=row.amount,
        currency=row.currency,
        is_test=row.is_test,
        expires_at=intent.expires_at,
        next_check_at=row.next_check_at,
        failure_code=row.failure_code,
        checkout_path=f"/api/v1/payments/{row.id}/mock-checkout"
        if row.is_test and row.status in OPEN
        else None,
        transactions=transactions,
    )


class PaymentService:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions
        self.database = sessions.database
        self.processor = PaymentProcessor(self.database, sessions.settings)

    def enable_mock(self, context: AuthContext, raw: str, csrf: str) -> dict[str, object]:
        self.processor.provider("mock", True)
        with self.sessions.authorized(context, raw, csrf, management=True) as (session, identity):
            identity.principal.require("salon.manage")
            merchant = f"salonbook-test-{context.tenant_id}"
            account = session.scalar(
                select(PaymentAccount).where(
                    PaymentAccount.provider == "mock", PaymentAccount.merchant_reference == merchant
                )
            )
            if account is None:
                account = PaymentAccount(
                    tenant_id=context.tenant_id,
                    provider="mock",
                    merchant_reference=merchant,
                    is_test=True,
                )
                session.add(account)
                session.flush()
                common.event(
                    session,
                    context.tenant_id,
                    "payment.mock_enabled",
                    account.id,
                    {"is_test": True},
                    actor=identity.user.id,
                )
            return {
                "id": str(account.id),
                "provider": "mock",
                "is_test": True,
                "is_active": account.is_active,
            }

    def create(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, key: str
    ) -> PaymentView:
        attempt_id = domain.retry(lambda: self.prepare(context, raw, csrf, identifier, key))
        self.processor.reconcile(context.tenant_id, attempt_id)
        return self.get(context, raw, attempt_id)

    def prepare(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, key: str
    ) -> UUID:
        with self.sessions.authorized(context, raw, csrf, calendar_read=True) as (
            session,
            identity,
        ):
            appointment = common.appointment(session, identifier, lock=True)
            common.financial_access(session, identity.principal, appointment, pay=True)
            request_key = sha256(f"{identity.user.id}:{key}".encode()).hexdigest()
            digest = sha256(str(identifier).encode()).digest()
            stored = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.actor_id == identity.user.id,
                    IdempotencyRecord.operation == "payment.create",
                    IdempotencyRecord.key == key,
                )
            )
            if stored:
                if stored.request_hash != digest:
                    raise AppError(
                        "idempotency_conflict", "This key was used for another appointment.", 409
                    )
                if stored.expires_at <= datetime.now(UTC):
                    raise AppError(
                        "idempotency_expired",
                        "Review the existing payment before using a new key.",
                        409,
                    )
                assert stored.response_body is not None
                return UUID(stored.response_body["id"])
            intent = session.scalar(
                select(PaymentIntent)
                .where(PaymentIntent.appointment_id == identifier)
                .with_for_update()
            )
            if intent:
                previous = session.scalar(
                    select(PaymentAttempt).where(
                        PaymentAttempt.intent_id == intent.id,
                        PaymentAttempt.request_key == request_key,
                    )
                )
                if previous:
                    return previous.id
            if (
                appointment.status != AppointmentStatus.AWAITING_PAYMENT
                or appointment.hold_expires_at is None
                or appointment.hold_expires_at <= datetime.now(UTC)
            ):
                raise AppError("live_hold_required", "A live unpaid hold is required.", 409)
            if appointment.total_amount <= 0:
                raise AppError("payment_not_required", "This appointment needs no payment.", 409)
            account = session.scalar(
                select(PaymentAccount)
                .where(
                    PaymentAccount.is_active.is_(True),
                    PaymentAccount.is_test == appointment.is_test,
                )
                .order_by(PaymentAccount.created_at)
                .limit(1)
            )
            if account is None:
                raise AppError(
                    "payment_unavailable", "No payment account is enabled for this salon.", 409
                )
            self.processor.provider(account.provider, account.is_test)
            if intent is None:
                intent = PaymentIntent(
                    tenant_id=context.tenant_id,
                    appointment_id=identifier,
                    amount=appointment.total_amount,
                    currency=appointment.currency,
                    is_test=appointment.is_test,
                    expires_at=appointment.hold_expires_at,
                )
                session.add(intent)
                session.flush()
            opened = session.scalar(
                select(PaymentAttempt.id).where(
                    PaymentAttempt.intent_id == intent.id, PaymentAttempt.status.in_(OPEN)
                )
            )
            if opened:
                raise AppError(
                    "payment_in_progress",
                    "A payment is already in progress for this appointment.",
                    409,
                )
            row = PaymentAttempt(
                tenant_id=context.tenant_id,
                intent_id=intent.id,
                account_id=account.id,
                amount=intent.amount,
                currency=intent.currency,
                is_test=intent.is_test,
                request_key=request_key,
                next_check_at=datetime.now(UTC),
            )
            session.add(row)
            intent.status = PaymentStatus.CREATED
            session.flush()
            session.add(
                IdempotencyRecord(
                    tenant_id=context.tenant_id,
                    actor_id=identity.user.id,
                    operation="payment.create",
                    key=key,
                    request_hash=digest,
                    state="COMPLETED",
                    response_status=201,
                    response_body={"id": str(row.id)},
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
            )
            common.event(
                session,
                context.tenant_id,
                "payment.created",
                row.id,
                {"appointment_id": str(identifier), "amount": row.amount, "is_test": row.is_test},
                actor=identity.user.id,
            )
            return row.id

    def get(self, context: AuthContext, raw: str, identifier: UUID) -> PaymentView:
        with self.sessions.authorized(context, raw) as (session, identity):
            row = common.attempt(session, identifier)
            common.financial_access(
                session,
                identity.principal,
                common.appointment(session, common.intent(session, row).appointment_id),
            )
            return view(session, row)

    def list(
        self,
        context: AuthContext,
        raw: str,
        identifier: UUID,
        limit: int,
        offset: int,
        *,
        newest_first: bool = False,
    ) -> list[PaymentView]:
        with self.sessions.authorized(context, raw) as (session, identity):
            common.financial_access(
                session, identity.principal, common.appointment(session, identifier)
            )
            return [
                view(session, row)
                for row in session.scalars(
                    select(PaymentAttempt)
                    .join(PaymentIntent, PaymentIntent.id == PaymentAttempt.intent_id)
                    .where(PaymentIntent.appointment_id == identifier)
                    .order_by(
                        PaymentAttempt.created_at.desc()
                        if newest_first
                        else PaymentAttempt.created_at,
                        PaymentAttempt.id.desc() if newest_first else PaymentAttempt.id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def verify(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        identifier: UUID,
        scenario: str | None = None,
    ) -> PaymentView:
        with self.sessions.authorized(context, raw, csrf) as (session, identity):
            row = common.attempt(session, identifier)
            common.financial_access(
                session,
                identity.principal,
                common.appointment(session, common.intent(session, row).appointment_id),
                pay=True,
            )
            order, account = common.order(session, row)
            provider = self.processor.provider(account.provider, account.is_test)
        if scenario is not None:
            if not isinstance(provider, MockPaymentProvider):
                raise AppError("not_mock", "This is not a test checkout.", 409)
            provider.simulate(order, scenario)
        self.processor.reconcile(context.tenant_id, identifier)
        return self.get(context, raw, identifier)

    def callback(self, context: AuthContext, identifier: UUID) -> None:
        # Unauthenticated return is only a coalesced durable wake-up, never proof of payment.
        with self.database.transaction(context.tenant_id) as session:
            require_active_context(session, context)
            row = common.attempt(session, identifier)
            session.refresh(row, with_for_update=True)
            if (
                session.scalar(
                    select(CallbackEvent.id).where(
                        CallbackEvent.attempt_id == identifier,
                        CallbackEvent.provider_event_id == "browser-return",
                    )
                )
                is None
            ):
                session.add(
                    CallbackEvent(
                        tenant_id=context.tenant_id,
                        attempt_id=identifier,
                        provider_event_id="browser-return",
                        outcome="QUEUED",
                        safe_payload={},
                    )
                )
            if row.status != PaymentStatus.SUCCEEDED and (
                row.next_check_at is None or row.next_check_at > datetime.now(UTC)
            ):
                row.next_check_at = datetime.now(UTC)

    def request_refund(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        transaction_id: UUID,
        key: str,
        payload: RefundInput,
    ) -> RefundView:
        with self.sessions.authorized(context, raw, csrf, calendar_read=True) as (
            session,
            identity,
        ):
            transaction = session.scalar(
                select(PaymentTransaction).where(PaymentTransaction.id == transaction_id)
            )
            if transaction is None:
                raise missing()
            row = common.attempt(session, transaction.attempt_id)
            appointment = common.appointment(
                session, common.intent(session, row).appointment_id, lock=True
            )
            identity.principal.require("payment.refund", line_id=appointment.line_id)
            # The parent appointment serializes all refund reservations. The receipt is immutable.
            session.refresh(transaction)
            request_key = sha256(f"{identity.user.id}:{key}".encode()).hexdigest()
            refund = session.scalar(select(Refund).where(Refund.request_key == request_key))
            if refund:
                if (refund.transaction_id, refund.amount, refund.reason) != (
                    transaction_id,
                    payload.amount,
                    payload.reason,
                ):
                    raise AppError(
                        "idempotency_conflict", "This key was used for different refund terms.", 409
                    )
                return RefundView.model_validate(refund)
            if payload.amount > common.remaining(session, transaction):
                raise AppError(
                    "refund_exceeds_balance", "Refund exceeds the unreserved payment balance.", 409
                )
            refund = Refund(
                tenant_id=context.tenant_id,
                transaction_id=transaction.id,
                captured_amount=transaction.amount,
                amount=payload.amount,
                currency=transaction.currency,
                is_test=transaction.is_test,
                status=RefundStatus.REQUESTED,
                request_key=request_key,
                requested_by_id=identity.user.id,
                reason=payload.reason,
            )
            session.add(refund)
            session.flush()
            common.event(
                session,
                context.tenant_id,
                "refund.requested",
                refund.id,
                {"amount": refund.amount},
                actor=identity.user.id,
                reason=refund.reason,
            )
            return RefundView.model_validate(refund)

    def refund_action(
        self, context: AuthContext, raw: str, csrf: str, identifier: UUID, action: str
    ) -> RefundView:
        with self.sessions.authorized(context, raw, csrf, calendar_read=True) as (
            session,
            identity,
        ):
            refund = session.scalar(select(Refund).where(Refund.id == identifier))
            if refund is None:
                raise missing()
            transaction = session.scalar(
                select(PaymentTransaction).where(PaymentTransaction.id == refund.transaction_id)
            )
            assert transaction is not None
            row = common.attempt(session, transaction.attempt_id)
            appointment = common.appointment(
                session, common.intent(session, row).appointment_id, lock=True
            )
            identity.principal.require("payment.refund", line_id=appointment.line_id)
            session.refresh(refund, with_for_update=True)
            if action == "approve" and refund.status == RefundStatus.REQUESTED:
                refund.status, refund.approved_by_id = RefundStatus.APPROVED, identity.user.id
                refund.next_check_at = datetime.now(UTC)
                common.event(
                    session,
                    context.tenant_id,
                    "refund.approved",
                    refund.id,
                    {"amount": refund.amount},
                    actor=identity.user.id,
                    reason=refund.reason,
                )
            elif action == "cancel" and refund.status == RefundStatus.REQUESTED:
                refund.status = RefundStatus.CANCELLED
                common.event(
                    session,
                    context.tenant_id,
                    "refund.cancelled",
                    refund.id,
                    {"amount": refund.amount},
                    actor=identity.user.id,
                    reason=refund.reason,
                )
            elif action == "cancel" and refund.status != RefundStatus.CANCELLED:
                raise AppError(
                    "invalid_transition", "Only an unapproved refund can be cancelled.", 409
                )
            elif action == "approve" and refund.status in {
                RefundStatus.CANCELLED,
                RefundStatus.FAILED,
            }:
                raise AppError(
                    "invalid_transition",
                    "Create a new refund request after reviewing this result.",
                    409,
                )
            session.flush()
        if action == "approve":
            self.processor.refund(context.tenant_id, identifier)
        return self.get_refund(context, raw, identifier)

    def get_refund(self, context: AuthContext, raw: str, identifier: UUID) -> RefundView:
        with self.sessions.authorized(context, raw) as (session, identity):
            refund = session.scalar(select(Refund).where(Refund.id == identifier))
            if refund is None:
                raise missing()
            transaction = session.scalar(
                select(PaymentTransaction).where(PaymentTransaction.id == refund.transaction_id)
            )
            assert transaction is not None
            row = common.attempt(session, transaction.attempt_id)
            common.financial_access(
                session,
                identity.principal,
                common.appointment(session, common.intent(session, row).appointment_id),
            )
            return RefundView.model_validate(refund)

    def invoice(self, context: AuthContext, raw: str, identifier: UUID) -> InvoiceView:
        with self.sessions.authorized(context, raw) as (session, identity):
            common.financial_access(
                session, identity.principal, common.appointment(session, identifier)
            )
            row = session.scalar(select(Invoice).where(Invoice.appointment_id == identifier))
            if row is None:
                raise missing()
            return billing.invoice_view(session, row)

    def credit_note(self, context: AuthContext, raw: str, identifier: UUID) -> CreditNoteView:
        refund = self.get_refund(context, raw, identifier)
        with self.database.transaction(context.tenant_id, read_only=True) as session:
            row = session.scalar(select(CreditNote).where(CreditNote.refund_id == identifier))
            if row is None:
                raise missing()
            return CreditNoteView(number=row.number, issued_at=row.issued_at, refund=refund)
