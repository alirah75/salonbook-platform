"""Exercise verified test payments and refunds through real HTTP in an isolated disposable salon."""

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
        change("POST", "/payments/mock-account", {})
        held = change("POST", "/appointments", body, 201)
        key = uuid4().hex
        payload = {"appointment_id": held["id"]}
        payment = change("POST", "/payments", payload, 201, key)
        assert payment["status"] == "PENDING" and payment["is_test"]
        assert change("POST", "/payments", payload, 201, key)["id"] == payment["id"]
        paid = change("POST", f"/payments/{payment['id']}/mock-checkout", {"scenario": "success"})
        assert paid["status"] == "SUCCEEDED" and paid["appointment_status"] == "CONFIRMED"
        assert change("POST", f"/payments/{payment['id']}/verify", {}) == paid
        receipt = paid["transactions"][0]
        assert receipt["allocated"] and receipt["receipt_number"].startswith("TEST-")
        invoice = client.get(f"/api/v1/payments/invoices/{held['id']}")
        assert invoice.status_code == 200 and invoice.json()["total_amount"] == 1_000_000
        refund = change(
            "POST",
            f"/payments/transactions/{receipt['id']}/refunds",
            {"amount": 300_000, "reason": "Test adjustment"},
            201,
        )
        assert refund["status"] == "REQUESTED"
        approved = change("POST", f"/payments/refunds/{refund['id']}/approve", {})
        assert approved["status"] == "SUCCEEDED"
        assert change("POST", f"/payments/refunds/{refund['id']}/approve", {}) == approved
        credit = client.get(f"/api/v1/payments/refunds/{refund['id']}/credit-note")
        assert credit.status_code == 200 and credit.json()["number"].startswith("TEST-")
        change(
            "POST",
            f"/payments/transactions/{receipt['id']}/refunds",
            {"amount": 700_001, "reason": "Too much"},
            409,
        )
        change(
            "POST",
            f"/appointments/{held['id']}/cancel",
            {"expected_version": 2, "reason": "Cancellation"},
        )
        # Real background worker must refund the remaining balance without a callback.
        import time

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            current = client.get(f"/api/v1/payments/{payment['id']}").json()
            refunds = current["transactions"][0]["refunds"]
            if (
                sum(item["amount"] for item in refunds if item["status"] == "SUCCEEDED")
                == 1_000_000
            ):
                break
            time.sleep(0.2)
        else:
            raise AssertionError("Cancellation refund worker did not finish")


def main() -> None:
    run_preview_check(
        check,
        "PASS: real HTTP test payment, idempotent retry, verified confirmation, invoice, receipt, refund approval, credit note and background cancellation refund.",
    )


if __name__ == "__main__":
    main()
