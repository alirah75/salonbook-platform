from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as UnitOfWork

from app.modules.access.models import Role, RoleAssignment
from app.modules.identity.models import User
from app.modules.operations.models import AuditLog
from tests.conftest import tenant_connection
from tests.test_authentication import (
    PASSWORD,
    AuthLab,
    login,
    public_post,
    register,
)
from tests.test_authentication import auth_lab as auth_lab_fixture

auth_lab = auth_lab_fixture

pytestmark = pytest.mark.postgres


@dataclass
class Manager:
    lab: AuthLab
    csrf: str
    user_id: str
    roles: dict[str, str]


@pytest.fixture
def manager(auth_lab: AuthLab) -> Manager:
    lab = auth_lab
    assert register(lab).status_code == 202
    with UnitOfWork(lab.database.lab.admin) as session, session.begin():
        user = session.scalar(
            select(User).where(User.tenant_id == lab.tenant, User.phone_normalized.is_not(None))
        )
        role = session.scalar(
            select(Role).where(Role.tenant_id == lab.tenant, Role.code == "salon_manager")
        )
        assert user is not None and role is not None
        session.add(
            RoleAssignment(tenant_id=lab.tenant, user_id=user.id, role_id=role.id, scope="TENANT")
        )
    response = login(lab)
    assert response.status_code == 200
    roles = {r["code"]: r["id"] for r in lab.client.get("/api/v1/roles").json()}
    return Manager(lab, response.json()["csrf_token"], response.json()["user"]["id"], roles)


def mutate(
    manager: Manager,
    method: str,
    path: str,
    data: dict[str, Any] | None = None,
    *,
    client: TestClient | None = None,
    csrf: str | None = None,
) -> Response:
    browser = client or manager.lab.client
    return browser.request(
        method,
        f"/api/v1{path}",
        json=data or {},
        headers={
            "Origin": str(browser.base_url).rstrip("/"),
            "X-CSRF-Token": csrf or manager.csrf,
        },
    )


