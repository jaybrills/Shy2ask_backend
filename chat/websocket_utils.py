"""Utility functions for WebSocket notifications."""
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.db.models import Count, OuterRef, Q, Subquery


def serialize_message_for_websocket(message):
    """Return the JSON message shape used by REST-triggered and WS-triggered broadcasts."""
    from .message_service import resolve_display_name, resolve_recipient_name

    parent_body = None
    if getattr(message, "parent_message", None):
        parent_body = (message.parent_message.clean_body or message.parent_message.body or "")[:120]

    return {
        "id": message.id,
        "request_id": message.request_id,
        "reply_to_id": message.parent_message_id,
        "reply_to_body": parent_body,
        "message_kind": message.message_kind,
        "sender": message.sender,
        "recipient": message.recipient,
        "sender_display": message.get_sender_display(),
        "sender_display_name": message.sender_display_name,
        "recipient_display_name": message.recipient_display_name,
        "display_name": resolve_display_name(message),
        "recipient_name": resolve_recipient_name(message),
        "body": message.body,
        "clean_body": message.clean_body,
        "is_blocked": message.is_blocked,
        "created_at": message.created_at.isoformat(),
        "created_at_display": message.created_at.strftime("%b %d, %H:%M"),
    }


def build_received_request_inbox_snapshot(user, *, limit: int = 20):
    """Return recent received requests plus aggregate stats for a target user."""
    from .models import Message, ShyRequest

    if not user or not getattr(user, "is_authenticated", False):
        return {
            "stats": {
                "received_requests_count": 0,
                "pending_requests_count": 0,
                "cancelled_requests_count": 0,
                "rejected_requests_count": 0,
                "blocked_requests_count": 0,
            },
            "recent_requests": [],
        }

    request_filters = Q(target_user=user)
    if getattr(user, "email", ""):
        request_filters |= Q(target_email__iexact=user.email)

    queryset = ShyRequest.objects.with_related().filter(request_filters).distinct()
    stats = queryset.aggregate(
        received_requests_count=Count("id", distinct=True),
        pending_requests_count=Count(
            "id",
            filter=Q(status=ShyRequest.Status.SUBMITTED, is_blocked=False),
            distinct=True,
        ),
        cancelled_requests_count=Count(
            "id",
            filter=Q(status=ShyRequest.Status.REJECTED),
            distinct=True,
        ),
        blocked_requests_count=Count("id", filter=Q(is_blocked=True), distinct=True),
    )
    stats["rejected_requests_count"] = stats["cancelled_requests_count"]

    latest_message_id_subquery = (
        Message.objects.filter(request=OuterRef("pk"))
        .visible_to(Message.Actor.TARGET)
        .order_by("-created_at")
        .values("id")[:1]
    )
    latest_message_created_at_subquery = (
        Message.objects.filter(request=OuterRef("pk"))
        .visible_to(Message.Actor.TARGET)
        .order_by("-created_at")
        .values("created_at")[:1]
    )

    recent_requests = list(
        queryset.annotate(
            latest_message_id=Subquery(latest_message_id_subquery),
            latest_message_created_at=Subquery(latest_message_created_at_subquery),
        )
        .order_by("-latest_message_created_at", "-updated_at", "-created_at")[:limit]
    )

    latest_message_ids = [request.latest_message_id for request in recent_requests if request.latest_message_id]
    latest_messages = {
        message.id: message
        for message in Message.objects.filter(id__in=latest_message_ids).select_related("parent_message")
    }

    return {
        "stats": stats,
        "recent_requests": [
            {
                "id": request.id,
                "tracking_code": request.tracking_code,
                "status": request.status,
                "is_blocked": request.is_blocked,
                "requester_name": request.requester_display_name,
                "requester_email": request.requester_email,
                "target_name": request.target_display_name,
                "target_email": request.target_email,
                "description": request.description,
                "created_at": request.created_at.isoformat() if request.created_at else None,
                "updated_at": request.updated_at.isoformat() if request.updated_at else None,
                "latest_message": serialize_message_for_websocket(latest_messages[request.latest_message_id])
                if request.latest_message_id in latest_messages
                else None,
            }
            for request in recent_requests
        ],
    }


def get_request_inbox_user_ids(shy_request):
    """Return user IDs that should receive inbox refreshes for a request."""
    user_ids = set()
    if getattr(shy_request, "target_user_id", None):
        user_ids.add(shy_request.target_user_id)

    target_email = (getattr(shy_request, "target_email", "") or "").strip()
    if target_email:
        matched_user_id = (
            get_user_model()
            .objects.filter(email__iexact=target_email)
            .values_list("id", flat=True)
            .first()
        )
        if matched_user_id:
            user_ids.add(matched_user_id)
    return user_ids


def send_notification_websocket(user_id, notification_data):
    """Send notification via WebSocket to a specific user."""
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"notifications_{user_id}",
                {
                    "type": "notification_message",
                    "notification": notification_data,
                }
            )
            print(f"✓ WebSocket notification queued for user {user_id}")
        else:
            print(f"⚠ Channel layer not available for user {user_id}")
    except Exception as e:
        print(f"✗ Error sending WebSocket notification to user {user_id}: {e}")
        import traceback
        traceback.print_exc()


def send_received_request_inbox_websocket(user_id):
    """Ask all connected request inbox clients for a user to refresh."""
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"request_inbox_{user_id}",
                {
                    "type": "request_inbox_refresh",
                }
            )
            print(f"✓ WebSocket request inbox refresh queued for user {user_id}")
        else:
            print(f"⚠ Channel layer not available for request inbox user {user_id}")
    except Exception as e:
        print(f"✗ Error sending request inbox refresh to user {user_id}: {e}")
        import traceback
        traceback.print_exc()


def send_chat_message_websocket(request_id, message_data):
    """Send chat message via WebSocket to all connected clients in a chat room."""
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"chat_{request_id}",
                {
                    "type": "chat_message",
                    "message": message_data,
                }
            )
            print(f"✓ WebSocket chat message queued for request {request_id}")
        else:
            print(f"⚠ Channel layer not available for request {request_id}")
    except Exception as e:
        print(f"✗ Error sending WebSocket chat message for request {request_id}: {e}")
        import traceback
        traceback.print_exc()
