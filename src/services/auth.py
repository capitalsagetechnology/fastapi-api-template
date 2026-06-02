import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import redis.asyncio as redis
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.config import settings
from src.core.security import (
    create_access_token,
    generate_totp_7_digit,
    get_password_hash,
    verify_password,
)
from src.models.user import Token as TokenModel
from src.models.user import User
from src.worker.tasks import send_invite_otp_email_task, send_welcome_email_task

logger = logging.getLogger("services.auth")

# Initialize Redis Connection
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)


class RedisSessionManager:
    """Manages active user JWT sessions in Redis to support revocation (logouts)."""

    @staticmethod
    def _get_key(user_id: str | uuid.UUID, jti: str) -> str:
        return f"session:{str(user_id)}:{jti}"

    async def create_session(
        self, user_id: str | uuid.UUID, jti: str, expire_minutes: int
    ) -> None:
        key = self._get_key(user_id, jti)
        await redis_client.setex(name=key, time=expire_minutes * 60, value="active")
        logger.info(f"Session created in Redis for user {user_id} with JWT ID {jti}")

    async def is_session_active(self, user_id: str | uuid.UUID, jti: str) -> bool:
        key = self._get_key(user_id, jti)
        exists = await redis_client.exists(key)
        return exists > 0

    async def invalidate_session(self, user_id: str | uuid.UUID, jti: str) -> None:
        key = self._get_key(user_id, jti)
        await redis_client.delete(key)
        logger.info(
            f"Session invalidated in Redis for user {user_id} with JWT ID {jti}"
        )


session_manager = RedisSessionManager()


async def seed_first_superuser(db: AsyncSession) -> None:
    """Seed the initial ADMIN user using settings config."""
    email = settings.FIRST_SUPERUSER_EMAIL.strip().lower()
    # Check if any user exists with this email
    stmt = select(User).where(User.email == email)
    existing_user = (await db.exec(stmt)).one_or_none()

    if not existing_user:
        logger.info(f"Seeding admin user: {email}...")
        admin_user = User(
            email=email,
            hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
            roles=["ADMIN"],
            is_active=True,
            is_verified=True,
        )
        db.add(admin_user)
        await db.commit()
        logger.info("Admin user seeded successfully.")
    else:
        logger.info("Admin user seeding skipped: already exists.")


