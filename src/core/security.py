import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from src.core.config import settings


def get_password_hash(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify standard plain text password matches bcrypt hashed password."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def create_access_token(
    subject: str | Any, expires_delta: timedelta = None
) -> tuple[str, str]:
    """
    Create a JWT access token.
    Returns:
        (token_str, jti_uuid_str)
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    jti = str(uuid.uuid4())
    to_encode = {"exp": expire, "sub": str(subject), "jti": jti, "type": "access"}
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt, jti


def decode_access_token(token: str) -> dict | None:
    """
    Decode and validate a JWT access token.
    Returns payload dict if valid, else None.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        # Verify token type
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None
