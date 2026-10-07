"""Public discovery stays tenant scoped; personal views never become manager lists."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.modules.catalog.models import Line, LineService, Service
from tests.test_appointments import create, free
from tests.test_authentication import auth_lab as auth_lab
from tests.test_catalog_workforce import Catalog
from tests.test_catalog_workforce import catalog as catalog
from tests.test_payments import finish, pay, started
from tests.test_payments import mock_enabled as mock_enabled
from tests.test_scheduling import Schedule
from tests.test_scheduling import schedule as schedule
from tests.test_tenant_management import manager as manager
from tests.test_tenant_management import new_user, sign_in

pytestmark = pytest.mark.postgres


def test_public_service_discovery_and_safe_settings(catalog: Catalog) -> None:
    c, lab = catalog, catalog.manager.lab
    with TestClient(lab.client.app, base_url=str(lab.client.base_url)) as browser:
        result = browser.get("/api/v1/catalog/services", params={"limit": 100})
        assert result.status_code == 200
        assert c.service in {item["id"] for item in result.json()["items"]}
        assert browser.get("/api/v1/catalog/services", params={"limit": 101}).status_code == 422
        lines = browser.get(f"/api/v1/catalog/services/{c.service}/lines").json()
        assert lines["items"][0]["line_id"] == c.line
        assert lines["items"][0]["price_amount"] == 1_000_000
        config = browser.get("/api/v1/catalog/booking-settings").json()
        assert set(config) == {"timezone", "today", "booking_horizon_days", "cancel_before_minutes"}
        assert config["timezone"] == "Asia/Tehran"
        foreign = browser.get(f"{lab.other_origin}/api/v1/catalog/services").json()
        assert c.service not in {item["id"] for item in foreign["items"]}
        assert (
            browser.get(f"{lab.other_origin}/api/v1/catalog/services/{c.service}/lines").status_code
            == 404
        )
        # Each inactive link in the public path closes discovery independently.
        for model, identifier in ((Line, c.line), (Service, c.service)):
            with lab.database.lab.admin.begin() as connection:
                connection.execute(
                    update(model).where(model.id == UUID(identifier)).values(is_active=False)
                )
            assert c.service not in {
                item["id"] for item in browser.get("/api/v1/catalog/services").json()["items"]
            }
            with lab.database.lab.admin.begin() as connection:
                connection.execute(
                    update(model).where(model.id == UUID(identifier)).values(is_active=True)
                )
        with lab.database.lab.admin.begin() as connection:
            connection.execute(
                update(LineService)
                .where(LineService.line_id == UUID(c.line))
                .values(is_active=False)
            )
        assert c.service not in {
            item["id"] for item in browser.get("/api/v1/catalog/services").json()["items"]
        }
        assert browser.get(f"/api/v1/catalog/services/{c.service}/lines").json()["items"] == []


def test_mine_remains_personal_for_manager_and_customer(schedule: Schedule) -> None:
    s, m = schedule, schedule.catalog.manager
    free(s)
    own = create(s).json()["id"]
    new_user(m, "09121111111")
    with TestClient(m.lab.client.app, base_url=str(m.lab.client.base_url)) as customer:
        csrf = sign_in(m, customer, "09121111111")
        other = create(s, 600, client=customer, csrf=csrf).json()["id"]
        assert {
            r["id"] for r in customer.get("/api/v1/appointments?mine=true").json()["items"]
        } == {other}
    assert {r["id"] for r in m.lab.client.get("/api/v1/appointments").json()["items"]} == {
        own,
        other,
    }
    assert {
        r["id"] for r in m.lab.client.get("/api/v1/appointments?mine=true").json()["items"]
    } == {own}


def test_payment_latest_first_keeps_recovery_on_current_attempt(
    schedule: Schedule, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SALONBOOK_MOCK_PAYMENTS_ENABLED", "true")
    s = schedule
    appointment, first = started(s)
    finish(s, first, "failure")
    second = pay(s, body={"appointment_id": appointment["id"]}).json()
    browser = s.catalog.manager.lab.client
    path = f"/api/v1/payments?appointment_id={appointment['id']}&limit=1"
    assert browser.get(path).json()[0]["id"] == first["id"]
    assert browser.get(path + "&newest_first=true").json()[0]["id"] == second["id"]
