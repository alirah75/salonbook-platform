from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.modules.identity.models import Session, User
from app.modules.identity.phone import normalize_mobile
from app.modules.identity.schemas import RegisterInput
from scripts.bind_login_mobile import bind_mobile
from tests.conftest import add, tenant_connection
from tests.test_api_foundation import captured_logs
from tests.test_authentication import (
    NEW_PASSWORD,
    PASSWORD,
    PHONE,
    AuthLab,
    login,
    private_post,
    public_post,
    register,
)
from tests.test_authentication import (
    auth_lab as auth_lab,
)


@pytest.mark.parametrize(
    "value",
    [
        "09123456789",
        "+989123456789",
        "00989123456789",
        "۰۹۱۲۳۴۵۶۷۸۹",
        "٠٩١٢٣٤٥٦٧٨٩",
        "+۹۸۹۱۲۳۴۵۶۷۸۹",
        "0912 345 6789",
        "(0912) 345-6789",
        " 09123456789 ",
    ],
)
def test_mobile_formats_have_one_canonical_identifier(value: str) -> None:
    assert normalize_mobile(value) == PHONE


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0912",
        "091234567890",
        "+12025550123",
        "02112345678",
        "email@example.com",
        "0912ABC6789",
        "tel:+989123456789",
        "09123456789;ext=2",
        "0912\n3456789",
        "۰۰۰۰۰۰۰۰۰۰۰۰",
    ],
)
def test_only_valid_iranian_mobile_numbers_are_accepted(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_mobile(value)


@pytest.mark.postgres
def test_mobile_registration_has_no_email_or_notification_side_effect(auth_lab: AuthLab) -> None:
    lab = auth_lab
    assert register(lab, phone="۰۹۱۲۳۴۵۶۷۸۹").status_code == 202
    signed_in = login(lab)
    assert signed_in.status_code == 200
    user = signed_in.json()["user"]
    assert user["phone"] == PHONE and user["phone_verified"] is False
    assert "email" not in user and "email_verified" not in user
    with lab.database.lab.admin.connect() as connection:
        row = connection.execute(
            select(User.email_normalized, User.phone_verified_at).where(User.id == UUID(user["id"]))
        ).one()
        assert row.email_normalized is None and row.phone_verified_at is None
        assert (
            connection.scalar(
                text("SELECT count(*) FROM background_jobs WHERE tenant_id = :tenant"),
                {"tenant": lab.tenant},
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM outbox_events WHERE tenant_id = :tenant"),
                {"tenant": lab.tenant},
            )
            == 0
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    "extra",
    [
        {"email": "person@example.com"},
        {"phone_verified": True},
        {"phone_verified_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_signup_rejects_email_and_client_verification_claims(
    auth_lab: AuthLab, extra: dict[str, object]
) -> None:
    payload = {"phone": PHONE, "password": PASSWORD, "display_name": "Test", **extra}
    assert public_post(auth_lab, "register", payload).status_code == 422


@pytest.mark.postgres
def test_email_login_and_retired_email_routes_are_unavailable(auth_lab: AuthLab) -> None:
    lab = auth_lab
    spec = lab.client.get("/api/v1/openapi.json").json()
    register_schema = spec["components"]["schemas"]["RegisterInput"]
    assert set(register_schema["required"]) == {"phone", "password", "display_name"}
    assert "email" not in register_schema["properties"]
    assert (
        public_post(lab, "login", {"email": "person@example.com", "password": PASSWORD}).status_code
        == 422
    )
    for path in ("forgot-password", "reset-password", "verify-email", "resend-verification"):
        assert f"/api/v1/auth/{path}" not in spec["paths"]
        assert lab.client.post(f"/api/v1/auth/{path}", json={}).status_code == 404


@pytest.mark.postgres
def test_alternate_formats_cannot_duplicate_or_overwrite_credentials(auth_lab: AuthLab) -> None:
    lab = auth_lab
    first = register(lab, phone="09123456789")
    second = public_post(
        lab,
        "register",
        {"phone": "+989123456789", "password": NEW_PASSWORD, "display_name": "Attacker"},
    )
    assert first.status_code == second.status_code == 202 and first.json() == second.json()
    assert login(lab).status_code == 200
    assert login(lab, password=NEW_PASSWORD).status_code == 401
    with lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM users WHERE tenant_id = :tenant AND phone_normalized = :phone"
                ),
                {"tenant": lab.tenant, "phone": PHONE},
            )
            == 1
        )


@pytest.mark.postgres
def test_equivalent_formats_share_login_throttle(auth_lab: AuthLab) -> None:
    lab = auth_lab
    register(lab)
    formats = (PHONE, "09123456789", "۰۹۱۲۳۴۵۶۷۸۹", "00989123456789")
    for index in range(lab.runtime.settings.auth_attempt_limit):
        assert (
            public_post(
                lab, "login", {"phone": formats[index % len(formats)], "password": "incorrect"}
            ).status_code
            == 401
        )
    assert (
        public_post(lab, "login", {"phone": "0912 345 6789", "password": PASSWORD}).status_code
        == 429
    )


