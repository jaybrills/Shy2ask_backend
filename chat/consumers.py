import json
import urllib.parse
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from rest_framework.authtoken.models import Token

from .message_service import create_message_for_request
from .models import Message, ShyRequest, Notification
from .websocket_utils import (
    build_request_inbox_snapshot,
    decorate_message_for_viewer,
    send_received_request_inbox_websocket,
    serialize_message_for_websocket,
    unread_message_count_for_request,
    viewer_role_for_request,
)


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time chat messages.

    The default response format stays HTML for the existing HTMX chat page.
    API/mobile clients can connect with ``?format=json`` to receive JSON events.
    """

    async def connect(self):
        # Get request_id from URL route
        url_route = self.scope.get("url_route", {})
        kwargs = url_route.get("kwargs", {})
        self.request_id = kwargs.get("request_id")
        
        if not self.request_id:
            await self.close()
            return
            
        self.user = await self.get_authenticated_user()
        self.room_group_name = f"chat_{self.request_id}"

        # Get tracking code from query string (for responder access).
        self.query_params = self.get_query_params()
        self.tracking_code = None
        self.is_target = False
        self.response_format = (self.query_params.get("format", ["html"])[0] or "html").lower()
        self.response_format = "json" if self.response_format in {"json", "api"} else "html"
        self.tracking_code = self.query_params.get("tracking_code", [None])[0]

        request = await self.get_request(self.request_id)
        if not request:
            await self.close()
            return

        # Verify access: either authenticated requester OR target with tracking code
        if isinstance(self.user, AnonymousUser):
            # Check if target access via tracking code
            if self.tracking_code and self.tracking_code == request.tracking_code:
                self.is_target = True
            else:
                await self.close()
                return
        else:
            viewer_role = viewer_role_for_request(request, self.user)
            if viewer_role == Message.Actor.REQUESTER:
                self.is_target = False
            elif viewer_role == Message.Actor.TARGET:
                self.is_target = True
            else:
                await self.close()
                return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send recent messages to the newly connected client
        await self.send_recent_messages()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Receive message from WebSocket.

        Accepts {body, alias, reply_to_id}. HTMX clients may include extra form
        fields; JSON clients may send type="chat.message" or "chat_message".
        """
        try:
            data = json.loads(text_data)
            body = None
            alias = (data.get("alias") or "").strip() or None
            reply_to_id = data.get("reply_to_id")
            message_type = data.get("type")

            if message_type == "ping":
                await self.send_json_event({"type": "pong"})
                return

            if "body" in data:
                body = str(data["body"]).strip()
            if not body:
                for key, value in data.items():
                    if key not in ("HEADERS", "alias", "type") and isinstance(value, str) and value.strip():
                        body = value.strip()
                        break
            if not body:
                if message_type in {"chat_message", "chat.message"}:
                    body = data.get("body", "").strip()

            if body:
                message_data = await self.create_message(body, self.user, alias=alias, reply_to_id=reply_to_id)
                if message_data:
                    # Send message to room group
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            "type": "chat_message",
                            "message": message_data
                        }
                    )
                else:
                    await self.send_error("Unable to create message.")
            else:
                await self.send_error("Message body is required.")

        except json.JSONDecodeError as e:
            await self.send_error(f"Invalid JSON: {e.msg}")
        except Exception as e:
            print(f"ERROR in receive: {e}")
            import traceback
            traceback.print_exc()
            await self.send_error("Unexpected WebSocket error.")

    async def chat_message(self, event):
        """Receive message from room group."""
        message = self.with_viewer_fields(event["message"])
        if self.response_format == "json":
            await self.send_json_event({"type": "chat.message", "message": message})
            return

        # Render HTML message for HTMX
        html_message = await self.render_message_html(message)
        # Send HTML message with hx-swap-oob for HTMX
        await self.send(text_data=html_message)

    async def send_recent_messages(self):
        """Send recent messages to the client."""
        messages = await self.get_recent_messages()
        if self.response_format == "json":
            request_data = await self.get_request_summary()
            await self.send_json_event({
                "type": "chat.history",
                "request": request_data,
                "viewer": {
                    "role": Message.Actor.TARGET if self.is_target else Message.Actor.REQUESTER,
                    "label": "Target" if self.is_target else "Requester",
                },
                "participants": {
                    "requester": request_data.get("requester"),
                    "target": request_data.get("target"),
                },
                "messages": [self.with_viewer_fields(message) for message in messages],
            })
            return

        # Render all messages as HTML for HTMX
        html_messages = []
        for msg in messages:
            html = await self.render_message_html(msg)
            html_messages.append(html)
        # Send all messages (HTMX will process them)
        if html_messages:
            await self.send(text_data="\n".join(html_messages))

    @database_sync_to_async
    def get_request(self, request_id):
        """Get request object."""
        try:
            return ShyRequest.objects.get(pk=request_id)
        except ShyRequest.DoesNotExist:
            return None

    @database_sync_to_async
    def get_recent_messages(self):
        """Get recent messages for this request; include display_name (alias or profile default)."""
        try:
            request = ShyRequest.objects.get(pk=self.request_id)
            viewer_role = Message.Actor.TARGET if self.is_target else Message.Actor.REQUESTER
            updated_count = Message.objects.filter(request=request).mark_read_for_actor(viewer_role)
            if updated_count and getattr(self.user, "is_authenticated", False):
                send_received_request_inbox_websocket(self.user.id)
            messages = Message.objects.filter(request=request).visible_to(viewer_role).select_related(
                "author",
                "request",
                "sender_user",
                "recipient_user",
            ).order_by("-created_at")[:50]
            out = []
            for msg in reversed(messages):
                out.append(serialize_message_for_websocket(msg))
            return out
        except Exception as e:
            print(f"Error getting recent messages: {e}")
            return []

    @database_sync_to_async
    def create_message(self, body, user, alias=None, reply_to_id=None):
        """Create a new message. alias = display name for this message (request-wise); else use profile/request default."""
        try:
            request = ShyRequest.objects.get(pk=self.request_id)
            try:
                message = create_message_for_request(
                    request,
                    body,
                    user=user,
                    tracking_code=self.tracking_code if self.is_target else None,
                    alias=alias,
                    reply_to_id=reply_to_id,
                )
            except Exception:
                return None

            return serialize_message_for_websocket(message)
        except Exception as e:
            print(f"Error creating message: {e}")
            import traceback
            traceback.print_exc()
            return None

    @database_sync_to_async
    def get_request_summary(self):
        request = ShyRequest.objects.get(pk=self.request_id)
        viewer_role = Message.Actor.TARGET if self.is_target else Message.Actor.REQUESTER
        return {
            "id": request.id,
            "tracking_code": request.tracking_code,
            "status": request.status,
            "unread_count": unread_message_count_for_request(request, viewer_role),
            "service_channel": request.service_channel,
            "description": request.description,
            "created_at": request.created_at.isoformat(),
            "requester": {
                "role": Message.Actor.REQUESTER,
                "label": "Requester",
                "name": request.requester_display_name,
                "email": request.requester_email,
                "is_me": not self.is_target,
            },
            "target": {
                "role": Message.Actor.TARGET,
                "label": "Target",
                "name": request.target_display_name,
                "email": request.target_email,
                "is_me": self.is_target,
            },
        }

    def get_query_params(self):
        query_string = self.scope.get("query_string", b"").decode()
        return urllib.parse.parse_qs(query_string)

    async def get_authenticated_user(self):
        user = self.scope["user"]
        if not isinstance(user, AnonymousUser):
            return user

        params = self.get_query_params()
        token_key = (params.get("token") or params.get("access_token") or [None])[0]
        if not token_key:
            headers = dict(self.scope.get("headers") or [])
            auth_header = headers.get(b"authorization", b"").decode()
            if auth_header.lower().startswith("bearer "):
                token_key = auth_header.split(" ", 1)[1].strip()
        if not token_key:
            return user
        return await self.get_user_by_token(token_key) or user

    @database_sync_to_async
    def get_user_by_token(self, token_key):
        token = Token.objects.select_related("user").filter(key=token_key).first()
        return token.user if token else None

    def with_viewer_fields(self, message):
        viewer_role = Message.Actor.TARGET if self.is_target else Message.Actor.REQUESTER
        return decorate_message_for_viewer(message, viewer_role)

    async def send_json_event(self, payload):
        if self.response_format == "json":
            await self.send(text_data=json.dumps(payload))

    async def send_error(self, detail):
        if self.response_format == "json":
            await self.send_json_event({"type": "error", "detail": detail})

    @database_sync_to_async
    def render_message_html(self, message):
        """Render message as HTML for HTMX; include display_name (alias or profile default)."""
        is_requester = message.get("sender") == "requester"
        return render_to_string(
            "chat/message_fragment.html",
            {
                "message_id": message.get("id"),
                "message_body": message.get("clean_body") or message.get("body", ""),
                "display_name": message.get("display_name", ""),
                "is_requester": is_requester,
                "is_blocked": message.get("is_blocked", False),
                "created_at_display": message.get("created_at_display", ""),
            }
        )
    
class NotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time notifications."""

    async def connect(self):
        self.user = await self.get_authenticated_user()
        self.user_id = self.user.id if not isinstance(self.user, AnonymousUser) else None

        if isinstance(self.user, AnonymousUser):
            await self.close()
            return

        self.room_group_name = f"notifications_{self.user_id}"

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send unread notifications
        await self.send_unread_notifications()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            message_type = data.get("type")

            if message_type == "mark_read":
                notification_id = data.get("notification_id")
                await self.mark_notification_read(notification_id)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"Error in notification receive: {e}")

    async def notification_message(self, event):
        """Receive notification from room group."""
        notification = event["notification"]
        # Send notification to WebSocket
        await self.send(text_data=json.dumps({
            "type": "notification",
            "notification": notification
        }))

    async def send_unread_notifications(self):
        """Send unread notifications to the client."""
        notifications = await self.get_unread_notifications()
        await self.send(text_data=json.dumps({
            "type": "unread_notifications",
            "notifications": notifications
        }))

    @database_sync_to_async
    def get_unread_notifications(self):
        """Get unread notifications for the user."""
        try:
            notifications = (
                Notification.objects.unread()
                .for_recipient(user=self.user)
                .select_related("related_request")
                .order_by("-created_at")[:20]
            )

            return [
                {
                    "id": notif.id,
                    "subject": notif.subject,
                    "body": notif.body,
                    "created_at": notif.created_at.isoformat(),
                    "created_at_display": notif.created_at.strftime("%b %d, %H:%M"),
                    "request_id": notif.related_request.id if notif.related_request else None,
                    "tracking_code": notif.related_request.tracking_code if notif.related_request else None,
                }
                for notif in notifications
            ]
        except Exception as e:
            print(f"Error getting unread notifications: {e}")
            return []

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        """Mark a notification as read."""
        try:
            notification = Notification.objects.for_recipient(user=self.user).get(
                pk=notification_id
            )
            notification.is_read = True
            notification.save()
        except Notification.DoesNotExist:
            pass
        except Exception as e:
            print(f"Error marking notification read: {e}")

    def get_query_params(self):
        query_string = self.scope.get("query_string", b"").decode()
        return urllib.parse.parse_qs(query_string)

    async def get_authenticated_user(self):
        user = self.scope["user"]
        if not isinstance(user, AnonymousUser):
            return user

        params = self.get_query_params()
        token_key = (params.get("token") or params.get("access_token") or [None])[0]
        if not token_key:
            headers = dict(self.scope.get("headers") or [])
            auth_header = headers.get(b"authorization", b"").decode()
            if auth_header.lower().startswith("bearer "):
                token_key = auth_header.split(" ", 1)[1].strip()
        if not token_key:
            return user
        return await self.get_user_by_token(token_key) or user

    @database_sync_to_async
    def get_user_by_token(self, token_key):
        token = Token.objects.select_related("user").filter(key=token_key).first()
        return token.user if token else None


class RequestInboxConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for a user's received-request inbox snapshot."""

    async def connect(self):
        self.user = await self.get_authenticated_user()
        self.user_id = self.user.id if not isinstance(self.user, AnonymousUser) else None
        if isinstance(self.user, AnonymousUser):
            await self.close()
            return

        self.query_params = self.get_query_params()
        self.limit = self._parse_limit((self.query_params.get("limit") or [20])[0])
        self.room_group_name = f"request_inbox_{self.user_id}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()
        await self.send_snapshot(event_type="request_inbox.snapshot")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        message_type = data.get("type")
        if message_type == "ping":
            await self.send(text_data=json.dumps({"type": "pong"}))
            return
        if message_type == "request_inbox.refresh":
            await self.send_snapshot(event_type="request_inbox.snapshot")

    async def request_inbox_refresh(self, event):
        await self.send_snapshot(event_type=event.get("event_type", "request_inbox.updated"))

    async def send_snapshot(self, *, event_type: str):
        snapshot = await self.get_snapshot()
        await self.send(text_data=json.dumps({
            "type": event_type,
            **snapshot,
        }))

    @database_sync_to_async
    def get_snapshot(self):
        return build_request_inbox_snapshot(self.user, limit=self.limit)

    def _parse_limit(self, value):
        try:
            return max(1, min(int(value), 100))
        except (TypeError, ValueError):
            return 20

    def get_query_params(self):
        query_string = self.scope.get("query_string", b"").decode()
        return urllib.parse.parse_qs(query_string)

    async def get_authenticated_user(self):
        user = self.scope["user"]
        if not isinstance(user, AnonymousUser):
            return user

        params = self.get_query_params()
        token_key = (params.get("token") or params.get("access_token") or [None])[0]
        if not token_key:
            headers = dict(self.scope.get("headers") or [])
            auth_header = headers.get(b"authorization", b"").decode()
            if auth_header.lower().startswith("bearer "):
                token_key = auth_header.split(" ", 1)[1].strip()
        if not token_key:
            return user
        return await self.get_user_by_token(token_key) or user

    @database_sync_to_async
    def get_user_by_token(self, token_key):
        token = Token.objects.select_related("user").filter(key=token_key).first()
        return token.user if token else None
