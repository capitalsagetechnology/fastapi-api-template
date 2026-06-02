import logging
from typing import Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from src.api.deps import IPWhitelistChecker, ScopedAPIKeyChecker, get_current_user
from src.models.api_key import APIKey
from src.models.user import User
from src.services.s3 import s3_service

router = APIRouter()
logger = logging.getLogger("api.assets")


class UploadResponse(BaseModel):
    filename: str
    url: str


@router.post(
    "/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED
)
async def upload_asset(
    file: UploadFile = File(...), current_user: User = Depends(get_current_user)
):
    """
    Centralized endpoint for uploading files to S3.
    Requires a valid JWT session.
    """
    try:
        content = await file.read()
        file_url = await s3_service.upload_file(
            file_content=content, filename=file.filename, content_type=file.content_type
        )
        return UploadResponse(filename=file.filename, url=file_url)
    except Exception as e:
        logger.error(f"Asset upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Asset upload failed: {str(e)}",
        )


# Whitelisted IP Demo Endpoint
@router.get("/secure-config", dependencies=[Depends(IPWhitelistChecker())])
async def get_secure_configuration() -> Dict[str, str]:
    """
    Endpoint protected by IP Whitelisting.
    Only client IPs specified in ALLOWED_IPS can call this route.
    """
    return {
        "status": "authorized",
        "message": "You are accessing this endpoint from a whitelisted IP address.",
        "whitelisted_ip_checked": "Passed",
    }


# Scoped API Key Demo Endpoint
@router.get("/audit", response_model=dict)
async def get_audit_logs(
    api_key: APIKey = Depends(ScopedAPIKeyChecker(required_scopes=["assets:audit"])),
) -> Dict[str, str]:
    """
    Endpoint protected by Scoped API Keys.
    Requires header X-API-Key with scope 'assets:audit'.
    """
    return {
        "status": "authorized",
        "api_key_name": api_key.name,
        "allowed_scopes": api_key.scopes,
        "message": "Scope verification successful. Access granted to audit logs.",
    }
