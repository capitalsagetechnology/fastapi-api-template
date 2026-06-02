import pytest
from sqlmodel import select

from src.core.config import settings
from src.models.user import User
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
    stmt = select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL.lower())
    admin = (await db_session.exec(stmt)).one_or_none()

    assert admin is not None
    assert admin.email == settings.FIRST_SUPERUSER_EMAIL.lower()
    assert "ADMIN" in admin.roles
    assert admin.is_active is True
    assert admin.is_verified is True


async def test_authentication_flow(client, db_session):
    """Test the complete auth flow: Login -> Access Profile -> Logout -> Denied Access."""
    # Seed admin first
    await seed_first_superuser(db_session)

    # 1. Login with seeded credentials (JSON request body)
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    response = await client.post("/api/v1/auth/login", json=login_data)
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" in token_data
    token = token_data["access_token"]

    # Verify last_login updated
    stmt = select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL.lower())
    admin = (await db_session.exec(stmt)).one_or_none()
    assert admin.last_login is not None

    # Auth header
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Access profile details
    profile_response = await client.get("/api/v1/users/me", headers=headers)
    assert profile_response.status_code == 200
    profile_data = profile_response.json()
    assert profile_data["email"] == settings.FIRST_SUPERUSER_EMAIL.lower()
    assert "ADMIN" in profile_data["roles"]

    # 3. Log out
    logout_response = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout_response.status_code == 200
    assert logout_response.json() == {"detail": "Successfully logged out."}

    # 4. Attempt to access profile again (should fail because Redis session is invalidated)
    denied_response = await client.get("/api/v1/users/me", headers=headers)
    assert denied_response.status_code == 401
    assert "Session has expired" in denied_response.json()["detail"]


async def test_oauth2_token_endpoint(client, db_session):
    """Verify that the OAuth2 Form Data login /api/v1/auth/token endpoint functions correctly."""
    await seed_first_superuser(db_session)
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    # Form data request
    response = await client.post("/api/v1/auth/token", data=login_data)
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
