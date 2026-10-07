"""Opt-in random staff credentials for disposable previews only."""

import json
import secrets
from pathlib import Path
from uuid import UUID

from psycopg import sql
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.access.models import Role, RoleAssignment
from app.modules.catalog.models import Line
from app.modules.identity.models import CustomerProfile, User
from app.modules.identity.security import Security
from app.modules.workforce.models import EmployeeProfile
from scripts.postgres_lab import PostgresLab, execute_sql


def write_credentials(local: Path, credentials: dict[str, dict[str, str]], port: int) -> None:
    local.mkdir(exist_ok=True)
    (local / "dashboard-demo.json").write_text(
        json.dumps(credentials, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# حساب‌های پیش‌نمایش سالن‌بوک",
        "",
        "فقط برای دیتابیس آزمایشی همین اجرا؛ با راه‌اندازی دوبارهٔ پیش‌نمایش، رمزها تغییر می‌کنند.",
        "",
        f"[ورود به پنل سالن](http://127.0.0.1:{port}/dashboard) · [ورود مدیر کل](http://127.0.0.1:{port}/platform)",
        "",
        "| نقش | شماره موبایل | رمز عبور |",
        "|---|---|---|",
    ]
    for code, label in {
        "salon_manager": "مدیر سالن",
        "line_manager": "مدیر لاین",
        "employee": "کارمند",
        "super_admin": "مدیر کل",
    }.items():
        account = credentials[code]
        lines.append(f"| {label} | {account['phone']} | `{account['password']}` |")
    lines.extend(
        [
            "",
            "این فایل حاوی رمزهای آزمایشی است؛ آن را منتشر نکنید. حساب واقعی، ایمیل یا کد پیامکی در این پیش‌نمایش ایجاد نمی‌شود.",
            "",
        ]
    )
    (local / "preview-accounts.md").write_text("\n".join(lines), encoding="utf-8")


def platform_login(lab: PostgresLab) -> str:
    password = secrets.token_urlsafe(32)
    with lab.admin.begin() as connection:
        execute_sql(
            connection,
            (Path(__file__).resolve().parents[1] / "sql/platform_grants.sql").read_text(
                encoding="utf-8"
            ),
        )
        connection.exec_driver_sql(
            sql.SQL(
                "CREATE ROLE salonbook_test_platform LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}"
            )
            .format(sql.Literal(password))
            .as_string()
        )
        connection.exec_driver_sql("GRANT salonbook_platform TO salonbook_test_platform")
    return lab.admin.url.set(
        username="salonbook_test_platform", password=password
    ).render_as_string(hide_password=False)


def staff_accounts(engine: Engine, tenant: UUID, security: Security) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    with Session(engine) as session, session.begin():
        roles = {r.code: r for r in session.scalars(select(Role).where(Role.tenant_id == tenant))}
        line = session.scalar(
            select(Line).where(Line.tenant_id == tenant, Line.slug == "hair-studio")
        )
        assert line is not None
        employee = session.scalar(
            select(EmployeeProfile)
            .where(EmployeeProfile.tenant_id == tenant)
            .order_by(EmployeeProfile.public_name)
        )
        assert employee is not None
        for code, phone, name in (
            ("line_manager", "09120000002", "مدیر استودیوی مو"),
            ("employee", "09120000003", employee.public_name),
        ):
            password = secrets.token_urlsafe(24)
            user = (
                session.get(User, (tenant, employee.user_id))
                if code == "employee"
                else User(tenant_id=tenant, display_name=name)
            )
            assert user is not None
            user.phone_normalized = "+98" + phone[1:]
            user.password_hash = security.hash_password(password)
            session.add(user)
            session.flush()
            session.add(
                CustomerProfile(tenant_id=tenant, user_id=user.id, contact_preference="NONE")
            )
            for rolecode in ("customer", code):
                session.add(
                    RoleAssignment(
                        tenant_id=tenant,
                        user_id=user.id,
                        role_id=roles[rolecode].id,
                        scope="LINE" if rolecode == "line_manager" else "TENANT",
                        line_id=line.id if rolecode == "line_manager" else None,
                    )
                )
            result[code] = {"phone": phone, "password": password, "name": name}
        result["scope"] = {"line_id": str(line.id), "employee_id": str(employee.id)}
    return result
