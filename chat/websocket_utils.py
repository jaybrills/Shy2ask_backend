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


def _normalize_email(email: str) -> str:
    if not email:
        return ""
    return get_user_model().objects.normalize_email(email).lower()


def actor_label(actor_role: str | None) -> str:
    mapping = {
        "requester": "Requester",
        "target": "Target",
        "staff": "Staff",
        "system": "System",
    }
    return mapping.get(actor_role, (actor_role or "").title() or "Unknown")


def viewer_role_for_request(shy_request, user) -> str | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None

    user_email = _normalize_email(getattr(user, "email", ""))
    if user.id in {shy_request.user_id, shy_request.requester_user_id}:
        return "requester"
    if user_email and user_email == _normalize_email(getattr(shy_request, "requester_email", "")):
        return "requester"
    if user.id == shy_request.target_user_id:
        return "target"
    if user_email and user_email == _normalize_email(getattr(shy_request, "target_email", "")):
        return "target"
    return None


def request_direction_for_user(shy_request, user) -> str | None:
    viewer_role = viewer_role_for_request(shy_request, user)
    if viewer_role == "requester":
        return "sent"
    if viewer_role == "target":
        return "received"
    return None


def decorate_message_for_viewer(message, viewer_role: str | None):
    message = dict(message)
    sender_role = message.get("sender")
    recipient_role = message.get("recipient")
    message["direction"] = "outbound" if viewer_role and sender_role == viewer_role else "inbound"
    message["is_mine"] = bool(viewer_role and sender_role == viewer_role)
    message["sender_role"] = sender_role
    message["recipient_role"] = recipient_role
    message["sender_label"] = actor_label(sender_role)
    message["recipient_label"] = actor_label(recipient_role)
    return message


def build_request_read_state(shy_request):
    return {
        "requester_last_read_message_id": shy_request.requester_last_read_message_id,
        "requester_last_read_at": shy_request.requester_last_read_at.isoformat() if shy_request.requester_last_read_at else None,
        "target_last_read_message_id": shy_request.target_last_read_message_id,
        "target_last_read_at": shy_request.target_last_read_at.isoformat() if shy_request.target_last_read_at else None,
    }


def unread_message_count_for_request(shy_request, viewer_role: str | None) -> int:
    if not viewer_role:
        return 0
    return shy_request.unread_messages_for_actor(viewer_role).count()


def mark_request_read_state(shy_request, viewer_role: str | None, *, last_read_message_id: int | None = None):
    from .models import Message

    if viewer_role not in {"requester", "target"}:
        return {
            "updated": False,
            "request_id": shy_request.id,
            "actor_role": viewer_role,
            "last_read_message_id": None,
            "unread_count": 0,
            **build_request_read_state(shy_request),
        }

    message_queryset = Message.objects.for_request(shy_request).visible_to(viewer_role)
    if last_read_message_id is None:
        target_message = message_queryset.order_by("-id").first()
    else:
        target_message = message_queryset.filter(id=last_read_message_id).first()
        if target_message is None:
            raise Message.DoesNotExist("Message not found in this request.")

    updated = shy_request.set_last_read_message_for_actor(viewer_role, target_message)
    shy_request.refresh_from_db(fields=[
        "requester_last_read_message",
        "requester_last_read_at",
        "target_last_read_message",
        "target_last_read_at",
    ])
    return {
        "updated": updated,
        "request_id": shy_request.id,
        "actor_role": viewer_role,
        "actor_label": actor_label(viewer_role),
        "last_read_message_id": shy_request.get_last_read_message_id_for_actor(viewer_role),
        "unread_count": unread_message_count_for_request(shy_request, viewer_role),
        **build_request_read_state(shy_request),
    }


