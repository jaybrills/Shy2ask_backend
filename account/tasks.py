"""
Celery tasks for the account app.
All email and push-notification sending is offloaded here so HTTP requests
return immediately.
"""
import json
import logging

from celery import shared_task
from django.conf import settings

from account.emailing import build_email_context, get_info_connection, send_templated_email
from account.models import CeleryTaskError

logger = logging.getLogger(__name__)


def log_task_error(task_name: str, args: tuple, kwargs: dict, exc: Exception) -> None:
    """Persist a Celery task failure to the DB and always log it."""
    try:
        CeleryTaskError.objects.create(
            task_name=task_name,
            args=json.dumps(args),
            kwargs=json.dumps(kwargs),
            exception=str(exc),
        )
    except Exception as e:
        logger.error("Failed to log Celery task error to DB: %s", e)


def send_email_django(*, subject: str, recipient: str, text_template: str, html_template: str, context: dict) -> None:
    """Send a branded transactional email from info@shy2ask.com."""
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
        logger.info("Email sent to %s — subject: %s", recipient, subject)
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", recipient, exc)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_otp_email_task(self, email: str, otp: str) -> None:
    """Send a password-reset OTP email asynchronously."""
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
            subject="Shy2Ask.com password reset code",
            recipient=email,
            text_template="emails/auth_otp.txt",
            html_template="emails/auth_otp.html",
            context=context,
        )
    except Exception as exc:
        log_task_error(self.name, (email,), {}, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_verification_email_task(self, email: str, otp: str) -> None:
    """Send an email-verification OTP asynchronously."""
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
            subject="Verify your email for Shy2Ask.com",
            recipient=email,
            text_template="emails/auth_otp.txt",
            html_template="emails/auth_otp.html",
            context=context,
        )
    except Exception as exc:
        log_task_error(self.name, (email,), {}, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_push_notification_task(self, user_id: int, title: str, body: str, data: dict | None = None) -> None:
    """
    Send a Firebase push notification to all active devices of a user.

    Fetches every registered active FCM token for the user and delivers via
    FCM's batch API in a single round-trip. Stale/unregistered tokens are
    deactivated automatically after the batch completes.

    Every notification is persisted to UserNotification before FCM delivery
    so the in-app notification history is always complete regardless of
    device state or FCM token validity.

    Args:
        user_id:  Primary key of the recipient User.
        title:    Notification title shown on the device.
        body:     Notification body text.
        data:     Optional key-value payload delivered alongside the notification.
                  All values are coerced to strings (FCM requirement).
    """
    from account.firebase import send_to_user_devices
    from account.models import UserNotification

    payload = data or {}

    # ── Persist to DB first (history is written even if FCM fails) ────────
    try:
        UserNotification.objects.create(
            user_id=user_id,
            title=title,
            body=body,
            notification_type=payload.get("type", ""),
            priority=payload.get("priority", UserNotification.Priority.MEDIUM),
            data=payload,
        )
    except Exception as exc:
        # Never let a DB write failure block the actual push delivery
        logger.error(
            "Failed to persist UserNotification for user_id=%s: %s",
            user_id, exc,
        )

    # ── Deliver via FCM ───────────────────────────────────────────────────
    try:
        stats = send_to_user_devices(user_id=user_id, title=title, body=body, data=payload)
        logger.info(
            "Push notification dispatched — user_id=%s title=%r stats=%s",
            user_id, title, stats,
        )
    except Exception as exc:
        log_task_error(self.name, (user_id, title, body), payload, exc)
        raise self.retry(exc=exc)
