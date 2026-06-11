import logging

from django.conf import settings
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError

from .models import Message, ShyRequest
from .websocket_utils import viewer_role_for_request


logger = logging.getLogger(__name__)


class MessageAccessError(PermissionDenied):
    """Raised when a user/tracking code cannot access request conversation."""


def can_access_conversation(shy_request: ShyRequest, user=None, tracking_code: str | None = None) -> bool:
    """Requester (owner) or responder (tracking code) can access the conversation."""
    user = user if getattr(user, "is_authenticated", False) else None
    if user and viewer_role_for_request(shy_request, user):
        return True
    return bool(tracking_code and tracking_code == shy_request.tracking_code)


def _resolve_sender(shy_request: ShyRequest, user=None, tracking_code: str | None = None):
    user = user if getattr(user, "is_authenticated", False) else None
    viewer_role = viewer_role_for_request(shy_request, user) if user else None
    if viewer_role == Message.Actor.REQUESTER:
        return Message.Actor.REQUESTER, user
    if viewer_role == Message.Actor.TARGET:
        return Message.Actor.TARGET, user
    if tracking_code and tracking_code == shy_request.tracking_code:
        return Message.Actor.TARGET, None
    raise MessageAccessError("You are not allowed to send messages for this request.")


def resolve_display_name(msg: Message) -> str:
    """Human-readable sender display name used by API responses/UI."""
    if msg.sender_display_name:
        return msg.sender_display_name

    req = msg.request
    if msg.sender == Message.Actor.REQUESTER and msg.author:
        return getattr(msg.author, "alias_name", None) or req.requester_display_name
    if msg.sender == Message.Actor.REQUESTER:
        return req.requester_display_name
    if msg.sender == Message.Actor.TARGET:
        return req.target_display_name
    return "Staff"


def resolve_recipient_name(msg: Message) -> str:
    if msg.recipient_display_name:
        return msg.recipient_display_name

    req = msg.request
    if msg.recipient == Message.Actor.REQUESTER:
        return req.requester_display_name or "Requester"
    if msg.recipient == Message.Actor.TARGET:
        return req.target_display_name
    if msg.recipient == Message.Actor.STAFF:
        return "Staff"
    return "System"


def create_message_for_request(
    shy_request: ShyRequest,
    body: str,
    *,
    user=None,
    tracking_code: str | None = None,
    alias: str | None = None,
    reply_to_id: int | None = None,
    run_async_business_logic: bool = True,
) -> Message:
    """Create message with shared business rules across REST/WebSocket flows."""
    if shy_request.is_deleted:
        raise ValidationError("This request has been deleted.")
    if shy_request.is_blocked:
        raise ValidationError("This request has been blocked.")

    parent_message = None
    if reply_to_id:
        parent_message = Message.objects.filter(request=shy_request, pk=reply_to_id).first()
        if not parent_message:
            raise ValidationError("Reply target message was not found.")

    sender, author = _resolve_sender(shy_request, user=user, tracking_code=tracking_code)

    alias_clean = (alias or "").strip()
    if sender == Message.Actor.REQUESTER:
        recipient = Message.Actor.TARGET
        sender_user = shy_request.requester_identity or author
        recipient_user = shy_request.target_user
        sender_email = shy_request.requester_email
        recipient_email = shy_request.target_email
        sender_display_name = alias_clean or shy_request.requester_display_name
        recipient_display_name = shy_request.target_display_name
    else:
        recipient = Message.Actor.REQUESTER
        sender_user = shy_request.target_user or author
        recipient_user = shy_request.requester_identity
        sender_email = shy_request.target_email
        recipient_email = shy_request.requester_email
        sender_display_name = alias_clean or shy_request.target_display_name
        recipient_display_name = shy_request.requester_display_name

    msg = Message(
        request=shy_request,
        parent_message=parent_message,
        sender=sender,
        recipient=recipient,
        message_kind=Message.Kind.REPLY,
        author=author,
        sender_user=sender_user,
        recipient_user=recipient_user,
        sender_email=sender_email,
        recipient_email=recipient_email,
        sender_display_name=sender_display_name,
        recipient_display_name=recipient_display_name,
        body=body,
    )
    # Enforce censoring at model level; will raise ValidationError if blocked.
    msg.full_clean()
    msg.save()

    def refresh_request_inbox():
        try:
            from .websocket_utils import get_request_inbox_user_ids, send_received_request_inbox_websocket

            for user_id in get_request_inbox_user_ids(shy_request):
                send_received_request_inbox_websocket(user_id)
        except Exception:
            logger.exception("Failed request inbox websocket refresh for request %s", shy_request.id)

    transaction.on_commit(refresh_request_inbox)

    if run_async_business_logic:
        try:
            from .tasks import process_request_reply_side_effects_task

            transaction.on_commit(
                lambda: process_request_reply_side_effects_task.delay(shy_request.id, sender, body)
            )
        except Exception:
            pass

    return msg


def run_post_message_business_logic(shy_request: ShyRequest, sender: str, body: str):
    """Notifications + AI deal detection after each message."""
    from .views import send_notification
    from .emailing import send_request_reply_emails

    admin_email = getattr(settings, "ADMIN_NOTIFY_EMAIL", "")

    send_request_reply_emails(shy_request, sender, body)

    if sender == Message.Actor.TARGET:
        # Target replied → notify requester (#10 message_replied)
        send_notification(
            subject="New reply from target",
            body=f"Target replied to your request {shy_request.tracking_code}",
            recipient=shy_request.requester_email,
            related_request=shy_request,
            use_ai_enhance=False,
            deliver_email=False,
            push_type="message_replied",
        )
        # Delivery confirmation to sender — no push needed
        send_notification(
            subject="New message from target",
            body=f"Your reply on {shy_request.tracking_code} was delivered.",
            recipient=shy_request.target_email,
            related_request=shy_request,
            use_ai_enhance=False,
            deliver_email=False,
            deliver_push=False,
        )
        if admin_email:
            send_notification(
                subject="New reply from target",
                body=body,
                recipient=admin_email,
                related_request=shy_request,
            )
    else:
        if shy_request.target_email:
            # Requester sent message → notify target (#9 new_message)
            send_notification(
                subject="New reply from requester",
                body=f"Requester sent a new message on {shy_request.tracking_code}.",
                recipient=shy_request.target_email,
                related_request=shy_request,
                use_ai_enhance=False,
                deliver_email=False,
                push_type="new_message",
            )
        # Delivery confirmation to sender — no push needed
        send_notification(
            subject="New message from requester",
            body=f"Your reply on {shy_request.tracking_code} was delivered.",
            recipient=shy_request.requester_email,
            related_request=shy_request,
            use_ai_enhance=False,
            deliver_email=False,
            deliver_push=False,
        )
        if admin_email:
            send_notification(
                subject="New reply from requester",
                body=body,
                recipient=admin_email,
                related_request=shy_request,
            )
    try:
        from .tasks import run_deal_detection_and_notify_task

        run_deal_detection_and_notify_task.delay(shy_request.id)
    except Exception:
        pass
