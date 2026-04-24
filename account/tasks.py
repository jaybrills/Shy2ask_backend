"""
Celery tasks for the account app.
All email sending is offloaded here so HTTP requests return immediately.
Uses Django's send_mail backend for SMTP (Office365 / Gmail etc.).
"""
from celery import shared_task
import logging
import json

from account.emailing import build_email_context, get_info_connection, send_templated_email
from django.conf import settings
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


def send_email_django(*, subject: str, recipient: str, text_template: str, html_template: str, context: dict):
    """Send branded transactional email from info@shy2ask.com."""
    try:
        send_templated_email(
            subject=subject,
            recipient=recipient,
            text_template=text_template,
            html_template=html_template,
            context=context,
            connection=get_info_connection(),
            from_email=settings.EMAIL_INFO_USER,
        )
        logger.info(f"Email sent to {recipient} from info account with subject '{subject}'")
    except Exception as exc:
        logger.error(f"Failed to send email to {recipient}: {exc}")
        raise exc


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_otp_email_task(self, email: str, otp: str):
    """Send password-reset OTP email asynchronously via Django backend."""
    subject = "Shy2Ask.com password reset code"
    context = build_email_context(
        preheader="Use this one-time code to reset your password.",
        headline="Reset your password",
        intro="We received a request to reset the password for your Shy2Ask.com account.",
        otp=otp,
        otp_label="Password reset code",
        expiry_minutes=15,
        primary_note="Enter this code in the app or website to continue resetting your password.",
        safety_note="If you did not request a password reset, you can safely ignore this email.",
        footer_note="For your security, never share this code with anyone.",
    )
    try:
        send_email_django(
            subject=subject,
            recipient=email,
            text_template="emails/auth_otp.txt",
            html_template="emails/auth_otp.html",
            context=context,
        )
    except Exception as exc:
        log_task_error(self.name, (email, otp), {}, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_verification_email_task(self, email: str, otp: str):
    """Send email verification OTP asynchronously via Django backend."""
    subject = "Verify your email for Shy2Ask.com"
    context = build_email_context(
        preheader="Confirm your email to activate your Shy2Ask.com account.",
        headline="Verify your email",
        intro="Welcome to Shy2Ask.com. Use the code below to verify your email address and activate your account.",
        otp=otp,
        otp_label="Verification code",
        expiry_minutes=10,
        primary_note="Once verified, you can log in and start creating requests securely.",
        safety_note="If you did not create a Shy2Ask.com account, you can ignore this email.",
        footer_note="This verification code works only for a short time for your safety.",
    )
    try:
        send_email_django(
            subject=subject,
            recipient=email,
            text_template="emails/auth_otp.txt",
            html_template="emails/auth_otp.html",
            context=context,
        )
    except Exception as exc:
        log_task_error(self.name, (email, otp), {}, exc)
        raise self.retry(exc=exc)
