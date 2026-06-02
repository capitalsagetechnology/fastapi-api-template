import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import redis.asyncio as redis
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.config import settings
from src.core.security import create_access_token, get_password_hash, verify_password
from src.models.user import Invitation, User
from src.services.s3 import s3_service
from src.worker.tasks import send_invitation_email_task, send_welcome_email_task

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
    email = settings.FIRST_SUPERUSER_EMAIL
    # Check if any user exists with this email
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()

    if not existing_user:
        logger.info(f"Seeding admin user: {email}...")
        admin_user = User(
            email=email,
            hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
            roles=["ADMIN"],
            is_active=True,
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
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            return None
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
    ) -> Invitation:
        """Create a secure invitation token in database and trigger Celery task to email it."""
        # 1. Create secure token
        token = uuid.uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=7
        )  # Invitation valid for 7 days

        invitation = Invitation(
            email=email,
            token=token,
            roles=roles,
            expires_at=expires_at,
            created_by_id=admin_user.id,
        )
        db.add(invitation)
        await db.commit()
        await db.refresh(invitation)

        # 2. Trigger Celery worker to send email
        invite_url = f"http://localhost:8000/api/v1/auth/register-invite?token={token}"
        expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Dispatch Celery background task
        send_invitation_email_task.delay(
            email=email, invite_url=invite_url, expires_at=expires_str, roles=roles
        )

        logger.info(f"Created invitation for {email} by admin {admin_user.email}")
        return invitation

    @staticmethod
    async def register_from_invitation(
        db: AsyncSession,
        token: str,
        password: str,
        profile_image_bytes: Optional[bytes] = None,
        profile_image_filename: Optional[str] = None,
        profile_image_content_type: Optional[str] = None,
    ) -> User:
        """Complete user registration from an invitation token."""
        # 1. Retrieve and validate the invitation token
        stmt = select(Invitation).where(Invitation.token == token)
        result = await db.execute(stmt)
        invitation = result.scalar_one_or_none()

        if not invitation:
            raise ValueError("Invalid invitation token.")
        if invitation.accepted_at:
            raise ValueError("Invitation has already been accepted.")
        if datetime.now(timezone.utc) > invitation.expires_at.replace(
            tzinfo=timezone.utc
        ):
            raise ValueError("Invitation has expired.")

        # 2. Check if a user with that email already exists
        user_stmt = select(User).where(User.email == invitation.email)
        user_result = await db.execute(user_stmt)
        if user_result.scalar_one_or_none():
            raise ValueError("User with this email already exists.")

        # 3. Handle optional profile image upload to S3
        profile_image_url = None
        if (
            profile_image_bytes
            and profile_image_filename
            and profile_image_content_type
        ):
            profile_image_url = await s3_service.upload_file(
                file_content=profile_image_bytes,
                filename=profile_image_filename,
                content_type=profile_image_content_type,
            )

        # 4. Create new user
        new_user = User(
            email=invitation.email,
            hashed_password=get_password_hash(password),
            roles=invitation.roles,
            is_active=True,
            profile_image=profile_image_url,
        )
        db.add(new_user)

        # 5. Mark invitation as accepted
        invitation.accepted_at = datetime.now(timezone.utc)
        db.add(invitation)

        await db.commit()
        await db.refresh(new_user)

        # 6. Trigger Celery worker to send Welcome Email
        login_url = "http://localhost:8000/api/v1/auth/login"
        send_welcome_email_task.delay(email=new_user.email, login_url=login_url)

        logger.info(f"User {new_user.email} registered successfully from invitation.")
        return new_user
