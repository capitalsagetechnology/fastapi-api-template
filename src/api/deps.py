import hashlib
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.config import settings
from src.core.database import get_db
from src.core.security import decode_access_token
from src.models.api_key import APIKey
from src.models.user import User
from src.services.auth import session_manager

# Token url matches our login endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


async def get_current_user(
    db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> User:
    """
    Extracts access token from Authorization header, validates signature/expiry,
    and checks if the session is registered as active in Redis.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception

    user_id_str: str = payload.get("sub")
    jti: str = payload.get("jti")
    if not user_id_str or not jti:
        raise credentials_exception

    # 1. Validate against Redis session blacklist/whitelist
    session_active = await session_manager.is_session_active(user_id_str, jti)
    if not session_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or been logged out. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Get User from Database
    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise credentials_exception

    stmt = select(User).where(User.id == user_uuid)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user account"
        )

    # Store token ID (jti) dynamically on user model instance to support logout invalidation
    user._current_jti = jti
    return user


class RoleChecker:
    """Dependency that evaluates user roles. ADMIN role automatically overrides access checks."""

    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if "ADMIN" in current_user.roles:
            return current_user

        user_has_role = any(role in current_user.roles for role in self.allowed_roles)
        if not user_has_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: User does not have any of required roles: {self.allowed_roles}",
            )
        return current_user


class IPWhitelistChecker:
    """Dependency class that whitelists specific API endpoints by client IP."""

    def __init__(self, allowed_ips: Optional[List[str]] = None):
        self.allowed_ips = allowed_ips or settings.ALLOWED_IPS

    def __call__(self, request: Request) -> None:
        # Extract IP (supports proxy setup via X-Forwarded-For)
        ip_address = request.headers.get("x-forwarded-for")
        if ip_address:
            ip_address = ip_address.split(",")[0].strip()
        else:
            ip_address = request.client.host if request.client else "unknown"

        if ip_address not in self.allowed_ips:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access Denied: IP '{ip_address}' is not authorized to call this API.",
            )


def hash_api_key(key: str) -> str:
    """Produce SHA-256 hash of API key for secure database matching."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class ScopedAPIKeyChecker:
    """Dependency that validates X-API-Key headers and verifies scopes."""

    def __init__(self, required_scopes: Optional[List[str]] = None):
        self.required_scopes = required_scopes or []

    async def __call__(
        self,
        x_api_key: str = Header(
            ..., alias="X-API-Key", description="Scoped API credential key"
        ),
        db: AsyncSession = Depends(get_db),
    ) -> APIKey:
        hashed = hash_api_key(x_api_key)

        # Query active key matching the hash
        stmt = select(APIKey).where(APIKey.hashed_key == hashed, APIKey.is_active)
        result = await db.execute(stmt)
        api_key_obj = result.scalar_one_or_none()

        if not api_key_obj:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key."
            )

        # Verify key expiration
        if api_key_obj.expires_at and datetime.now(
            timezone.utc
        ) > api_key_obj.expires_at.replace(tzinfo=timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key has expired."
            )

        # Verify scopes
        missing_scopes = [
            scope for scope in self.required_scopes if scope not in api_key_obj.scopes
        ]
        if missing_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: API Key lacks required scopes: {missing_scopes}",
            )

        return api_key_obj
