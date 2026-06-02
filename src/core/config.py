import json
from typing import List

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Annotated


def parse_cors_origins(v: str | List[str]) -> List[str]:
    if isinstance(v, str):
        if not v.strip():
            return []
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [i.strip() for i in v.split(",") if i.strip()]
    return v


def parse_sensitive_keys(v: str | List[str]) -> List[str]:
    if isinstance(v, str):
        return [i.strip().lower() for i in v.split(",") if i.strip()]
    return [i.lower() for i in v]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    # API Settings
    PROJECT_NAME: str = "FastAPI Production Template"
    API_V1_STR: str = "/api/v1"

    # CORS Origins
    BACKEND_CORS_ORIGINS: Annotated[
        str | List[str], BeforeValidator(parse_cors_origins)
    ] = []

    # Security
    SECRET_KEY: str = "super-secret-key-change-in-production-1234567890!"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Seeding
    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "AdminPassword123!"

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "app"
    DATABASE_URL: str | None = None

    @property
    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def get_sync_database_url(self) -> str:
        """Required for Alembic migrations, which are run synchronously."""
        url = self.get_database_url
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql://")
        return url

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery & RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672//"

    # SendGrid
    SENDGRID_API_KEY: str = ""
    SENDER_EMAIL: str = "noreply@example.com"

    # S3 Storage / LocalStack
    AWS_ACCESS_KEY_ID: str = "mock-key"
    AWS_SECRET_ACCESS_KEY: str = "mock-secret"
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "app-assets"
    S3_ENDPOINT_URL: str | None = (
        "http://localhost:4566"  # Point to LocalStack by default in dev
    )

    # Logging Middleware
    SENSITIVE_KEYS: Annotated[
        str | List[str], BeforeValidator(parse_sensitive_keys)
    ] = [
        "password",
        "password_confirm",
        "token",
        "secret",
        "access_token",
        "authorization",
        "api_key",
        "x-api-key",
        "credit_card",
    ]

    ALLOWED_IPS: Annotated[str | List[str], BeforeValidator(parse_cors_origins)] = [
        "127.0.0.1",
        "::1",
    ]


settings = Settings()
