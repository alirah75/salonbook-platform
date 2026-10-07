"""Shared persistence conventions; tenant identity is part of every local key."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, ForeignKeyConstraint, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Record:
    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Mutable:
    # The migration installs a DB trigger, covering ORM and direct SQL writes alike.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SoftDelete:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantRecord(Record):
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("salons.id", ondelete="RESTRICT"), primary_key=True
    )


def tenant_fk(
    local: str | tuple[str, ...],
    target: str,
    remote: str | tuple[str, ...] = "id",
) -> ForeignKeyConstraint:
    """Include tenant identity even when a UUID has been guessed or misrouted."""
    local_columns = (local,) if isinstance(local, str) else local
    remote_columns = (remote,) if isinstance(remote, str) else remote
    return ForeignKeyConstraint(
        ["tenant_id", *local_columns],
        [f"{target}.tenant_id", *(f"{target}.{name}" for name in remote_columns)],
        ondelete="RESTRICT",
    )


def enum_type(enum: type[StrEnum], name: str) -> Enum:
    """Portable SQL CHECK-backed enum; altering values is an explicit migration."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


JsonObject = dict[str, Any]
