from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

Dimension = Literal["line", "employee", "service"]
DocumentKind = Literal["payments", "refunds", "invoices"]


class Totals(BaseModel):
    received: str
    refunded: str
    net: str
    allocated_received: str
    allocated_refunded: str
    revenue: str
    unallocated_net: str


class Daily(Totals):
    day: date


class Report(BaseModel):
    start: date
    end: date
    timezone: str
    is_test: bool
    currency: str = "IRR"
    generated_at: datetime
    totals: Totals
    daily: list[Daily]


class Breakdown(BaseModel):
    id: UUID
    name: str
    received: str
    refunded: str
    net: str


class Document(BaseModel):
    id: UUID
    appointment_id: UUID
    line_id: UUID
    number: str | None
    at: datetime
    amount: str
    status: str
    allocated: bool | None = None
    refundable: str | None = None
    reason: str | None = None


class InvoiceLine(BaseModel):
    description: str
    amount: str


class InvoiceDocument(BaseModel):
    id: UUID
    number: str
    amount: str
    is_test: bool
    issued_at: datetime
    seller: str
    buyer: str
    items: list[InvoiceLine]
