import pytest

from src.core.config import settings
from src.services.auth import seed_first_superuser

pytestmark = pytest.mark.asyncio


async def test_scoped_api_key_access(client, db_session):
    """Test creating scoped api keys and making requests to scoped-resource endpoints."""
    await seed_first_superuser(db_session)
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_res = await client.post("/api/v1/auth/login", json=login_data)
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
