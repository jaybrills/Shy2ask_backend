"""
Celery tasks for the account app.
All email sending is offloaded here so HTTP requests return immediately.
Uses Django's send_mail backend for SMTP (Office365 / Gmail etc.).
"""
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
import logging
import json
from account.models import CeleryTaskError  # optional: DB logging

logger = logging.getLogger(__name__)


def log_task_error(task_name: str, args: tuple, kwargs: dict, exc: Exception):
    """Log task errors to DB and fallback to logger."""
    try:
        CeleryTaskError.objects.create(
            task_name=task_name,
            args=json.dumps(args),
            kwargs=json.dumps(kwargs),
            exception=str(exc),
        )
    except Exception as e:
        logger.error(f"Failed to log Celery task error: {e}")


def send_email_django(subject: str, message: str, recipient: str, html_message: str = None):
    """Send email via Django's send_mail backend."""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
            html_message=html_message,
        )
        logger.info(f"Email sent to {recipient} via Django backend with subject '{subject}'")
    except Exception as exc:
        logger.error(f"Failed to send email to {recipient}: {exc}")
        raise exc


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_otp_email_task(self, email: str, otp: str):
    """Send password-reset OTP email asynchronously via Django backend."""
    subject = "Shy2Ask – Password reset code"
    message = (
        f"Your password reset code is: {otp}\n\n"
        "It is valid for 15 minutes.\n\n"
        "If you did not request this, ignore this email."
    )
    try:
        send_email_django(subject, message, email)
    except Exception as exc:
        log_task_error(self.name, (email, otp), {}, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_verification_email_task(self, email: str, otp: str):
    """Send email verification OTP asynchronously via Django backend."""
    subject = "Shy2Ask – Verify your email"
    message = (
        f"Your email verification code is: {otp}\n\n"
        "It is valid for 10 minutes.\n\n"
        "If you did not create an account, ignore this email."
    )
    try:
        send_email_django(subject, message, email)
    except Exception as exc:
        log_task_error(self.name, (email, otp), {}, exc)
        raise self.retry(exc=exc)