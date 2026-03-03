from django.conf import settings
from django.core.mail import send_mail


def send_notification(subject, body, recipient, related_request=None, use_ai_enhance=True):
    """Send email notification and create notification record. AI makes subject/body short and engaging when OPENAI_API_KEY set."""
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
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [recipient],
        fail_silently=True,
    )
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
    if related_request and related_request.user:
        send_notification_websocket(related_request.user.id, payload)
    if related_request:
        _notify_subscribers(
            related_request, payload, subscription_type="request_updates",
            exclude_user_id=related_request.user_id,
        )
    return notification


def _notify_subscribers(related_request, notification_payload, subscription_type="request_updates", exclude_user_id=None):
    """Send WebSocket notification to active subscribers (owner already gets one, so exclude_user_id=request.user_id)."""
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
    except Exception:
        pass
