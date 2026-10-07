"""Exercise localhost mobile login without email, SMS or printing credentials."""

import argparse
import secrets
from uuid import uuid4

import httpx2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    origin = f"http://127.0.0.1:{args.port}"
    phone = f"0912{secrets.randbelow(10_000_000):07d}"
    password, changed_password = uuid4().hex, uuid4().hex
    with httpx2.Client(base_url=origin, trust_env=False, timeout=15) as client:

        def public(path: str, data: dict[str, str]) -> httpx2.Response:
            csrf = client.get("/api/v1/auth/csrf")
            assert csrf.status_code == 200
            return client.post(
                f"/api/v1/auth/{path}",
                json=data,
                headers={"Origin": origin, "X-CSRF-Token": csrf.json()["csrf_token"]},
            )

        assert client.get("/api/v1/health/ready").status_code == 200
        assert (
            public(
                "register",
                {"phone": phone, "password": password, "display_name": "Local verification"},
            ).status_code
            == 202
        )
        signed_in = public("login", {"phone": "+98" + phone[1:], "password": password})
        assert signed_in.status_code == 200
        user = client.get("/api/v1/auth/me").json()["user"]
        assert user["phone"] == "+98" + phone[1:] and user["phone_verified"] is False
        assert "email" not in user
        headers = {"Origin": origin, "X-CSRF-Token": signed_in.json()["csrf_token"]}
        assert (
            client.post(
                "/api/v1/auth/change-password",
                json={"current_password": password, "new_password": changed_password},
                headers=headers,
            ).status_code
            == 204
        )
        assert client.get("/api/v1/auth/me").status_code == 401
        assert public("login", {"phone": phone, "password": password}).status_code == 401
        signed_in = public("login", {"phone": phone, "password": changed_password})
        assert signed_in.status_code == 200
        assert (
            client.post(
                "/api/v1/auth/logout",
                json={},
                headers={"Origin": origin, "X-CSRF-Token": signed_in.json()["csrf_token"]},
            ).status_code
            == 204
        )
        assert client.get("/api/v1/auth/me").status_code == 401
    print(
        "PASS: mobile-only registration, normalized phone login, password change, session revocation and logout; no email or SMS."
    )


if __name__ == "__main__":
    main()