class AuthService:
    @staticmethod
    async def authenticate_user(
        db: AsyncSession, email: str, password: str
    ) -> Optional[User]:
        """Authenticate user against email and password. Returns User if valid."""
        # Normalize email before lookup
        email_normalized = email.strip().lower()
        stmt = select(User).where(User.email == email_normalized)
        user = (await db.exec(stmt)).one_or_none()

        if not user:
            return None
        if not user.hashed_password or not verify_password(
            password, user.hashed_password
        ):
            return None
        if not user.is_active:
            return None
        if not user.is_verified:
            return None

        # Track last login
        user.last_login = datetime.now(timezone.utc)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def generate_user_token(user: User) -> dict:
        """Create token and register the session in Redis."""
        token, jti = create_access_token(subject=user.id)
        await session_manager.create_session(
            user_id=user.id,
            jti=jti,
            expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        )
        return {"access_token": token, "token_type": "bearer"}

    @staticmethod
    async def create_user_invitation(
        db: AsyncSession, admin_user: User, email: str, roles: List[str]
    ) -> User:
        """Create a new User and a unique 7-digit OTP verification token, then send it via Celery."""
        # 1. Normalize email
        email_normalized = email.strip().lower()

        # Check if user already exists
        stmt = select(User).where(User.email == email_normalized)
        existing_user = (await db.exec(stmt)).one_or_none()
        if existing_user:
            raise ValueError("User with this email already exists.")

        # 2. Create User record (unverified, no password set yet)
        new_user = User(
            email=email_normalized,
            roles=roles,
            is_active=True,
            is_verified=False,
            hashed_password=None,
        )
        db.add(new_user)
        await db.flush()  # Populates user ID

        # 3. Generate a unique 7-digit OTP token
        counter_offset = 0
        while True:
            otp = generate_totp_7_digit(
                new_user.id, settings.SECRET_KEY, counter_offset
            )
            stmt_token = select(TokenModel).where(TokenModel.token == otp)
            existing_token = (await db.exec(stmt_token)).first()
            if not existing_token:
                break
            counter_offset += 1

        # 4. Save token to DB
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        token_record = TokenModel(
            user_id=new_user.id,
            token=otp,
            expires_at=expires_at,
        )
        db.add(token_record)
        await db.commit()
        await db.refresh(new_user)

        # 5. Send token over Celery
        expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        send_invite_otp_email_task.delay(
            email=new_user.email,
            token=otp,
            expires_at=expires_str,
        )

        logger.info(
            f"Created invitation for {new_user.email} (ID: {new_user.id}) by admin {admin_user.email}"
        )
        return new_user

    @staticmethod
    async def re_invite_user(db: AsyncSession, admin_user: User, email: str) -> User:
        """Re-invite an existing user who has not yet verified their password."""
        email_normalized = email.strip().lower()
        stmt = select(User).where(User.email == email_normalized)
        user = (await db.exec(stmt)).one_or_none()

        if not user:
            raise ValueError("User not found.")
        if user.is_verified:
            raise ValueError("User has already set a password and is verified.")

        # Delete any existing active/expired tokens for this user first
        stmt_del = select(TokenModel).where(TokenModel.user_id == user.id)
        existing_tokens = (await db.exec(stmt_del)).all()
        deleted_tokens = [t.token for t in existing_tokens]
        for t in existing_tokens:
            await db.delete(t)
        await db.flush()

        # Generate a new unique 7-digit OTP token
        counter_offset = 0
        while True:
            otp = generate_totp_7_digit(user.id, settings.SECRET_KEY, counter_offset)
            if otp in deleted_tokens:
                counter_offset += 1
                continue
            stmt_token = select(TokenModel).where(TokenModel.token == otp)
            existing_token = (await db.exec(stmt_token)).first()
            if not existing_token:
                break
            counter_offset += 1

        # Save token to DB
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        token_record = TokenModel(
            user_id=user.id,
            token=otp,
            expires_at=expires_at,
        )
        db.add(token_record)
        await db.commit()

        # Send token over Celery
        expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        send_invite_otp_email_task.delay(
            email=user.email,
            token=otp,
            expires_at=expires_str,
        )

        logger.info(
            f"Re-invited user {user.email} (ID: {user.id}) by admin {admin_user.email}"
        )
        return user

    @staticmethod
    async def validate_token(db: AsyncSession, user_id: uuid.UUID, token: str) -> bool:
        """Validate if the invitation/verification token is valid and active."""
        stmt = select(TokenModel).where(
            TokenModel.user_id == user_id,
            TokenModel.token == token,
        )
        token_record = (await db.exec(stmt)).one_or_none()
        if not token_record:
            return False
        if datetime.now(timezone.utc) > token_record.expires_at.replace(
            tzinfo=timezone.utc
        ):
            return False
        return True

    @staticmethod
    async def set_password_via_token(
        db: AsyncSession, user_id: uuid.UUID, token: str, password: str
    ) -> User:
        """Verify the token, set the user's password, activate their account, and delete the token."""
        stmt = select(TokenModel).where(
            TokenModel.user_id == user_id,
            TokenModel.token == token,
        )
        token_record = (await db.exec(stmt)).one_or_none()
        if not token_record:
            raise ValueError("Invalid verification token.")
        if datetime.now(timezone.utc) > token_record.expires_at.replace(
            tzinfo=timezone.utc
        ):
            raise ValueError("Verification token has expired.")

        # Retrieve user
        stmt_user = select(User).where(User.id == user_id)
        user = (await db.exec(stmt_user)).one_or_none()
        if not user:
            raise ValueError("User not found.")

        # Validate password
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")

        # Update user password and mark as verified
        user.hashed_password = get_password_hash(password)
        user.is_verified = True
        db.add(user)

        # Delete token
        await db.delete(token_record)

        await db.commit()
        await db.refresh(user)

        # Trigger welcome email task
        login_url = "http://localhost:8000/api/v1/auth/login"
        send_welcome_email_task.delay(email=user.email, login_url=login_url)

        logger.info(
            f"User {user.email} (ID: {user.id}) successfully verified their account and set their password."
        )
        return user
