import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from src.api.deps import get_current_user, hash_api_key
from src.core.database import get_db
from src.models.api_key import APIKey
from src.models.user import User
from src.services.s3 import s3_service

router = APIRouter()
logger = logging.getLogger("api.users")


# Schemas
class UserMeResponse(BaseModel):
    id: str
    email: str
    roles: List[str]
    is_active: bool
    profile_image: Optional[str] = None


class APIKeyCreateRequest(BaseModel):
    name: str
    scopes: List[str]
    expires_in_days: Optional[int] = 30


class APIKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: List[str]
    is_active: bool
    expires_at: Optional[str]
    raw_key: Optional[str] = None  # Returned ONLY during creation


@router.get("/me", response_model=UserMeResponse)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Fetch current authenticated user's profile details."""
    return UserMeResponse(
        id=str(current_user.id),
        email=current_user.email,
        roles=current_user.roles,
        is_active=current_user.is_active,
        profile_image=current_user.profile_image,
    )


@router.post("/me/profile-image", response_model=UserMeResponse)
async def upload_profile_image(
    profile_image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload new profile photo to S3 and update the user record."""
    # Validate file type
    if not profile_image.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image type (jpeg, png, etc.)",
        )

    try:
        content = await profile_image.read()
        image_url = await s3_service.upload_file(
            file_content=content,
            filename=profile_image.filename,
            content_type=profile_image.content_type,
        )

        # Save to DB
        current_user.profile_image = image_url
        db.add(current_user)
        await db.commit()
        await db.refresh(current_user)

        return UserMeResponse(
            id=str(current_user.id),
            email=current_user.email,
            roles=current_user.roles,
            is_active=current_user.is_active,
            profile_image=current_user.profile_image,
        )
    except Exception as e:
        logger.error(f"Failed to update profile image: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}",
        )


@router.post(
    "/api-keys", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED
)
async def create_scoped_api_key(
    payload: APIKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a new scoped API key for secure third-party service integration.
    WARNING: The raw key is returned ONLY once in this response payload.
    """
    # 1. Generate unique raw api key string
    raw_key = f"ak_{secrets.token_hex(20)}"
    prefix = raw_key[:8]  # e.g., "ak_12345"
    hashed = hash_api_key(raw_key)

    expires_at = None
    if payload.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=payload.expires_in_days
        )

    new_key = APIKey(
        name=payload.name,
        prefix=prefix,
        hashed_key=hashed,
        scopes=payload.scopes,
        is_active=True,
        expires_at=expires_at,
        user_id=current_user.id,
    )

    try:
        db.add(new_key)
        await db.commit()
        await db.refresh(new_key)

        return APIKeyResponse(
            id=str(new_key.id),
            name=new_key.name,
            prefix=new_key.prefix,
            scopes=new_key.scopes,
            is_active=new_key.is_active,
            expires_at=new_key.expires_at.isoformat() if new_key.expires_at else None,
            raw_key=raw_key,  # Send the unhashed key once
        )
    except Exception as e:
        logger.error(f"Failed to create API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate API Key.",
        )
