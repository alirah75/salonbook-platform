"""Persisted states. Transition rules belong to their domain services."""

from enum import StrEnum


class AppointmentStatus(StrEnum):
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    EXPIRED = "EXPIRED"


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class RefundStatus(StrEnum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    PROCESSING = "PROCESSING"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CalendarScope(StrEnum):
    SALON = "SALON"
    LINE = "LINE"
    EMPLOYEE = "EMPLOYEE"
    EMPLOYEE_LINE = "EMPLOYEE_LINE"


class DayOverrideMode(StrEnum):
    CLOSED = "CLOSED"
    REPLACE = "REPLACE"


class BlockKind(StrEnum):
    LEAVE = "LEAVE"
    HOLIDAY = "HOLIDAY"
    BLOCKED = "BLOCKED"


class BlockStatus(StrEnum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TokenPurpose(StrEnum):
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    PASSWORD_RESET = "PASSWORD_RESET"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    DEAD = "DEAD"
