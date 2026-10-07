"""Run the API with an explicitly provided runtime database configuration."""

import argparse
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def run_server(settings: Settings, host: str, port: int) -> None:
    """Proxy trust is disabled until the reverse-proxy deployment is configured."""
    app = create_app(settings)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_config=None,
        access_log=False,
        proxy_headers=False,
        server_header=False,
        timeout_keep_alive=5,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()
    try:
        settings = Settings(_env_file=args.env_file)
    except ValidationError as exc:
        fields = ", ".join(
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors(include_input=False, include_context=False, include_url=False)
        )
        raise SystemExit(f"Invalid configuration. Check: {fields}") from None
    run_server(settings, args.host, args.port)


if __name__ == "__main__":
    main()