def new_user(
    manager: Manager, phone: str = "09121234567", kind: str = "customer"
) -> dict[str, Any]:
    response = mutate(
        manager,
        "POST",
        "/users",
        {"phone": phone, "password": PASSWORD, "display_name": "New person", "kind": kind},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def sign_in(manager: Manager, browser: TestClient, phone: str = "09121234567") -> str:
    result = public_post(
        manager.lab, "login", {"phone": phone, "password": PASSWORD}, client=browser
    )
    assert result.status_code == 200, result.text
    csrf: str = result.json()["csrf_token"]
    return csrf


def assign(
    manager: Manager, user: dict[str, Any], role_id: str, *, line: UUID | None = None
) -> Response:
    return mutate(
        manager,
        "POST",
        f"/users/{user['id']}/roles",
        {
            "role_id": role_id,
            "scope": "LINE" if line else "TENANT",
            "line_id": str(line) if line else None,
        },
    )


def test_salon_users_employee_profiles_and_pagination(manager: Manager) -> None:
    lab = manager.lab
    salon = lab.client.get("/api/v1/salon")
    assert salon.json()["id"] == str(lab.tenant)
    response = mutate(manager, "PATCH", "/salon", {"name": "  سالن آزمایشی  "})
    assert response.status_code == 200 and response.json()["name"] == "سالن آزمایشی"
    assert lab.client.get("/api/v1/salon").json()["name"] == "سالن آزمایشی"
    customer = new_user(manager)
    employee = new_user(manager, "09121234568", "employee")
    assert employee["employee"]["is_active"] is True
    assert {a["code"] for a in employee["assignments"]} == {"customer", "employee"}
    assert customer["customer_id"] and customer["employee"] is None
    assert customer["phone"] == "+989121234567" and customer["phone_verified"] is False
    assert "email" not in str(customer).lower() and "password" not in str(customer).lower()
    page = lab.client.get("/api/v1/users?limit=1&offset=0").json()
    second = lab.client.get("/api/v1/users?limit=1&offset=1").json()
    assert page["has_more"] and len(page["items"]) == 1
    assert page["items"][0]["id"] != second["items"][0]["id"]
    assert employee["id"] in {
        u["id"] for u in lab.client.get("/api/v1/users?kind=employee").json()["items"]
    }
    assert {u["id"] for u in lab.client.get("/api/v1/users?kind=manager").json()["items"]} == {
        manager.user_id
    }
    edited = mutate(
        manager,
        "PUT",
        f"/users/{employee['id']}/employee",
        {"public_name": "Stylist", "is_active": False},
    )
    assert edited.status_code == 200 and edited.json()["employee"]["is_active"] is False
    assert edited.json()["is_active"] is True
    assert lab.client.get(f"/api/v1/users/{customer['id']}").json()["id"] == customer["id"]
    duplicate = mutate(
        manager,
        "POST",
        "/users",
        {"phone": "+989121234567", "password": PASSWORD, "display_name": "Replacement"},
    )
    assert duplicate.status_code == 409
    assert lab.client.get(f"/api/v1/users/{customer['id']}").json()["display_name"] == "New person"
    with lab.database.lab.admin.connect() as connection:
        records = connection.execute(
            select(AuditLog.action, AuditLog.event_data).where(AuditLog.tenant_id == lab.tenant)
        ).all()
        assert {a for a, _ in records} >= {"salon.updated", "user.created", "employee.updated"}
        assert PASSWORD not in str(records) and customer["phone"] not in str(records)


@pytest.mark.parametrize("path", ["/users", "/roles", "/permissions"])
def test_customers_cannot_read_management(auth_lab: AuthLab, path: str) -> None:
    lab = auth_lab
    assert lab.client.get(f"/api/v1{path}").status_code == 401
    register(lab)
    response = login(lab)
    assert response.status_code == 200
    assert lab.client.get(f"/api/v1{path}").status_code == 403
    assert lab.client.get("/api/v1/salon").status_code == 200
    csrf = response.json()["csrf_token"]
    changed = lab.client.patch(
        "/api/v1/profile",
        json={"display_name": "  New name  "},
        headers={"Origin": lab.origin, "X-CSRF-Token": csrf},
    )
    assert changed.status_code == 200 and changed.json()["display_name"] == "New name"
    assert lab.client.get("/api/v1/auth/me").json()["user"]["display_name"] == "New name"


def test_manager_cannot_read_or_modify_another_salon(manager: Manager) -> None:
    lab = manager.lab
    with lab.database.lab.admin.connect() as connection:
        other_user = connection.scalar(select(User.id).where(User.tenant_id == lab.other_tenant))
        other_role = connection.scalar(select(Role.id).where(Role.tenant_id == lab.other_tenant))
    user = new_user(manager)
    assert lab.client.get(f"/api/v1/users/{other_user}").status_code == 404
    assert mutate(manager, "PATCH", f"/users/{other_user}", {"is_active": False}).status_code == 404
    assert (
        mutate(
            manager, "PUT", f"/users/{other_user}/employee", {"public_name": "Intruder"}
        ).status_code
        == 404
    )
    assert (
        mutate(
            manager, "PUT", f"/roles/{other_role}", {"name": "Intruder", "permissions": []}
        ).status_code
        == 404
    )
    assert mutate(manager, "DELETE", f"/roles/{other_role}").status_code == 404
    assert assign(manager, user, str(other_role)).status_code == 404
    assert (
        assign(manager, user, manager.roles["line_manager"], line=lab.other_line).status_code == 404
    )
    assert other_user not in {
        UUID(u["id"]) for u in lab.client.get("/api/v1/users").json()["items"]
    }
    assert (
        lab.client.get("/api/v1/users", headers={"X-Tenant-ID": str(lab.other_tenant)}).json()
        == lab.client.get("/api/v1/users").json()
    )
    with tenant_connection(lab.database, lab.tenant) as connection:
        assert (
            connection.execute(
                text("UPDATE salons SET name = 'intruder' WHERE id = :id"), {"id": lab.other_tenant}
            ).rowcount
            == 0
        )
    with pytest.raises(DBAPIError), tenant_connection(lab.database, lab.tenant) as connection:
        connection.execute(
            text("UPDATE salons SET status = 'SUSPENDED' WHERE id = :id"), {"id": lab.tenant}
        )


def test_deactivation_and_reactivation_never_restore_old_sessions(manager: Manager) -> None:
    user = new_user(manager)
    with TestClient(manager.lab.app, base_url=manager.lab.origin) as browser:
        sign_in(manager, browser)
        assert (
            mutate(manager, "PATCH", f"/users/{user['id']}", {"is_active": False}).status_code
            == 200
        )
        assert browser.get("/api/v1/auth/me").status_code == 401
        assert (
            public_post(
                manager.lab, "login", {"phone": user["phone"], "password": PASSWORD}, client=browser
            ).status_code
            == 401
        )
        assert (
            mutate(manager, "PATCH", f"/users/{user['id']}", {"is_active": True}).status_code == 200
        )
        assert browser.get("/api/v1/auth/me").status_code == 401
        sign_in(manager, browser)
        assert browser.get("/api/v1/auth/me").status_code == 200


def test_last_manager_is_retained_and_failed_write_rolls_back(manager: Manager) -> None:
    user = manager.lab.client.get(f"/api/v1/users/{manager.user_id}").json()
    assignment = next(a for a in user["assignments"] if a["code"] == "salon_manager")
    for response in (
        mutate(manager, "PATCH", f"/users/{manager.user_id}", {"is_active": False}),
        mutate(manager, "DELETE", f"/role-assignments/{assignment['id']}"),
    ):
        assert response.status_code == 409 and response.json()["error"]["code"] == "last_manager"
    assert manager.lab.client.get("/api/v1/auth/me").status_code == 200
    assert manager.lab.client.get(f"/api/v1/users/{manager.user_id}").json()["is_active"] is True


def test_concurrent_managers_cannot_remove_the_last_manager(manager: Manager) -> None:
    user = new_user(manager)
    assert assign(manager, user, manager.roles["salon_manager"]).status_code == 201
    with TestClient(manager.lab.app, base_url=manager.lab.origin) as second:
        csrf = sign_in(manager, second)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_result = pool.submit(
                mutate, manager, "PATCH", f"/users/{manager.user_id}", {"is_active": False}
            )
            second_result = pool.submit(
                mutate,
                manager,
                "PATCH",
                f"/users/{user['id']}",
                {"is_active": False},
                client=second,
                csrf=csrf,
            )
            responses = [first_result.result(), second_result.result()]
        assert sorted(response.status_code for response in responses) == [200, 409]
        with manager.lab.database.lab.admin.connect() as connection:
            statuses = (
                connection.execute(
                    select(User.is_active).where(
                        User.id.in_([UUID(manager.user_id), UUID(user["id"])])
                    )
                )
                .scalars()
                .all()
            )
            assert sum(statuses) == 1


def test_role_changes_invalidate_sessions_and_soft_delete_is_audited(manager: Manager) -> None:
    user = new_user(manager)
    response = mutate(
        manager,
        "POST",
        "/roles",
        {"code": "reception", "name": "Reception", "permissions": ["users.read"]},
    )
    assert response.status_code == 201
    role = response.json()
    with TestClient(manager.lab.app, base_url=manager.lab.origin) as browser:
        sign_in(manager, browser)
        granted = assign(manager, user, role["id"])
        assert granted.status_code == 201
        assert browser.get("/api/v1/auth/me").status_code == 401
        sign_in(manager, browser)
        assert browser.get("/api/v1/users").status_code == 200
        updated = mutate(
            manager, "PUT", f"/roles/{role['id']}", {"name": "Reception", "permissions": []}
        )
        assert updated.status_code == 200
        assert browser.get("/api/v1/users").status_code == 401
        sign_in(manager, browser)
        assert browser.get("/api/v1/users").status_code == 403
        assert mutate(manager, "DELETE", f"/roles/{role['id']}").status_code == 204
        assert browser.get("/api/v1/auth/me").status_code == 401
    with manager.lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(select(Role.deleted_at).where(Role.id == UUID(role["id"])))
            is not None
        )
        assert (
            connection.scalar(
                select(RoleAssignment.revoked_at).where(
                    RoleAssignment.id == UUID(granted.json()["id"])
                )
            )
            is not None
        )
        actions = set(
            connection.scalars(
                select(AuditLog.action).where(AuditLog.tenant_id == manager.lab.tenant)
            )
        )
        assert actions >= {"role.created", "role.assigned", "role.updated", "role.deleted"}
        changed = connection.scalar(
            select(AuditLog.event_data).where(
                AuditLog.entity_id == UUID(role["id"]), AuditLog.action == "role.updated"
            )
        )
        assert changed is not None and changed["permissions"] == {
            "before": ["users.read"],
            "after": [],
        }


