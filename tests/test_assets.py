import pytest

from src.core.config import settings
from src.services.auth import seed_first_superuser

pytestmark = pytest.mark.asyncio


async def test_central_asset_upload(client, db_session):
    """Verify standard file uploads to S3 storage."""
    await seed_first_superuser(db_session)
    login_data = {
        "username": settings.FIRST_SUPERUSER_EMAIL,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_res = await client.post("/api/v1/auth/login", json=login_data)
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
