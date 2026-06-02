import logging
from typing import List

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