@pytest.mark.postgres
def test_concurrent_registration_creates_one_account(auth_lab: AuthLab) -> None:
    lab = auth_lab
    inputs = [
        RegisterInput(phone=phone, password=PASSWORD, display_name="Concurrent")
        for phone in (PHONE, "09123456789")
    ]
    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(lambda payload: lab.auth.accounts.register(lab.context, payload), inputs))
    with lab.database.lab.admin.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM users WHERE tenant_id = :tenant AND phone_normalized = :phone"
                ),
                {"tenant": lab.tenant, "phone": PHONE},
            )
            == 1
        )


@pytest.mark.postgres
def test_password_change_revokes_other_sessions_and_preserves_phone(auth_lab: AuthLab) -> None:
    lab = auth_lab
    register(lab)
    response = login(lab)
    old = lab.client.cookies.get("__Host-salonbook-session")
    assert (
        private_post(
            lab,
            "change-password",
            response.json()["csrf_token"],
            {"current_password": "incorrect", "new_password": NEW_PASSWORD},
        ).status_code
        == 400
    )
    assert (
        private_post(
            lab,
            "change-password",
            response.json()["csrf_token"],
            {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        ).status_code
        == 204
    )
    assert (
        lab.client.get(
            "/api/v1/auth/me", headers={"Cookie": f"__Host-salonbook-session={old}"}
        ).status_code
        == 401
    )
    assert login(lab).status_code == 401
    assert login(lab, password=NEW_PASSWORD).json()["user"]["phone"] == PHONE


@pytest.mark.postgres
def test_mobile_and_credentials_are_absent_from_logs(auth_lab: AuthLab) -> None:
    lab = auth_lab
    with captured_logs() as logs:
        register(lab)
        response = login(lab)
        raw = lab.client.cookies.get("__Host-salonbook-session")
        assert raw and raw not in response.text
    assert (
        raw not in logs.getvalue()
        and PASSWORD not in logs.getvalue()
        and PHONE not in logs.getvalue()
    )


@pytest.mark.postgres
def test_database_rejects_duplicate_and_noncanonical_mobile(auth_lab: AuthLab) -> None:
    lab = auth_lab
    register(lab)
    for value in (PHONE, "09123456789", "+12025550123"):
        with (
            pytest.raises(IntegrityError),
            tenant_connection(lab.database, lab.tenant) as connection,
        ):
            add(
                connection,
                "users",
                tenant_id=lab.tenant,
                phone_normalized=value,
                password_hash="test",
                display_name="Invalid",
            )
    with tenant_connection(lab.database, lab.other_tenant) as connection:
        add(
            connection,
            "users",
            tenant_id=lab.other_tenant,
            phone_normalized=PHONE,
            password_hash="test",
            display_name="Other salon",
        )
    with lab.database.lab.admin.connect() as connection:
        constraints = set(
            connection.execute(
                text("SELECT conname FROM pg_constraint WHERE conrelid = 'users'::regclass")
            ).scalars()
        )
        assert {
            "ck_users_phone_normalized",
            "ck_users_phone_verification",
            "uq_users_tenant_id_phone_normalized",
        } <= constraints


@pytest.mark.postgres
def test_legacy_contact_phone_never_grants_login_and_binding_is_scoped(auth_lab: AuthLab) -> None:
    lab = auth_lab
    with tenant_connection(lab.database, lab.tenant) as connection:
        identifier = add(
            connection,
            "users",
            tenant_id=lab.tenant,
            phone="09123456789",
            email_normalized="legacy@example.test",
            password_hash=lab.auth.security.hash_password(PASSWORD),
            display_name="Legacy",
        )
    assert login(lab).status_code == 401
    with pytest.raises(ValueError):
        bind_mobile(lab.runtime.database, lab.other_tenant, identifier, PHONE)
    bind_mobile(lab.runtime.database, lab.tenant, identifier, "۰۹۱۲۳۴۵۶۷۸۹")
    signed_in = login(lab)
    assert signed_in.status_code == 200 and signed_in.json()["user"]["phone_verified"] is False
    with lab.database.lab.admin.begin() as connection:
        connection.execute(
            update(User).where(User.id == identifier).values(phone_verified_at=datetime.now(UTC))
        )
    bind_mobile(lab.runtime.database, lab.tenant, identifier, "09351234567")
    assert lab.client.get("/api/v1/auth/me").status_code == 401
    with lab.database.lab.admin.connect() as connection:
        row = connection.execute(
            select(User.phone_normalized, User.phone_verified_at, User.email_normalized).where(
                User.id == identifier
            )
        ).one()
        assert row.phone_normalized == "+989351234567" and row.phone_verified_at is None
        assert row.email_normalized == "legacy@example.test"
        assert (
            connection.scalar(select(Session.revoked_at).where(Session.user_id == identifier))
            is not None
        )
