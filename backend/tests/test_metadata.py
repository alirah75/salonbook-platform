from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.models import Base


def test_every_tenant_relationship_contains_tenant_identity() -> None:
    for table in Base.metadata.tables.values():
        for fk in table.foreign_key_constraints:
            assert isinstance(fk, ForeignKeyConstraint)
            target = fk.referred_table
            if "tenant_id" in table.c and "tenant_id" in target.c:
                assert "tenant_id" in fk.column_keys, (table.name, target.name)


def test_all_tables_compile_for_postgresql() -> None:
    for table in Base.metadata.sorted_tables:
        assert str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]


def test_no_money_column_uses_floating_point() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if "amount" in column.name:
                assert column.type.python_type is int, (table.name, column.name)
