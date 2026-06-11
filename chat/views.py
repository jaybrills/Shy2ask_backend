import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _normalize_email(email: str | None) -> str:
    if not email:
        return ""

    from account.models import User

    return User.objects.normalize_email(email).lower()


def _resolve_notification_recipient_user(recipient, related_request=None):
    if not recipient:
        return None

    from account.models import User

    recipient_user = User.objects.find_by_email(recipient)
    if recipient_user or not related_request:
        return recipient_user

    normalized_recipient = _normalize_email(recipient)
    if normalized_recipient and normalized_recipient == _normalize_email(getattr(related_request, "requester_email", "")):
        return related_request.requester_identity
    if normalized_recipient and normalized_recipient == _normalize_email(getattr(related_request, "target_email", "")):
        return related_request.target_user
    return None


def send_notification(subject, body, recipient, related_request=None, use_ai_enhance=True, deliver_email=True, push_type: str | None = None, deliver_push: bool = True):
    """
    Central notification dispatcher — email + DB record + WebSocket + push.

    push_type: optional key from account.push_notifications.REGISTRY.
               When supplied the push body/title comes from the template.
               When omitted the email subject/body are used directly for push.
    """
    if not recipient:
        return

    if use_ai_enhance and getattr(settings, "OPENAI_API_KEY", None):
        try:
            from .ai_services import ai_notification_enhance
            context = {}
            if related_request:
                context["tracking_code"] = getattr(related_request, "tracking_code", "")
            subject, body = ai_notification_enhance(subject, body, context)
        except Exception:
            pass

    tracking_code = getattr(related_request, "tracking_code", "")

    if deliver_email:
        try:
            from .tasks import send_notification_email_task

            send_notification_email_task.delay(subject=subject, recipient=recipient, body=body, tracking_code=tracking_code)
        except Exception:
            logger.exception("Failed to queue notification email for recipient=%s", recipient)

    from .models import Notification
    from .websocket_utils import send_notification_websocket

    notification = Notification.objects.create(
        recipient_email=recipient,
        subject=subject,
        body=body,
        related_request=related_request,
    )

    payload = {
        "id": notification.id,
        "subject": notification.subject,
        "body": notification.body,
        "created_at": notification.created_at.isoformat(),
        "created_at_display": notification.created_at.strftime("%b %d, %H:%M"),
        "request_id": related_request.id if related_request else None,
        "tracking_code": related_request.tracking_code if related_request else None,
    }

    recipient_user = _resolve_notification_recipient_user(recipient, related_request=related_request)
    if recipient_user:
        send_notification_websocket(recipient_user.id, payload)

    if related_request:
        _notify_subscribers(
            related_request, payload, subscription_type="request_updates",
            exclude_user_id=related_request.user_id,
        )

    # ── Push notification ──────────────────────────────────────────────────────
    if deliver_push and recipient_user and recipient_user.id:
        _dispatch_push(
            user_id=recipient_user.id,
            push_type=push_type,
            fallback_title=subject,
            fallback_body=body,
            related_request=related_request,
            notification_id=notification.id,
        )

    return notification


def _dispatch_push(*, user_id: int, push_type: str | None, fallback_title: str, fallback_body: str, related_request=None, notification_id: int | None = None):
    """Fire the Celery push task. Never raises — push failures must not break the request cycle."""
    try:
        from account.tasks import send_push_notification_task
        from account.push_notifications import REGISTRY

        if push_type and push_type in REGISTRY:
            tpl = REGISTRY[push_type]
            kwargs = {}
            if related_request:
                kwargs["tracking_code"] = getattr(related_request, "tracking_code", "")
            title, body = tpl.render(**kwargs)
            priority = tpl.priority.value
        else:
            title = fallback_title
            body = fallback_body[:200]
            priority = "medium"

        data = {"type": push_type or "notification", "priority": priority}
        if notification_id:
            data["notification_id"] = str(notification_id)
        if related_request:
            data["request_id"] = str(related_request.id)

        send_push_notification_task.delay(user_id=user_id, title=title, body=body, data=data)
    except Exception:
        logger.exception("Push dispatch failed for user_id=%s push_type=%s", user_id, push_type)


def _notify_subscribers(related_request, notification_payload, subscription_type="request_updates", exclude_user_id=None):
    """Send WebSocket notification to active subscribers of a request."""
    try:
        from .models import Subscription
        from .websocket_utils import send_notification_websocket
        qs = Subscription.objects.filter(is_active=True, subscription_type=subscription_type)
        if subscription_type == "request_updates":
            qs = qs.filter(request=related_request)
        else:
            qs = qs.filter(request__isnull=True) | qs.filter(request=related_request)
        if exclude_user_id:
            qs = qs.exclude(user_id=exclude_user_id)
        for sub in qs.distinct():
            if sub.user_id:
                send_notification_websocket(sub.user_id, notification_payload)
                # Push for subscribers (#12 / #13)
                _dispatch_push(
                    user_id=sub.user_id,
                    push_type="subscription_update" if subscription_type == "request_updates" else "deal_alert",
                    fallback_title=notification_payload.get("subject", "New update"),
                    fallback_body=notification_payload.get("body", ""),
                    notification_id=notification_payload.get("id"),
                )
    except Exception:
        logger.exception("Subscriber notification failed for request_id=%s", getattr(related_request, "id", None))
