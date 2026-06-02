import os
import sys
from unittest.mock import MagicMock

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Add workspace to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.database import get_db
from src.main import app

# Test SQLite in-memory Database URL
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


class MockRedisSessionManager:
    """In-memory Redis session manager mock."""

    def __init__(self):
        self.sessions = {}

    def _get_key(self, user_id, jti):
        return f"session:{str(user_id)}:{jti}"

    async def create_session(self, user_id, jti, expire_minutes):
        self.sessions[self._get_key(user_id, jti)] = "active"

    async def is_session_active(self, user_id, jti):
        return self._get_key(user_id, jti) in self.sessions

    async def invalidate_session(self, user_id, jti):
        self.sessions.pop(self._get_key(user_id, jti), None)


class MockS3Service:
    """Mock storage service mimicking S3 uploads."""

    async def upload_file(
        self, file_content: bytes, filename: str, content_type: str
    ) -> str:
        return f"https://mock-bucket.s3.amazonaws.com/assets/{filename}"


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create in-memory SQLite tables and yield session for each test function."""
    engine = create_async_engine(
        TEST_DATABASE_URL, connect_args={"check_same_thread": False}
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async_session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session

    # Drop tables and close
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db_session, monkeypatch):
    """
    Yields Async HTTP Client configured with mock DB,
    mock Redis session cache, mock S3, and mock Celery emails.
    """
    # 1. Override Database Dependency
    app.dependency_overrides[get_db] = lambda: db_session

    # 2. Mock Redis session management in auth module and dependencies
    mock_redis = MockRedisSessionManager()
    monkeypatch.setattr("src.services.auth.session_manager", mock_redis)
    monkeypatch.setattr("src.api.deps.session_manager", mock_redis)
    monkeypatch.setattr("src.api.v1.auth.session_manager", mock_redis)

    # 3. Mock S3 storage operations
    mock_s3 = MockS3Service()
    monkeypatch.setattr("src.api.v1.users.s3_service", mock_s3)
    monkeypatch.setattr("src.api.v1.assets.s3_service", mock_s3)

    # 4. Mock Celery email task delays
    mock_invite_task = MagicMock()
    mock_welcome_task = MagicMock()
    mock_log_task = MagicMock()
    monkeypatch.setattr(
        "src.services.auth.send_invite_otp_email_task.delay", mock_invite_task
    )
    monkeypatch.setattr(
        "src.services.auth.send_welcome_email_task.delay", mock_welcome_task
    )
    monkeypatch.setattr("src.core.middleware.log_to_mongodb_task.delay", mock_log_task)

    # 5. Build ASGI Transport for HTTPX AsyncClient
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        # Attach mocks dynamically to the client to make assertions easier in tests
        ac.invite_mock_task = mock_invite_task
        ac.welcome_mock_task = mock_welcome_task
        ac.log_mock_task = mock_log_task
        ac.redis_sessions = mock_redis
        yield ac

    # Clean overrides
    app.dependency_overrides.clear()