def test_role_revocation_and_employee_conversion(manager: Manager) -> None:
    user = new_user(manager)
    assert assign(manager, user, manager.roles["employee"]).status_code == 409
    assert (
        mutate(
            manager, "PUT", f"/users/{user['id']}/employee", {"public_name": "New employee"}
        ).status_code
        == 200
    )
    assignment = assign(manager, user, manager.roles["employee"])
    assert assignment.status_code == 201
    assert assign(manager, user, manager.roles["employee"]).status_code == 409
    with TestClient(manager.lab.app, base_url=manager.lab.origin) as browser:
        sign_in(manager, browser)
        assert (
            mutate(manager, "DELETE", f"/role-assignments/{assignment.json()['id']}").status_code
            == 204
        )
        assert browser.get("/api/v1/auth/me").status_code == 401
        assert (
            mutate(manager, "DELETE", f"/role-assignments/{assignment.json()['id']}").status_code
            == 404
        )


def test_delegation_ceiling_blocks_escalation_and_higher_privilege_account_changes(
    manager: Manager,
) -> None:
    user = new_user(manager)
    role = mutate(
        manager,
        "POST",
        "/roles",
        {
            "code": "limited_admin",
            "name": "Limited admin",
            "permissions": ["roles.read", "roles.manage", "users.read", "users.manage"],
        },
    ).json()
    assert assign(manager, user, role["id"]).status_code == 201
    with TestClient(manager.lab.app, base_url=manager.lab.origin) as browser:
        csrf = sign_in(manager, browser)
        assert (
            mutate(
                manager,
                "POST",
                "/roles",
                {"code": "escalation", "name": "Bad", "permissions": ["finance.read"]},
                client=browser,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                manager,
                "PUT",
                f"/roles/{role['id']}",
                {"name": "Bad", "permissions": ["finance.read"]},
                client=browser,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                manager,
                "POST",
                f"/users/{user['id']}/roles",
                {"role_id": manager.roles["salon_manager"]},
                client=browser,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                manager,
                "PATCH",
                f"/users/{manager.user_id}",
                {"is_active": False},
                client=browser,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                manager,
                "POST",
                "/roles",
                {"code": "allowed", "name": "Allowed", "permissions": ["users.read"]},
                client=browser,
                csrf=csrf,
            ).status_code
            == 201
        )


