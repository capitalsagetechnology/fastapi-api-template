import hashlib
import hmac
import struct
import time
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


def generate_totp_7_digit(
    user_id: uuid.UUID, secret_key: str, counter_offset: int = 0
) -> str:
    """Generate a 7-digit OTP leveraging TOTP with the user_id uniquely."""
    # 1. Create user-specific secret key
    key_material = f"{user_id}-{secret_key}".encode("utf-8")
    secret = hashlib.sha256(key_material).digest()

    # 2. Get 30-minute time step counter
    time_step = 1800  # 30 minutes in seconds
    counter = int(time.time() / time_step) + counter_offset

    # Pack counter as 8-byte big-endian
    msg = struct.pack(">Q", counter)

    # 3. HMAC-SHA256
    hs = hmac.new(secret, msg, hashlib.sha256).digest()

    # 4. Dynamic truncation
    offset = hs[-1] & 0x0F
    binary = struct.unpack(">I", hs[offset : offset + 4])[0] & 0x7FFFFFFF

    # 5. Extract 7-digit OTP
    otp = binary % 10_000_000
    return f"{otp:07d}"


def uuid7() -> uuid.UUID:
    """Generate a UUIDv7 (time-based) according to RFC 9562."""
    from uuid6 import uuid7 as _uuid7

    return uuid.UUID(bytes=_uuid7().bytes)
