"""Real HTTP management check in a separate disposable preview; no secrets are printed."""

import secrets
import socket
import time
from collections.abc import Callable
from threading import Thread
from typing import Any

import httpx2
import uvicorn
from pydantic import SecretStr

from app.main import create_app
from app.modules.identity.schemas import RegisterInput
from scripts.dev import preview_environment


def sign_in(client: httpx2.Client, origin: str, phone: str, password: str) -> str:
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    result = client.post(
        "/api/v1/auth/login",
        json={"phone": phone, "password": password},
        headers={"Origin": origin, "X-CSRF-Token": token},
    )
    assert result.status_code == 200, "Login failed"
    csrf: str = result.json()["csrf_token"]
    return csrf


def check(origin: str, password: str) -> None:
    with (
        httpx2.Client(base_url=origin, trust_env=False, timeout=10) as manager,
        httpx2.Client(base_url=origin, trust_env=False, timeout=10) as employee,
    ):
        csrf = sign_in(manager, origin, "09123456789", password)
        headers = {"Origin": origin, "X-CSRF-Token": csrf}

        def change(method: str, path: str, data: dict[str, Any], expected: int) -> httpx2.Response:
            response = manager.request(method, f"/api/v1{path}", json=data, headers=headers)
            assert response.status_code == expected, f"Management {method} {path} failed"
            return response

        assert manager.get("/api/v1/permissions").status_code == 200
        change("PATCH", "/salon", {"name": "HTTP checked salon"}, 200)
        user = change(
            "POST",
            "/users",
            {
                "phone": "09121234567",
                "password": password,
                "display_name": "HTTP employee",
                "kind": "employee",
            },
            201,
        ).json()
        assert "email" not in user and user["phone_verified"] is False
        sign_in(employee, origin, "09121234567", password)
        assert employee.get("/api/v1/users").status_code == 403
        role = change(
            "POST",
            "/roles",
            {"code": "reception", "name": "Reception", "permissions": ["users.read"]},
            201,
        ).json()
        change("POST", f"/users/{user['id']}/roles", {"role_id": role["id"]}, 201)
        assert employee.get("/api/v1/auth/me").status_code == 401
        sign_in(employee, origin, "09121234567", password)
        assert employee.get("/api/v1/users").status_code == 200
        change("PUT", f"/roles/{role['id']}", {"name": "Reception", "permissions": []}, 200)
        assert employee.get("/api/v1/auth/me").status_code == 401
        sign_in(employee, origin, "09121234567", password)
        assert employee.get("/api/v1/users").status_code == 403
        change("PATCH", f"/users/{user['id']}", {"is_active": False}, 200)
        assert employee.get("/api/v1/auth/me").status_code == 401
        change("DELETE", f"/roles/{role['id']}", {}, 204)
        assert manager.get("/api/v1/salon").json()["name"] == "HTTP checked salon"
        assert any(
            item["id"] == user["id"]
            for item in manager.get("/api/v1/users?kind=employee").json()["items"]
        )


def run_preview_check(checker: Callable[[str, str], None], message: str) -> None:
    password = secrets.token_urlsafe(32)
    manager = RegisterInput(
        phone="09123456789", display_name="HTTP manager", password=SecretStr(password)
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        with preview_environment(port, manager) as settings:
            server = uvicorn.Server(
                uvicorn.Config(
                    create_app(settings),
                    host="127.0.0.1",
                    port=port,
                    log_config=None,
                    access_log=False,
                    proxy_headers=False,
                    server_header=False,
                )
            )
            worker = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            worker.start()
            try:
                deadline = time.monotonic() + 15
                while not server.started and worker.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert server.started, "Preview failed to start"
                checker(f"http://127.0.0.1:{port}", password)
                print(message)
            finally:
                server.should_exit = True
                worker.join(timeout=10)
                assert not worker.is_alive(), "Preview did not shut down"


def main() -> None:
    run_preview_check(
        check,
        "PASS: real HTTP salon, user, employee, roles, permissions and session revocation checks.",
    )


if __name__ == "__main__":
    main()
