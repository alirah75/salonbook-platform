"""Provider boundary: no application transaction may be held during these calls."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

Outcome = Literal["PENDING", "SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"]


@dataclass(frozen=True)
class Capabilities:
    idempotent_create: bool = True
    lookup_by_request_key: bool = True
    refunds: bool = True
    idempotent_refund: bool = True


@dataclass(frozen=True)
class Order:
    tenant: UUID
    account: UUID
    merchant: str
    request_key: str
    amount: int
    currency: str
    expires_at: datetime


@dataclass(frozen=True)
class Verification:
    outcome: Outcome
    merchant: str
    order_id: str
    amount: int
    currency: str
    transaction_id: str | None = None
    received_at: datetime | None = None


@dataclass(frozen=True)
class RefundResult:
    outcome: Outcome
    refund_id: str | None = None
    merchant: str | None = None
    transaction_id: str | None = None
    amount: int | None = None
    currency: str | None = None


class PaymentProvider(Protocol):
    capabilities: Capabilities

    def create(self, order: Order) -> str: ...

    def verify(self, order: Order, gateway_order_id: str) -> Verification: ...

    def status(self, order: Order) -> Verification: ...

    def refund(self, order: Order, transaction_id: str, key: str, amount: int) -> RefundResult: ...

    def refund_status(self, order: Order, key: str) -> RefundResult: ...


class ProviderUnavailable(Exception):
    """Unknown transport outcome, never evidence of failure."""