def test_line_manager_cannot_manage_shared_accounts_or_global_roles(manager: Manager) -> None:
    user = new_user(manager, kind="employee")
    assert (
        assign(manager, user, manager.roles["line_manager"], line=manager.lab.line).status_code
        == 201
    )
    with TestClient(manager.lab.app, base_url=manager.lab.origin) as browser:
        csrf = sign_in(manager, browser)
        for path in ("/users", "/roles", "/permissions"):
            assert browser.get(f"/api/v1{path}").status_code == 403
        assert (
            mutate(
                manager,
                "PATCH",
                f"/users/{user['id']}",
                {"is_active": False},
                client=browser,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                manager,
                "PUT",
                f"/users/{user['id']}/employee",
                {"public_name": "Unauthorized global edit"},
                client=browser,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                manager, "PATCH", "/salon", {"name": "Unauthorized"}, client=browser, csrf=csrf
            ).status_code
            == 403
        )


def test_line_delegation_cannot_escape_its_scope(manager: Manager) -> None:
    delegate = new_user(manager)
    target = new_user(manager, "09121234568")
    role = mutate(
        manager,
        "POST",
        "/roles",
        {
            "code": "line_delegate",
            "name": "Line delegate",
            "permissions": ["roles.manage", "catalog.manage"],
        },
    ).json()
    limited = mutate(
        manager,
        "POST",
        "/roles",
        {"code": "line_catalog", "name": "Catalog", "permissions": ["catalog.manage"]},
    ).json()
    assert assign(manager, delegate, role["id"], line=manager.lab.line).status_code == 201
    with TestClient(manager.lab.app, base_url=manager.lab.origin) as browser:
        csrf = sign_in(manager, browser)
        body = {"role_id": limited["id"], "scope": "LINE", "line_id": str(manager.lab.line)}
        assert (
            mutate(
                manager, "POST", f"/users/{target['id']}/roles", body, client=browser, csrf=csrf
            ).status_code
            == 201
        )
        assert (
            mutate(
                manager,
                "POST",
                f"/users/{target['id']}/roles",
                {"role_id": limited["id"]},
                client=browser,
                csrf=csrf,
            ).status_code
            == 403
        )
        assert (
            mutate(
                manager,
                "POST",
                f"/users/{target['id']}/roles",
                {**body, "line_id": str(uuid4())},
                client=browser,
                csrf=csrf,
            ).status_code
            == 403
        )