def build_request_inbox_snapshot(user, *, limit: int = 20):
    """Return a role-aware inbox snapshot for requests connected to the user."""
    from .models import Message, ShyRequest

    if not user or not getattr(user, "is_authenticated", False):
        return {
            "viewer": {
                "id": None,
                "role": None,
                "label": "Guest",
            },
            "stats": {
                "total_requests_count": 0,
                "sent_requests_count": 0,
                "received_requests_count": 0,
                "pending_requests_count": 0,
                "cancelled_requests_count": 0,
                "rejected_requests_count": 0,
                "blocked_requests_count": 0,
            },
            "recent_requests": [],
        }

    user_email = _normalize_email(getattr(user, "email", ""))
    requester_filters = Q(user=user) | Q(requester_user=user)
    target_filters = Q(target_user=user)
    if user_email:
        requester_filters |= Q(requester_email__iexact=user_email)
        target_filters |= Q(target_email__iexact=user_email)

    queryset = ShyRequest.objects.with_related().filter(requester_filters | target_filters).distinct()
    stats = queryset.aggregate(
        total_requests_count=Count("id", distinct=True),
        sent_requests_count=Count("id", filter=requester_filters, distinct=True),
        received_requests_count=Count("id", filter=target_filters, distinct=True),
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

    recent_requests = list(
        queryset.annotate(
            latest_message_created_at=Subquery(
                Message.objects.filter(request=OuterRef("pk"))
                .order_by("-created_at")
                .values("created_at")[:1]
            ),
        )
        .order_by("-latest_message_created_at", "-updated_at", "-created_at")[:limit]
    )

    items = []
    for request in recent_requests:
        viewer_role = viewer_role_for_request(request, user)
        latest_message_obj = (
            Message.objects.filter(request=request)
            .visible_to(viewer_role)
            .select_related("parent_message")
            .order_by("-created_at")
            .first()
        )
        latest_message = None
        if latest_message_obj:
            latest_message = decorate_message_for_viewer(
                serialize_message_for_websocket(latest_message_obj),
                viewer_role,
            )

        direction = request_direction_for_user(request, user)
        items.append(
            {
                "id": request.id,
                "tracking_code": request.tracking_code,
                "status": request.status,
                "is_blocked": request.is_blocked,
                "direction": direction,
                "is_sent": direction == "sent",
                "is_received": direction == "received",
                "viewer_role": viewer_role,
                "viewer_label": actor_label(viewer_role),
                "requester_name": request.requester_display_name,
                "requester_email": request.requester_email,
                "target_name": request.target_display_name,
                "target_email": request.target_email,
                "counterparty_role": "target" if viewer_role == "requester" else "requester" if viewer_role == "target" else None,
                "counterparty_label": "Target" if viewer_role == "requester" else "Requester" if viewer_role == "target" else None,
                "counterparty_name": request.target_display_name if viewer_role == "requester" else request.requester_display_name if viewer_role == "target" else "",
                "counterparty_email": request.target_email if viewer_role == "requester" else request.requester_email if viewer_role == "target" else "",
                "unread_count": unread_message_count_for_request(request, viewer_role),
                "description": request.description,
                "created_at": request.created_at.isoformat() if request.created_at else None,
                "updated_at": request.updated_at.isoformat() if request.updated_at else None,
                "latest_message": latest_message,
                "last_message": latest_message,
            }
        )

    items.sort(
        key=lambda item: (
            1 if (item.get("latest_message") or {}).get("message_kind") == "reply" else 0,
            (item.get("latest_message") or {}).get("created_at")
            or item.get("updated_at")
            or item.get("created_at")
            or "",
        ),
        reverse=True,
    )

    return {
        "viewer": {
            "id": user.id,
            "role": "participant",
            "label": "Participant",
        },
        "requestCount": len(items),
        "stats": stats,
        "requests": items,
        "recent_requests": items,
    }


def get_request_inbox_user_ids(shy_request):
    """Return participant user IDs that should receive inbox refreshes for a request."""
    user_ids = set()
    if getattr(shy_request, "user_id", None):
        user_ids.add(shy_request.user_id)
    if getattr(shy_request, "requester_user_id", None):
        user_ids.add(shy_request.requester_user_id)
    if getattr(shy_request, "target_user_id", None):
        user_ids.add(shy_request.target_user_id)

    requester_email = (getattr(shy_request, "requester_email", "") or "").strip()
    if requester_email:
        matched_user_id = (
            get_user_model()
            .objects.filter(email__iexact=requester_email)
            .values_list("id", flat=True)
            .first()
        )
        if matched_user_id:
            user_ids.add(matched_user_id)

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


def build_received_request_inbox_snapshot(user, *, limit: int = 20):
    """Backward-compatible alias for the participant inbox snapshot."""
    return build_request_inbox_snapshot(user, limit=limit)


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


def send_chat_read_state_websocket(request_id, read_state_data):
    """Broadcast participant-level read cursor updates to connected chat clients."""
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"chat_{request_id}",
                {
                    "type": "chat_read_state",
                    "read": read_state_data,
                }
            )
            print(f"✓ WebSocket chat read state queued for request {request_id}")
        else:
            print(f"⚠ Channel layer not available for request {request_id}")
    except Exception as e:
        print(f"✗ Error sending WebSocket chat read state for request {request_id}: {e}")
        import traceback
        traceback.print_exc()
