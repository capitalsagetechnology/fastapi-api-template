import logging
import sys
from typing import List

from pymongo import MongoClient

from src.core.config import settings
from src.services.email import send_html_email
from src.worker.celery_app import celery_app

logger = logging.getLogger("worker.tasks")


@celery_app.task(name="tasks.send_invitation_email")
def send_invitation_email_task(
    email: str, invite_url: str, expires_at: str, roles: List[str]
) -> bool:
    """Celery background task to dispatch HTML invitation emails."""
    logger.info(f"Starting Celery background task: sending invitation email to {email}")
    context = {
        "invite_url": invite_url,
        "expires_at": expires_at,
        "roles": roles,
    }
    return send_html_email(
        to_email=email,
        subject="You have been invited to join the platform",
        template_name="email/invite.html",
        context=context,
    )


@celery_app.task(name="tasks.send_welcome_email")
def send_welcome_email_task(email: str, login_url: str) -> bool:
    """Celery background task to dispatch HTML welcome emails upon registration."""
    logger.info(f"Starting Celery background task: sending welcome email to {email}")
    context = {
        "email": email,
        "login_url": login_url,
    }
    return send_html_email(
        to_email=email,
        subject="Welcome! Account successfully configured",
        template_name="email/welcome.html",
        context=context,
    )


# MongoDB Logger Client configuration
# Global MongoClient, initialized lazily and thread-safe.
_mongo_client = None


def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        if settings.MONGO_URL:
            _mongo_client = MongoClient(
                settings.MONGO_URL, serverSelectionTimeoutMS=2000
            )
        else:
            # Fallback for testing / local running outside container
            _mongo_client = MongoClient(
                "mongodb://localhost:27017/logs_db", serverSelectionTimeoutMS=2000
            )
    return _mongo_client


@celery_app.task(name="tasks.log_to_mongodb", queue="logging")
def log_to_mongodb_task(log_data: dict) -> None:
    """Celery background task to write an HTTP request/response log to MongoDB."""
    if "pytest" in sys.modules:
        logger.info(
            f"Test environment detected. Skipping MongoDB log write: {log_data}"
        )
        return

    try:
        client = get_mongo_client()
        try:
            db = client.get_default_database()
        except Exception:
            db = client["logs_db"]
        collection = db["request_logs"]
        collection.insert_one(log_data)
    except Exception as e:
        logger.error(f"Failed to write log to MongoDB: {e}")
