"""Export reviewable schema documentation without connecting to a database."""

import argparse
import ast
import io
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import CheckConstraint, Column, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, DefaultClause

from alembic import command
from app.db.models import Base

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OUTPUT = ROOT / "docs" / "database"
DIALECT = postgresql.dialect()  # type: ignore[no-untyped-call]  # SQLAlchemy dialect factory lacks annotations.


def frozen_list(name: str) -> set[str]:
    tree = ast.parse(
        (BACKEND / "alembic/versions/0002_isolation_and_integrity.py").read_text(encoding="utf-8")
    )
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            return set(value)
    raise ValueError(name)


def escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def dictionary() -> str:
    append_only = frozen_list("APPEND_ONLY_TABLES")
    tenant_tables = frozen_list("TENANT_TABLES") | {"salons"}
    sections = [
        "# فرهنگ دادهٔ مرحلهٔ ۲",
        "",
        "این فایل از مدل‌های SQLAlchemy تولید شده است. توضیح تصمیم‌ها و مرز ضمانت‌ها در سند مرحلهٔ ۲ است. نام‌های طولانی قیود در PostgreSQL به‌صورت قطعی با پسوند Hash کوتاه می‌شوند.",
        "",
        f"تعداد جدول‌ها: **{len(Base.metadata.tables)}**. FKهای تجاری متعلق به سالن، tenant_id را نیز حمل می‌کنند. همهٔ FKها RESTRICT هستند؛ حذف زنجیره‌ای مالی نداریم.",
        "",
    ]
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        lifecycle = (
            "الحاقی؛ Update/Delete با Trigger ممنوع"
            if table.name in append_only
            else "حذف نرم با deleted_at"
            if "deleted_at" in table.c
            else "تغییرپذیر با سیاست Service؛ حذف فیزیکی محدود به Grant و FK"
        )
        sections += [
            f"## {table.name}",
            "",
            f"جداسازی: {'FORCE RLS' if table.name in tenant_tables else 'Control plane / Global؛ دسترسی صریح'}. چرخهٔ عمر: {lifecycle}.",
            "",
            "| ستون | نوع PostgreSQL | تهی مجاز | کلید | پیش‌فرض سمت سرور |",
            "|---|---|---|---|---|",
        ]
        for column in table.columns:
            default = "—"
            if column.computed is not None:
                default = f"GENERATED: {column.computed.sqltext}"
            elif isinstance(column.server_default, DefaultClause):
                default = str(column.server_default.arg)
            keys = [
                name
                for name, yes in (("PK", column.primary_key), ("FK", bool(column.foreign_keys)))
                if yes
            ]
            sections.append(
                f"| {column.name} | {escape(column.type.compile(dialect=DIALECT))} | {'بله' if column.nullable else 'خیر'} | {', '.join(keys) or '—'} | {escape(default)} |"
            )
        sections += ["", "روابط:", ""]
        for fk in sorted(table.foreign_key_constraints, key=lambda item: str(item.name)):
            sections.append(
                f"- ({', '.join(fk.column_keys)}) → {fk.referred_table.name}({', '.join(element.column.name for element in fk.elements)}), ON DELETE RESTRICT."
            )
        if not table.foreign_key_constraints:
            sections.append("- رابطهٔ خروجی ندارد.")
        sections += [
            "",
            "قیود یکتا و اعتبارسنجی:",
            "",
            f"- PK: ({', '.join(column.name for column in table.primary_key.columns)}).",
        ]
        for constraint in sorted(table.constraints, key=lambda item: str(item.name)):
            if isinstance(constraint, UniqueConstraint):
                sections.append(
                    f"- UNIQUE: ({', '.join(column.name for column in constraint.columns)})"
                    + (
                        "؛ NULLS NOT DISTINCT"
                        if constraint.dialect_options["postgresql"].get("nulls_not_distinct")
                        else ""
                    )
                )
            if isinstance(constraint, CheckConstraint):
                expression = str(
                    constraint.sqltext.compile(
                        dialect=DIALECT, compile_kwargs={"literal_binds": True}
                    )
                )
                sections.append(f"- CHECK {constraint.name}: `{expression}`")
        if table.name == "appointments":
            sections.append(
                "- EXCLUDE USING GiST: برابری tenant_id و employee_id همراه با تداخل occupied_period در وضعیت‌های اشغال‌کننده ممنوع است."
            )
        sections += ["", "Indexهای صریح (علاوه بر PK/UNIQUE/Exclusion):", ""]
        for index in sorted(table.indexes, key=lambda item: str(item.name)):
            sections.append(f"- `{CreateIndex(index).compile(dialect=DIALECT)}`")
        if not table.indexes:
            sections.append("- Index اضافه لازم نشده؛ PK/UNIQUE نیازهای فعلی FK را پوشش می‌دهند.")
        sections.append("")
    return "\n".join(sections)


def mermaid_type(column: Column[Any]) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(column.type.compile(dialect=DIALECT))).strip("_")


def erd() -> str:
    lines = ["erDiagram", "    direction LR"]
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        lines.append(f"    {table.name} {{")
        for column in table.columns:
            key = " PK" if column.primary_key else " FK" if column.foreign_keys else ""
            lines.append(f"        {mermaid_type(column)} {column.name}{key}")
        lines.append("    }")
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        for fk in sorted(table.foreign_key_constraints, key=lambda item: str(item.name)):
            optional = any(column.nullable for column in fk.columns)
            keys = [set(column.name for column in table.primary_key.columns)]
            keys += [
                set(column.name for column in constraint.columns)
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            ]
            unique = any(key.issubset(set(fk.column_keys)) for key in keys)
            parent_end = "o|" if optional else "||"
            child_end = "o|" if unique else "o{"
            label = ",".join(name for name in fk.column_keys if name != "tenant_id") or "tenant_id"
            lines.append(
                f'    {fk.referred_table.name} {parent_end}--{child_end} {table.name} : "{label}"'
            )
    return "\n".join(lines) + "\n"


def offline_sql() -> str:
    stream = io.StringIO()
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=stream)
    # Offline placeholder: no credentials, network connection or live database.
    with patch.dict(
        "os.environ",
        {"DATABASE_MIGRATION_URL": "postgresql+psycopg://migration@localhost/salonbook"},
    ):
        command.upgrade(config, "head", sql=True)
    return stream.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail if committed documentation is stale"
    )
    args = parser.parse_args()
    artifacts = {
        "schema-dictionary.md": dictionary(),
        "schema-erd.mmd": erd(),
        "schema.sql": offline_sql(),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, body in artifacts.items():
        path = OUTPUT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != body:
                raise SystemExit(f"Stale schema documentation: {path}")
        else:
            path.write_text(body, encoding="utf-8", newline="\n")
        print(f"{'Checked' if args.check else 'Wrote'} {path}")


if __name__ == "__main__":
    main()
