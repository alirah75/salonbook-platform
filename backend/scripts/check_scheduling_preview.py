"""Check scheduling through real HTTP in an isolated, disposable salon."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx2

from scripts.check_management_preview import run_preview_check, sign_in


def check(origin: str, password: str) -> None:
    with (
        httpx2.Client(base_url=origin, trust_env=False, timeout=10) as manager,
        httpx2.Client(base_url=origin, trust_env=False, timeout=10) as visitor,
        httpx2.Client(base_url=origin, trust_env=False, timeout=10) as employee_client,
    ):
        csrf = sign_in(manager, origin, "09123456789", password)
        headers = {"Origin": origin, "X-CSRF-Token": csrf}

        def change(method: str, path: str, data: dict[str, Any], expected: int = 200) -> Any:
            response = manager.request(method, f"/api/v1{path}", json=data, headers=headers)
            assert response.status_code == expected, (
                f"Scheduling {method} {path} failed: {response.status_code}"
            )
            return response.json() if expected != 204 else None

        line = change("POST", "/lines", {"name": "Hair", "slug": "hair"}, 201)["id"]
        service = change("POST", "/services", {"name": "Haircut", "code": "cut"}, 201)["id"]
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
        )
        employee = account["employee"]["id"]
        change(
            "PUT",
            f"/lines/{line}/services/{service}",
            {"price_amount": 1_000_000, "duration_minutes": 90, "buffer_after_minutes": 15},
        )
        change("PUT", f"/lines/{line}/employees/{employee}", {})
        change("PUT", f"/lines/{line}/employees/{employee}/services/{service}", {})
        salon_calendar = change("POST", "/scheduling/calendars", {"scope": "SALON"}, 201)["id"]
        employee_calendar = change(
            "POST", "/scheduling/calendars", {"scope": "EMPLOYEE", "employee_id": employee}, 201
        )["id"]
        zone = ZoneInfo("Asia/Tehran")
        day = datetime.now(zone).date() + timedelta(days=1)
        periods = [
            {
                "weekday": day.weekday(),
                "valid_from": str(day),
                "start_minute": 540,
                "end_minute": 1020,
            }
        ]
        for calendar in (salon_calendar, employee_calendar):
            change("PUT", f"/scheduling/calendars/{calendar}/weekly", {"periods": periods})
        params = {
            "line_id": line,
            "service_ids": service,
            "date_from": str(day),
            "date_until": str(day + timedelta(days=1)),
            "assignment": "auto",
        }

        def slots() -> list[dict[str, Any]]:
            response = visitor.get("/api/v1/scheduling/availability", params=params)
            assert response.status_code == 200
            result: list[dict[str, Any]] = response.json()["items"]
            return result

        assert len(slots()) == 26
        employee_csrf = sign_in(employee_client, origin, "09121234567", password)
        start = datetime.combine(day, datetime.min.time(), zone) + timedelta(hours=12)
        request = employee_client.post(
            f"/api/v1/scheduling/calendars/{employee_calendar}/leave-requests",
            json={
                "kind": "LEAVE",
                "reason": "Personal leave",
                "starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=1)).isoformat(),
            },
            headers={"Origin": origin, "X-CSRF-Token": employee_csrf},
        )
        assert request.status_code == 201 and request.json()["status"] == "REQUESTED"
        assert len(slots()) == 26
        change("PATCH", f"/scheduling/blocks/{request.json()['id']}", {"status": "APPROVED"})
        assert len(slots()) == 16
        change(
            "PUT",
            f"/scheduling/calendars/{salon_calendar}/overrides/{day}",
            {"mode": "CLOSED", "reason": "Holiday"},
        )
        assert slots() == []
        assert (
            visitor.get(f"/api/v1/scheduling/calendars/{employee_calendar}/blocks").status_code
            == 401
        )


def main() -> None:
    run_preview_check(
        check,
        "PASS: real HTTP schedules, public availability, service buffers, employee leave approval and salon holiday.",
    )


if __name__ == "__main__":
    main()
