"""Single metadata registration point for migrations, tests and future services."""

from sqlalchemy import Index, PrimaryKeyConstraint, UniqueConstraint

from app.db.base import Base
from app.modules.access import models as access
from app.modules.appointments import models as appointments
from app.modules.billing import models as billing
from app.modules.catalog import models as catalog
from app.modules.identity import models as identity
from app.modules.operations import models as operations
from app.modules.payments import models as payments
from app.modules.scheduling import models as scheduling
from app.modules.tenancy import models as tenancy
from app.modules.workforce import models as workforce

__all__ = [
    "Base",
    "access",
    "appointments",
    "billing",
    "catalog",
    "identity",
    "operations",
    "payments",
    "scheduling",
    "tenancy",
    "workforce",
]


def _index_foreign_keys() -> None:
    """Add deterministic FK indexes unless an existing full B-tree covers the prefix."""
    for table in Base.metadata.tables.values():
        covered = [
            tuple(c.name for c in key.columns)
            for key in table.constraints
            if isinstance(key, (PrimaryKeyConstraint, UniqueConstraint))
        ]
        covered += [
            tuple(c.name for c in key.columns)
            for key in table.indexes
            if key.dialect_options["postgresql"].get("where") is None
            and key.dialect_options["postgresql"].get("using") in (False, None, "btree")
        ]
        for fk in sorted(table.foreign_key_constraints, key=lambda key: str(key.name)):
            columns = tuple(c.name for c in fk.columns)
            if not any(prefix[: len(columns)] == columns for prefix in covered):
                Index(None, *(table.c[name] for name in columns))
                covered.append(columns)


_index_foreign_keys()
