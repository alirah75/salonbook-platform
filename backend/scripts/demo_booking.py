"""Catalog fixtures exclusively for the disposable local preview; no usable staff logins."""

from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.enums import CalendarScope
from app.modules.catalog.models import Line, LineService, Service
from app.modules.identity.models import User
from app.modules.payments.models import PaymentAccount
from app.modules.scheduling.models import Calendar, WeeklyPeriod
from app.modules.workforce.models import EmployeeLine, EmployeeProfile, EmployeeService


def seed_booking_demo(engine: Engine, tenant: UUID) -> None:
    with Session(engine) as session, session.begin():
        products = [
            Service(tenant_id=tenant, name=name, code=code, description=description)
            for name, code, description in [
                ("کوتاهی و فرم مو", "haircut", "فرمی تازه، متناسب با چهره و سلیقهٔ شما."),
                ("براشینگ مو", "styling", "برای یک روز خاص یا حس خوب هر روز."),
                (
                    "مشاورهٔ زیبایی",
                    "consultation",
                    "گفت‌وگویی کوتاه برای انتخاب مراقبت مناسب؛ رایگان.",
                ),
            ]
        ]
        lines = [
            Line(tenant_id=tenant, name=name, slug=slug)
            for name, slug in [("استودیوی مو", "hair-studio"), ("استودیوی زیبایی", "beauty-studio")]
        ]
        session.add_all([*products, *lines])
        session.flush()
        for line in lines:
            for product, amount, duration in zip(
                products, [1_800_000, 1_200_000, 0], [45, 30, 15], strict=True
            ):
                session.add(
                    LineService(
                        tenant_id=tenant,
                        line_id=line.id,
                        service_id=product.id,
                        price_amount=amount,
                        currency="IRR",
                        duration_minutes=duration,
                        buffer_before_minutes=0,
                        buffer_after_minutes=5,
                        is_free=amount == 0,
                    )
                )
        session.flush()
        salon_calendar = session.scalar(
            select(Calendar).where(
                Calendar.tenant_id == tenant, Calendar.scope == CalendarScope.SALON
            )
        )
        if salon_calendar is None:
            salon_calendar = Calendar(tenant_id=tenant, scope=CalendarScope.SALON)
            session.add(salon_calendar)
        calendars = [salon_calendar]
        for name in ["نگار", "سارا"]:
            # No phone or email; the random invalid password hash cannot authenticate.
            user = User(
                tenant_id=tenant, display_name=name, password_hash=f"unusable:{uuid4().hex}"
            )
            session.add(user)
            session.flush()
            employee = EmployeeProfile(tenant_id=tenant, user_id=user.id, public_name=name)
            session.add(employee)
            session.flush()
            for line in lines:
                session.add(
                    EmployeeLine(tenant_id=tenant, employee_id=employee.id, line_id=line.id)
                )
            session.flush()
            for line in lines:
                for product in products:
                    session.add(
                        EmployeeService(
                            tenant_id=tenant,
                            employee_id=employee.id,
                            line_id=line.id,
                            service_id=product.id,
                        )
                    )
            calendar = Calendar(
                tenant_id=tenant, scope=CalendarScope.EMPLOYEE, employee_id=employee.id
            )
            session.add(calendar)
            calendars.append(calendar)
        session.flush()
        today = datetime.now(ZoneInfo("Asia/Tehran")).date()
        for calendar in calendars:
            for weekday in range(7):
                session.add(
                    WeeklyPeriod(
                        tenant_id=tenant,
                        calendar_id=calendar.id,
                        weekday=weekday,
                        start_minute=540,
                        end_minute=1140,
                        valid_from=today,
                    )
                )
        session.add(
            PaymentAccount(
                tenant_id=tenant, provider="mock", merchant_reference=uuid4().hex, is_test=True
            )
        )
