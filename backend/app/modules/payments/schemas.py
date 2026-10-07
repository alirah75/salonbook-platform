from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.base import JsonObject
from app.db.enums import PaymentStatus, RefundStatus


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreatePayment(Input):
    appointment_id: UUID


class Simulation(Input):
    scenario: Literal["success", "failure", "cancel", "timeout", "amount_mismatch"]


class RefundInput(Input):
    amount: int = Field(gt=0, le=10**15, strict=True)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A reason is required.")
        return value.strip()


class RefundView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    transaction_id: UUID
    amount: int
    currency: str
    is_test: bool
    status: RefundStatus
    reason: str
    succeeded_at: datetime | None


class TransactionView(BaseModel):
    id: UUID
    amount: int
    currency: str
    is_test: bool
    allocated: bool
    received_at: datetime
    receipt_number: str
    refunds: list[RefundView]


class PaymentView(BaseModel):
    id: UUID
    appointment_id: UUID
    appointment_status: str
    intent_id: UUID
    intent_status: PaymentStatus
    status: PaymentStatus
    amount: int
    currency: str
    is_test: bool
    expires_at: datetime
    checkout_path: str | None
    next_check_at: datetime | None
    failure_code: str | None
    transactions: list[TransactionView]


class InvoiceLine(BaseModel):
    position: int
    description: str
    amount: int


class InvoiceView(BaseModel):
    id: UUID
    appointment_id: UUID
    number: str
    total_amount: int
    currency: str
    is_test: bool
    issued_at: datetime
    seller: JsonObject
    buyer: JsonObject
    items: list[InvoiceLine]


class CreditNoteView(BaseModel):
    number: str
    issued_at: datetime
    refund: RefundView
