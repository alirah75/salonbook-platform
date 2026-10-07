"""Exercise booking lifecycle through real HTTP in an isolated disposable salon."""

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx2

from scripts.check_management_preview import run_preview_check, sign_in


def check(origin: str, password: str) -> None:
    with httpx2.Client(base_url=origin, trust_env=False, timeout=15) as client:
        csrf = sign_in(client, origin, "09123456789", password)
        headers = {"Origin": origin, "X-CSRF-Token": csrf}

        def change(
            method: str,
            path: str,
            body: dict[str, Any],
            expected: int = 200,
            key: str | None = None,
        ) -> dict[str, Any]:
            response = client.request(
                method,
                f"/api/v1{path}",
                json=body,
                headers={**headers, "Idempotency-Key": key or uuid4().hex},
            )
            assert response.status_code == expected, (
                f"Booking {method} {path} failed: {response.status_code}"
            )
            result: dict[str, Any] = response.json()
            return result

        line = change("POST", "/lines", {"name": "Hair", "slug": "hair"}, 201)["id"]
        service = change("POST", "/services", {"name": "Haircut", "code": "cut"}, 201)["id"]
        employee = change(
            "POST",
            "/users",
            {
                "phone": "09121234567",
                "password": password,
                "display_name": "Stylist",
                "kind": "employee",
            },
            201,
        )["employee"]["id"]
        offer = f"/lines/{line}/services/{service}"
        change("PUT", offer, {"price_amount": 1_000_000, "duration_minutes": 30})
        change("PUT", f"/lines/{line}/employees/{employee}", {})
        change("PUT", f"/lines/{line}/employees/{employee}/services/{service}", {})
        salon_calendar = change("POST", "/scheduling/calendars", {"scope": "SALON"}, 201)["id"]
        employee_calendar = change(
            "POST", "/scheduling/calendars", {"scope": "EMPLOYEE", "employee_id": employee}, 201
        )["id"]
        zone = ZoneInfo("Asia/Tehran")
        day = datetime.now(zone).date() + timedelta(days=2)
        start = datetime.combine(day, datetime.min.time(), zone) + timedelta(hours=9)
        for calendar in (salon_calendar, employee_calendar):
            change(
                "PUT",
                f"/scheduling/calendars/{calendar}/weekly",
                {
                    "periods": [
                        {
                            "weekday": day.weekday(),
                            "valid_from": str(day),
                            "start_minute": 540,
                            "end_minute": 1020,
                        }
                    ]
                },
            )
        body = {
            "line_id": line,
            "service_ids": [service],
            "employee_id": employee,
            "starts_at": start.isoformat(),
        }
        key = uuid4().hex
        held = change("POST", "/appointments", body, 201, key)
        assert held["status"] == "AWAITING_PAYMENT"
        assert change("POST", "/appointments", body, 201, key) == held
        denied = change("POST", f"/appointments/{held['id']}/confirm", {"expected_version": 1}, 409)
        assert denied["error"]["code"] == "payment_required"
        cancelled = change(
            "POST",
            f"/appointments/{held['id']}/cancel",
            {"expected_version": 1, "reason": "Changed plans"},
        )
        assert cancelled["status"] == "CANCELLED"
        change("PUT", offer, {"price_amount": 0, "duration_minutes": 30, "is_free": True})
        free = change("POST", "/appointments", body, 201)
        assert free["status"] == "CONFIRMED" and free["hold_expires_at"] is None
        moved = change(
            "POST",
            f"/appointments/{free['id']}/reschedule",
            {
                "expected_version": 1,
                "starts_at": (start + timedelta(hours=1)).isoformat(),
                "reason": "Later time",
            },
        )
        assert moved["version"] == 2 and moved["total_amount"] == 0
        assert client.get(f"/api/v1/appointments/{free['id']}").json() == moved
        ended = change(
            "POST",
            f"/appointments/{free['id']}/cancel",
            {"expected_version": 2, "reason": "Changed plans"},
        )
        assert ended["status"] == "CANCELLED"
        events = client.get(f"/api/v1/appointments/{free['id']}/history").json()["items"]
        assert {e["action"] for e in events} == {"confirmed_free", "rescheduled", "cancelled"}


def main() -> None:
    run_preview_check(
        check,
        "PASS: real HTTP booking, idempotent replay, payment evidence guard, free confirmation, rescheduling, cancellation and history.",
    )


if __name__ == "__main__":
    main()
