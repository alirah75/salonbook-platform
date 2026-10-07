from uuid import UUID

from sqlalchemy import Boolean, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Mutable, SoftDelete, TenantRecord, tenant_fk


class EmployeeProfile(TenantRecord, Mutable, SoftDelete, Base):
    __tablename__ = "employee_profiles"
    __table_args__ = (tenant_fk("user_id", "users"), UniqueConstraint("tenant_id", "user_id"))
    user_id: Mapped[UUID]
    public_name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class EmployeeLine(TenantRecord, Mutable, SoftDelete, Base):
    __tablename__ = "employee_lines"
    __table_args__ = (
        tenant_fk("employee_id", "employee_profiles"),
        tenant_fk("line_id", "lines"),
        UniqueConstraint("tenant_id", "employee_id", "line_id"),
    )
    employee_id: Mapped[UUID]
    line_id: Mapped[UUID]
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class EmployeeService(TenantRecord, Mutable, SoftDelete, Base):
    __tablename__ = "employee_services"
    __table_args__ = (
        tenant_fk(("employee_id", "line_id"), "employee_lines", ("employee_id", "line_id")),
        tenant_fk(("line_id", "service_id"), "line_services", ("line_id", "service_id")),
        UniqueConstraint("tenant_id", "employee_id", "line_id", "service_id"),
    )
    employee_id: Mapped[UUID]
    line_id: Mapped[UUID]
    service_id: Mapped[UUID]
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
