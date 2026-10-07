"""Exercise line/service/employee management over real HTTP in a disposable salon."""

from typing import Any

import httpx2

from scripts.check_management_preview import run_preview_check, sign_in


def check(origin: str, password: str) -> None:
    with (
        httpx2.Client(base_url=origin, trust_env=False, timeout=10) as manager,
        httpx2.Client(base_url=origin, trust_env=False, timeout=10) as visitor,
    ):
        csrf = sign_in(manager, origin, "09123456789", password)
        headers = {"Origin": origin, "X-CSRF-Token": csrf}

        def change(method: str, path: str, data: dict[str, Any], expected: int) -> httpx2.Response:
            response = manager.request(method, f"/api/v1{path}", json=data, headers=headers)
            assert response.status_code == expected, f"Catalog {method} {path} failed"
            return response

        line = change("POST", "/lines", {"name": "Hair", "slug": "hair"}, 201).json()["id"]
        product = change("POST", "/services", {"name": "Haircut", "code": "cut"}, 201).json()["id"]
        account = change(
            "POST",
            "/users",
            {
                "phone": "09121234567",
                "password": password,
                "display_name": "Stylist",
                "kind": "employee",
            },
            201,
        ).json()
        employee = account["employee"]["id"]
        offer_path = f"/lines/{line}/services/{product}"
        link_path = f"/lines/{line}/employees/{employee}"
        skill_path = f"{link_path}/services/{product}"
        public_path = f"/api/v1/catalog/lines/{line}/services/{product}/employees"
        offer = {
            "price_amount": 1_000_000,
            "duration_minutes": 30,
            "buffer_before_minutes": 5,
            "buffer_after_minutes": 10,
        }
        change("PUT", offer_path, offer, 200)
        change("PUT", link_path, {}, 200)
        change("PUT", skill_path, {}, 200)
        assert visitor.get(public_path).json()["items"] == [
            {"id": employee, "public_name": "Stylist"}
        ]
        assert visitor.get("/api/v1/employees").status_code == 401
        change("PUT", offer_path, {**offer, "price_amount": 2_000_000, "duration_minutes": 45}, 200)
        current = visitor.get(f"/api/v1/catalog/lines/{line}/services").json()["items"][0]
        assert current["price_amount"] == 2_000_000 and current["duration_minutes"] == 45
        change("DELETE", link_path, {}, 204)
        change("PUT", link_path, {}, 200)
        assert visitor.get(public_path).json()["items"] == []
        change("PUT", skill_path, {}, 200)
        change(
            "PUT",
            f"/users/{account['id']}/employee",
            {"public_name": "Stylist", "is_active": False},
            200,
        )
        assert visitor.get(public_path).json()["items"] == []
        change("DELETE", f"/employees/{employee}", {}, 204)
        change("DELETE", f"/services/{product}", {}, 204)
        change("DELETE", f"/lines/{line}", {}, 204)
        assert visitor.get("/api/v1/catalog/lines").json()["items"] == []


def main() -> None:
    run_preview_check(
        check,
        "PASS: real HTTP lines, services, prices, employees, assignments, public privacy and soft deletion checks.",
    )


if __name__ == "__main__":
    main()
