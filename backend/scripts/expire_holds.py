"""Run expiry with a runtime database account and an explicit tenant."""

import argparse
from pathlib import Path
from threading import Event
from uuid import UUID

from app.core.config import Settings
from app.db.database import Database
from app.modules.appointments.expiry import ExpiryService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, choices=range(1, 61), default=5)
    args = parser.parse_args()
    database = Database(Settings(_env_file=args.env_file))
    try:
        database.validate_ready()
        worker = ExpiryService(database)
        if args.once:
            print(f"Expired {worker.batch(args.tenant)} holds.")
        else:
            worker.run(args.tenant, Event(), args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
