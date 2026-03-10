import threading
import sys

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError

from .models import Message, ShyRequest
from .utils import censor_text


class MessageAccessError(PermissionDenied):
    """Raised when a user/tracking code cannot access request conversation."""


def can_access_conversation(shy_request: ShyRequest, user=None, tracking_code: str | None = None) -> bool:
    """Requester (owner) or responder (tracking code) can access the conversation."""
    user = user if getattr(user, "is_authenticated", False) else None
    if user and shy_request.user_id == user.id:
        return True
    if user and shy_request.target_email and user.email.lower() == shy_request.target_email.lower():
        return True
    return bool(tracking_code and tracking_code == shy_request.tracking_code)


def _resolve_sender(shy_request: ShyRequest, user=None, tracking_code: str | None = None):
    user = user if getattr(user, "is_authenticated", False) else None
    if user and shy_request.user_id == user.id:
        return Message.Sender.REQUESTER, user
    if user and shy_request.target_email and user.email.lower() == shy_request.target_email.lower():
        return Message.Sender.RESPONDER, user
    if tracking_code and tracking_code == shy_request.tracking_code:
        return Message.Sender.RESPONDER, None
    raise MessageAccessError("You are not allowed to send messages for this request.")


def resolve_display_name(msg: Message) -> str:
    """Human-readable sender display name used by API responses/UI."""
    if msg.sender_display_name:
        return msg.sender_display_name

    req = msg.request
    if msg.sender == Message.Sender.REQUESTER and msg.author:
        return getattr(msg.author, "alias_name", None) or req.requester_alias or req.requester_name
    if msg.sender == Message.Sender.REQUESTER:
        return req.requester_alias or req.requester_name
    if msg.sender == Message.Sender.RESPONDER:
        return req.requester_alias or req.requester_name or "Responder"
    return "Staff"


def create_message_for_request(
    shy_request: ShyRequest,
    body: str,
    *,
    user=None,
    tracking_code: str | None = None,
    alias: str | None = None,
    run_async_business_logic: bool = True,
) -> Message:
    """Create message with shared business rules across REST/WebSocket flows."""
    sender, author = _resolve_sender(shy_request, user=user, tracking_code=tracking_code)

    alias_clean = (alias or "").strip()

    msg = Message(
        request=shy_request,
        sender=sender,
        author=author,
        sender_display_name=alias_clean,
        body=body,
    )
    # Enforce censoring at model level; will raise ValidationError if blocked.
    msg.full_clean()
    msg.save()

    if run_async_business_logic:
        _run_post_message_business_logic(shy_request=shy_request, sender=sender, body=body)

    return msg


def _run_post_message_business_logic(shy_request: ShyRequest, sender: str, body: str):
    """Notifications + AI deal detection after each message."""
    from .views import send_notification

    admin_email = getattr(settings, "ADMIN_NOTIFY_EMAIL", "")

    if sender == Message.Sender.RESPONDER:
        send_notification(
            subject="New reply from responder",
            body=f"Responder replied to your request {shy_request.tracking_code}",
            recipient=shy_request.requester_email,
            related_request=shy_request,
        )
        if admin_email:
            send_notification(
                subject="New reply from responder",
                body=body,
                recipient=admin_email,
                related_request=shy_request,
            )
    elif admin_email:
        send_notification(
            subject="New reply from requester",
            body=body,
            recipient=admin_email,
            related_request=shy_request,
        )

    def _deal_detection_job():
        try:
            from .ai_services import run_deal_detection_and_notify

            run_deal_detection_and_notify(shy_request.id)
        except Exception:
            pass

    # Keep tests deterministic and avoid dangling DB sessions from background threads.
    if "test" in sys.argv:
        _deal_detection_job()
        return

    threading.Thread(target=_deal_detection_job, daemon=True).start()
