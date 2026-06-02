import pytest
from sqlmodel import select

from src.core.config import settings
from src.models.user import Invitation, User
from src.services.auth import seed_first_superuser

pytestmark = pytest.mark.asyncio


async def test_health_check(client):
    """Verify that the health check endpoint returns 200 OK."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "project": settings.PROJECT_NAME}


async def test_admin_seeding(db_session):
    """Test that the seed function successfully creates the initial superuser."""
    await seed_first_superuser(db_session)

    # Query seeded admin
    stmt = select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)
    result = await db_session.execute(stmt)
    admin = result.scalar_one_or_none()

    assert admin is not None
    assert admin.email == settings.FIRST_SUPERUSER_EMAIL
    assert "ADMIN" in admin.roles
    assert admin.is_active is True


async def test_authentication_flow(client, db_session):
    """Test the complete auth flow: Login -> Access Profile -> Logout -> Denied Access."""
    # Seed admin first
    await seed_first_superuser(db_session)

    # 1. Login with seeded credentials
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    response = await client.post("/api/v1/auth/login", data=login_data)
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" in token_data
    token = token_data["access_token"]

    # Auth header
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Access profile details
    profile_response = await client.get("/api/v1/users/me", headers=headers)
    assert profile_response.status_code == 200
    profile_data = profile_response.json()
    assert profile_data["email"] == settings.FIRST_SUPERUSER_EMAIL
    assert "ADMIN" in profile_data["roles"]

    # 3. Log out
    logout_response = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout_response.status_code == 200
    assert logout_response.json() == {"detail": "Successfully logged out."}

    # 4. Attempt to access profile again (should fail because Redis session is invalidated)
    denied_response = await client.get("/api/v1/users/me", headers=headers)
    assert denied_response.status_code == 401
    assert "Session has expired" in denied_response.json()["detail"]


async def test_user_invitation_by_admin(client, db_session):
    """Verify that ADMIN can invite users, triggers Celery email, and non-admins are forbidden."""
    await seed_first_superuser(db_session)

    # Login admin
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_res = await client.post("/api/v1/auth/login", data=login_data)
    admin_token = login_res.json()["access_token"]

    # 1. Invite request (admin)
    invite_payload = {"email": "agent@example.com", "roles": ["AGENT", "CONTROL"]}
    headers = {"Authorization": f"Bearer {admin_token}"}

    invite_res = await client.post(
        "/api/v1/auth/invite", json=invite_payload, headers=headers
    )
    assert invite_res.status_code == 200
    invite_data = invite_res.json()
    assert invite_data["email"] == "agent@example.com"
    assert invite_data["roles"] == ["AGENT", "CONTROL"]

    # Confirm celery task was called
    client.invite_mock_task.assert_called_once()

    # 2. Invite request (unauthenticated)
    no_auth_res = await client.post("/api/v1/auth/invite", json=invite_payload)
    assert no_auth_res.status_code == 401


async def test_registration_via_invitation(client, db_session):
    """Test registration workflow: Admin invites -> User accepts invite with S3 profile image upload."""
    await seed_first_superuser(db_session)

    # 1. Admin login & invite
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_res = await client.post("/api/v1/auth/login", data=login_data)
    admin_token = login_res.json()["access_token"]

    invite_payload = {"email": "agent@example.com", "roles": ["AGENT"]}
    invite_res = await client.post(
        "/api/v1/auth/invite",
        json=invite_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert invite_res.status_code == 200

    # Query invitation token from SQLite test DB
    stmt = select(Invitation).where(Invitation.email == "agent@example.com")
    res = await db_session.execute(stmt)
    invitation = res.scalar_one()
    invite_token = invitation.token

    # 2. User registers using invite token (includes profile image upload mock)
    # Prepare multipart form fields
    form_data = {"token": invite_token, "password": "SecureAgentPassword123!"}
    file_payload = {
        "profile_image": ("avatar.png", b"fake-png-binary-content", "image/png")
    }

    register_res = await client.post(
        "/api/v1/auth/register-invite", data=form_data, files=file_payload
    )
    assert register_res.status_code == 200
    user_data = register_res.json()
    assert user_data["email"] == "agent@example.com"
    assert user_data["roles"] == ["AGENT"]
    assert "avatar.png" in user_data["profile_image"]

    # Verify welcome email Celery task triggered
    client.welcome_mock_task.assert_called_once()

    # Verify invitation token is consumed
    stmt = select(Invitation).where(Invitation.token == invite_token)
    res = await db_session.execute(stmt)
    invitation = res.scalar_one()
    assert invitation.accepted_at is not None


async def test_central_asset_upload(client, db_session):
    """Verify standard file uploads to S3 storage."""
    await seed_first_superuser(db_session)
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_res = await client.post("/api/v1/auth/login", data=login_data)
    token = login_res.json()["access_token"]

    file_payload = {"file": ("document.pdf", b"fake-pdf-content", "application/pdf")}

    upload_res = await client.post(
        "/api/v1/assets/upload",
        files=file_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upload_res.status_code == 201
    upload_data = upload_res.json()
    assert upload_data["filename"] == "document.pdf"
    assert "document.pdf" in upload_data["url"]


async def test_ip_whitelisting(client):
    """Test access whitelisting by changing mock client IPs via X-Forwarded-For headers."""
    # 1. Allowed IP request
    allowed_res = await client.get(
        "/api/v1/assets/secure-config", headers={"X-Forwarded-For": "127.0.0.1"}
    )
    assert allowed_res.status_code == 200
    assert allowed_res.json()["whitelisted_ip_checked"] == "Passed"

    # 2. Blocked IP request
    blocked_res = await client.get(
        "/api/v1/assets/secure-config", headers={"X-Forwarded-For": "198.51.100.1"}
    )
    assert blocked_res.status_code == 403
    assert "Access Denied" in blocked_res.json()["detail"]


async def test_scoped_api_key_access(client, db_session):
    """Test creating scoped api keys and making requests to scoped-resource endpoints."""
    await seed_first_superuser(db_session)
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_res = await client.post("/api/v1/auth/login", data=login_data)
    token = login_res.json()["access_token"]

    # 1. Create API key with scope assets:audit
    key_payload = {
        "name": "Audit Service Key",
        "scopes": ["assets:audit"],
        "expires_in_days": 10,
    }
    key_res = await client.post(
        "/api/v1/users/api-keys",
        json=key_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert key_res.status_code == 201
    key_data = key_res.json()
    raw_key = key_data["raw_key"]
    assert raw_key is not None
    assert key_data["scopes"] == ["assets:audit"]

    # 2. Request scoped endpoint with correct key
    audit_res = await client.get("/api/v1/assets/audit", headers={"X-API-Key": raw_key})
    assert audit_res.status_code == 200
    assert "Scope verification successful" in audit_res.json()["message"]

    # 3. Request scoped endpoint with incorrect key (should fail 401)
    wrong_key_res = await client.get(
        "/api/v1/assets/audit", headers={"X-API-Key": "ak_invalidkeyhex"}
    )
    assert wrong_key_res.status_code == 401

    # 4. Request scoped endpoint with valid key lacking scope (lacks scope)
    # Create key lacking audit scope
    no_scope_payload = {"name": "Read Only Key", "scopes": ["users:read"]}
    no_scope_res = await client.post(
        "/api/v1/users/api-keys",
        json=no_scope_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    no_scope_raw_key = no_scope_res.json()["raw_key"]

    insufficient_res = await client.get(
        "/api/v1/assets/audit", headers={"X-API-Key": no_scope_raw_key}
    )
    assert insufficient_res.status_code == 403
    assert "lacks required scopes" in insufficient_res.json()["detail"]
