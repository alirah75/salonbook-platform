"""One-time authoring tool for the initial schema; refuses to replace a revision."""

import os
from pathlib import Path

from alembic.config import Config

from alembic import command
from scripts.postgres_lab import temporary_postgres


def main() -> None:
    versions = Path("alembic/versions")
    versions.mkdir(exist_ok=True)
    if list(versions.glob("*.py")):
        raise SystemExit("Refusing to regenerate an existing migration history.")
    with temporary_postgres() as lab:
        os.environ["DATABASE_MIGRATION_URL"] = lab.owner_url
        command.revision(
            Config("alembic.ini"),
            message="initial relational schema",
            autogenerate=True,
            rev_id="0001",
        )
    revision = next(versions.glob("0001_*.py"))
    source = revision.read_text(encoding="utf-8")
    source = source.replace(
        "def upgrade() -> None:\n",
        "def upgrade() -> None:\n    op.execute('CREATE EXTENSION IF NOT EXISTS btree_gist')\n",
        1,
    )
    revision.write_text(source, encoding="utf-8")
    print(f"Created {revision}; review PostgreSQL-specific constraints before use.")


if __name__ == "__main__":
    main()
