import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.v1 import api_router
from src.core.config import settings
from src.core.database import async_session_maker
from src.core.logging import setup_logging
from src.core.middleware import RequestLoggingMiddleware
from src.services.auth import seed_first_superuser

logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize logging
    setup_logging()
    logger.info("Initializing FastAPI application...")

    # 2. Seed default admin user
    async with async_session_maker() as session:
        try:
            await seed_first_superuser(session)
        except Exception as e:
            logger.error(f"Error seeding admin user: {e}")

    yield
    logger.info("Shutting down FastAPI application...")


# Initialize application
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production-grade template with JWT, Redis sessions, S3, Celery, and whitelisting",
    version="0.1.0",
    lifespan=lifespan,
    # Crucial setting: Persist auth token in swagger UI across reloads
    swagger_ui_parameters={"persistAuthorization": True},
)

# CORS configurations
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Request response logging and sensitive masking middleware
app.add_middleware(RequestLoggingMiddleware)

# API routes
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check():
    """Simple healthcheck endpoint."""
    return {"status": "ok", "project": settings.PROJECT_NAME}
