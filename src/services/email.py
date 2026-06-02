import logging
import os

from jinja2 import Environment, FileSystemLoader
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from src.core.config import settings

logger = logging.getLogger("services.email")

# Load template directory relative to this file's folder (src/services -> src/templates)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.normpath(os.path.join(CURRENT_DIR, "..", "templates"))
jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))


def send_html_email(
    to_email: str, subject: str, template_name: str, context: dict
) -> bool:
    """
    Renders an HTML email template and sends it to the recipient.
    If SENDGRID_API_KEY is not configured in settings, it logs the output to stdout.
    """
    context.setdefault("project_name", settings.PROJECT_NAME)

    try:
        # Load and render Jinja2 email template
        template = jinja_env.get_template(template_name)
        html_content = template.render(**context)
    except Exception as e:
        logger.error(f"Error rendering template '{template_name}': {e}")
        raise RuntimeError(f"Email rendering failed: {e}")

    # Dispatch email
    if settings.SENDGRID_API_KEY:
        try:
            message = Mail(
                from_email=settings.SENDER_EMAIL,
                to_emails=to_email,
                subject=subject,
                html_content=html_content,
            )
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
            response = sg.send(message)
            logger.info(
                f"Email successfully sent to {to_email} via SendGrid. Status: {response.status_code}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email} via SendGrid: {e}")
            raise e
    else:
        logger.info(
            f"\n=== MOCK EMAIL SENT ===\n"
            f"Recipient: {to_email}\n"
            f"Subject:   {subject}\n"
            f"HTML Body:\n{html_content}\n"
            f"=======================\n"
        )
        return True
