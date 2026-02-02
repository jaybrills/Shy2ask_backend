from django.conf import settings
from django.core.mail import send_mail


def send_notification(subject, body, recipient, related_request=None):
    """Send email notification and create notification record."""
    if not recipient:
        return
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

    if related_request and related_request.user:
        send_notification_websocket(
            related_request.user.id,
            {
                "id": notification.id,
                "subject": notification.subject,
                "body": notification.body,
                "created_at": notification.created_at.isoformat(),
                "created_at_display": notification.created_at.strftime("%b %d, %H:%M"),
                "request_id": related_request.id if related_request else None,
                "tracking_code": related_request.tracking_code if related_request else None,
            }
        )
