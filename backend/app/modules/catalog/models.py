from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Mutable, SoftDelete, TenantRecord, tenant_fk


class Line(TenantRecord, Mutable, SoftDelete, Base):
    __tablename__ = "lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug"),
        CheckConstraint("length(trim(name)) > 0", name="name"),
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Service(TenantRecord, Mutable, SoftDelete, Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class LineService(TenantRecord, Mutable, SoftDelete, Base):
    """Sellable offer: price and duration can differ by line."""

    __tablename__ = "line_services"
    __table_args__ = (
        tenant_fk("line_id", "lines"),
        tenant_fk("service_id", "services"),
        UniqueConstraint("tenant_id", "line_id", "service_id"),
        CheckConstraint("price_amount >= 0 AND is_free = (price_amount = 0)", name="price"),
        CheckConstraint("currency = 'IRR'", name="currency"),
        CheckConstraint("duration_minutes BETWEEN 1 AND 1440", name="duration"),
        CheckConstraint(
            "buffer_before_minutes BETWEEN 0 AND 240 AND buffer_after_minutes BETWEEN 0 AND 240",
            name="buffers",
        ),
    )
    line_id: Mapped[UUID]
    service_id: Mapped[UUID]
    price_amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default="IRR")
    duration_minutes: Mapped[int] = mapped_column(Integer)
    buffer_before_minutes: Mapped[int] = mapped_column(Integer, server_default="0")
    buffer_after_minutes: Mapped[int] = mapped_column(Integer, server_default="0")
    is_free: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
