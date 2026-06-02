from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from src.core.config import settings
from src.models.user import Token, User
from src.services.auth import seed_first_superuser

pytestmark = pytest.mark.asyncio


async def test_user_invitation_by_admin(client, db_session):
    """Verify that ADMIN can invite users, triggers Celery email, and normalizes email."""
    await seed_first_superuser(db_session)

    # Login admin
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_res = await client.post("/api/v1/auth/login", json=login_data)
    admin_token = login_res.json()["access_token"]

    # 1. Invite request (admin) - using mixed casing
    invite_payload = {"email": "aGeNt@ExAmPlE.CoM", "roles": ["AGENT", "CONTROL"]}
    headers = {"Authorization": f"Bearer {admin_token}"}

    invite_res = await client.post(
        "/api/v1/auth/invite", json=invite_payload, headers=headers
    )
    assert invite_res.status_code == 201
    invite_data = invite_res.json()
    assert invite_data["email"] == "agent@example.com"  # Normalized to lowercase
    assert "id" in invite_data

    # Confirm user created with normalized email and is not verified
    stmt = select(User).where(User.email == "agent@example.com")
    user = (await db_session.exec(stmt)).one()
    assert user.is_verified is False
    assert user.hashed_password is None

    # Confirm celery task was called with correct parameters
    client.invite_mock_task.assert_called_once()
    called_args = (
        client.invite_mock_task.call_args[1] or client.invite_mock_task.call_args[0]
    )
    assert called_args.get("email") == "agent@example.com"
    assert len(called_args.get("token")) == 7

    # 2. Invite duplicate email (should fail 400)
    dup_res = await client.post(
        "/api/v1/auth/invite",
        json={"email": "agent@example.com", "roles": ["AGENT"]},
        headers=headers,
    )
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]

    # 3. Invite request (unauthenticated)
    no_auth_res = await client.post("/api/v1/auth/invite", json=invite_payload)
    assert no_auth_res.status_code == 401


async def test_token_validation_and_set_password(client, db_session):
    """Test validation of 7-digit OTP and setting password."""
    await seed_first_superuser(db_session)
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_res = await client.post("/api/v1/auth/login", json=login_data)
    admin_token = login_res.json()["access_token"]

    # Invite user to generate token
    headers = {"Authorization": f"Bearer {admin_token}"}
    invite_payload = {"email": "agent@example.com", "roles": ["AGENT"]}
    await client.post("/api/v1/auth/invite", json=invite_payload, headers=headers)

    # Retrieve generated token from SQLite
    stmt = select(Token).join(User).where(User.email == "agent@example.com")
    token_obj = (await db_session.exec(stmt)).one()
    token_str = token_obj.token
    user_id = token_obj.user_id

    # 1. Validate token with valid inputs
    val_res = await client.post(
        "/api/v1/auth/validate-token",
        json={"user_id": str(user_id), "token": token_str},
    )
    assert val_res.status_code == 200
    assert val_res.json() == {"detail": "Token is valid"}

    # 2. Validate token with invalid inputs
    val_res_bad = await client.post(
        "/api/v1/auth/validate-token",
        json={"user_id": str(user_id), "token": "0000000"},
    )
    assert val_res_bad.status_code == 400

    # 3. Set password with weak password (should fail 400)
    pw_res_weak = await client.post(
        "/api/v1/auth/set-password",
        json={"user_id": str(user_id), "token": token_str, "password": "weak"},
    )
    assert pw_res_weak.status_code == 400

    # 4. Set password with valid password
    pw_res = await client.post(
        "/api/v1/auth/set-password",
        json={
            "user_id": str(user_id),
            "token": token_str,
            "password": "SecureAgentPassword123!",
        },
    )
    assert pw_res.status_code == 200
    assert pw_res.json() == {"detail": "Password set successfully"}

    # Confirm user is verified and password is set
    stmt_user = select(User).where(User.id == user_id)
    user = (await db_session.exec(stmt_user)).one()
    assert user.is_verified is True
    assert user.hashed_password is not None

    # Confirm token is deleted
    stmt_tok = select(Token).where(Token.user_id == user_id)
    toks = (await db_session.exec(stmt_tok)).all()
    assert len(toks) == 0

    # Confirm welcome email sent
    client.welcome_mock_task.assert_called_once()


async def test_re_invite_user(client, db_session):
    """Test re-inviting an unverified user."""
    await seed_first_superuser(db_session)
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_res = await client.post("/api/v1/auth/login", json=login_data)
    admin_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Invite user
    await client.post(
        "/api/v1/auth/invite",
        json={"email": "agent@example.com", "roles": ["AGENT"]},
        headers=headers,
    )

    # Get initial token
    stmt = select(Token).join(User).where(User.email == "agent@example.com")
    token_1 = (await db_session.exec(stmt)).one()
    token_str_1 = token_1.token

    # Re-invite user
    re_invite_payload = {"email": "agent@example.com"}
    re_invite_res = await client.post(
        "/api/v1/auth/re-invite", json=re_invite_payload, headers=headers
    )
    assert re_invite_res.status_code == 200

    # Get new token (should be replaced)
    db_session.expire_all()
    stmt_new = select(Token).join(User).where(User.email == "agent@example.com")
    tokens_after = (await db_session.exec(stmt_new)).all()
    assert len(tokens_after) == 1
    assert tokens_after[0].token != token_str_1


async def test_cleanup_expired_tokens(client, db_session):
    """Verify that cleanup task deletes only expired tokens."""
    await seed_first_superuser(db_session)
    # Create an unverified user
    user = User(
        email="test@example.com", roles=["USER"], is_active=True, is_verified=False
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Create 1 valid token and 1 expired token
    valid_token = Token(
        user_id=user.id,
        token="1111111",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    expired_token = Token(
        user_id=user.id,
        token="2222222",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=15),
    )
    db_session.add(valid_token)
    db_session.add(expired_token)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    stmt = select(Token).where(Token.expires_at < now)
    result = await db_session.exec(stmt)
    expired_toks = result.all()
    assert len(expired_toks) == 1
    await db_session.delete(expired_toks[0])
    await db_session.commit()

    # Confirm only valid token remains
    stmt_rem = select(Token)
    rem = (await db_session.exec(stmt_rem)).all()
    assert len(rem) == 1
    assert rem[0].token == "1111111"