@pytest.mark.parametrize(
    "method,path,payload",
    [
        (
            "POST",
            "/users",
            {
                "phone": "09121234567",
                "display_name": "User",
                "password": PASSWORD,
                "email": "no@example.test",
            },
        ),
        (
            "POST",
            "/users",
            {
                "phone": "09121234567",
                "display_name": "User",
                "password": PASSWORD,
                "role": "salon_manager",
            },
        ),
        ("PATCH", "/salon", {"name": "Salon", "status": "SUSPENDED"}),
        ("PATCH", "/profile", {"display_name": "User", "phone_verified": True}),
        ("PATCH", "/profile", {"display_name": " "}),
        ("POST", "/roles", {"code": "super_admin", "name": "Super", "permissions": []}),
        (
            "POST",
            "/roles",
            {"code": "unknown", "name": "Unknown", "permissions": ["invented.permission"]},
        ),
        (
            "POST",
            "/roles",
            {
                "code": "duplicate",
                "name": "Duplicate",
                "permissions": ["profile.read", "profile.read"],
            },
        ),
    ],
)
def test_strict_management_inputs(
    manager: Manager, method: str, path: str, payload: dict[str, Any]
) -> None:
    response = mutate(manager, method, path, payload)
    assert response.status_code == 422 and PASSWORD not in response.text


def test_system_roles_scope_validation_and_csrf(manager: Manager) -> None:
    for role in manager.roles.values():
        assert (
            mutate(
                manager, "PUT", f"/roles/{role}", {"name": "Changed", "permissions": []}
            ).status_code
            == 409
        )
        assert mutate(manager, "DELETE", f"/roles/{role}").status_code == 409
    user = new_user(manager)
    assert assign(manager, user, manager.roles["line_manager"]).status_code == 422
    assert (
        assign(manager, user, manager.roles["salon_manager"], line=manager.lab.line).status_code
        == 422
    )
    for path in ("/users?limit=101", "/users?offset=-1", "/users?kind=platform", "/roles?limit=0"):
        assert manager.lab.client.get(f"/api/v1{path}").status_code == 422
    assert mutate(manager, "PATCH", f"/users/{user['id']}", {}).status_code == 422
    assert mutate(manager, "PATCH", f"/users/{user['id']}", {"is_active": None}).status_code == 422
    assert mutate(manager, "PATCH", "/salon", {"name": "Forgery"}, csrf="f" * 64).status_code == 403
    assert (
        manager.lab.client.patch(
            "/api/v1/salon", json={"name": "No origin"}, headers={"X-CSRF-Token": manager.csrf}
        ).status_code
        == 403
    )
