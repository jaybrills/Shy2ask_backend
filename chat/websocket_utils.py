"""Utility functions for WebSocket notifications."""
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


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
