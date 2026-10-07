"""Serve the separate platform application with SALONBOOK_PLATFORM_* settings."""

import uvicorn

from app.platform.main import create_platform_app


def main() -> None:
    uvicorn.run(
        create_platform_app(),
        host="127.0.0.1",
        port=8001,
        proxy_headers=False,
        server_header=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
