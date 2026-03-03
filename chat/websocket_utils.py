"""Utility functions for WebSocket notifications."""
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


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

