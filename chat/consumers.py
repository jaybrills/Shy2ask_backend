import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string

from .message_service import create_message_for_request, resolve_display_name
from .models import Message, ShyRequest, Notification


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time chat messages."""

    async def connect(self):
        # Get request_id from URL route
        url_route = self.scope.get("url_route", {})
        kwargs = url_route.get("kwargs", {})
        self.request_id = kwargs.get("request_id")
        
        if not self.request_id:
            await self.close()
            return
            
        self.user = self.scope["user"]
        self.room_group_name = f"chat_{self.request_id}"

        # Get tracking code from query string (for responder access)
        query_string = self.scope.get("query_string", b"").decode()
        self.tracking_code = None
        self.is_target = False
        
        if query_string:
            import urllib.parse
            params = urllib.parse.parse_qs(query_string)
            self.tracking_code = params.get("tracking_code", [None])[0]

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
            # Authenticated: owner -> requester; target -> target
            if self.user.id in {request.user_id, request.requester_user_id}:
                self.is_target = False
            elif self.user.id == request.target_user_id:
                self.is_target = True
            elif request.target_email and self.user.email.lower() == request.target_email.lower():
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
        """Receive message from WebSocket. Accept { body, alias } – alias is display name for this request/conversation."""
        try:
            data = json.loads(text_data)
            body = None
            alias = (data.get("alias") or "").strip() or None

            if "body" in data:
                body = str(data["body"]).strip()
            if not body:
                for key, value in data.items():
                    if key not in ("HEADERS", "alias") and isinstance(value, str) and value.strip():
                        body = value.strip()
                        break
            if not body:
                message_type = data.get("type")
                if message_type == "chat_message":
                    body = data.get("body", "").strip()

            if body:
                message_data = await self.create_message(body, self.user, alias=alias)
                if message_data:
                    print(f"Message created successfully: ID={message_data.get('id')}")
                    # Send message to room group
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            "type": "chat_message",
                            "message": message_data
                        }
                    )
                else:
                    print("ERROR: Failed to create message in database")
            else:
                print(f"WARNING: No body found in data. Full data: {data}")

        except json.JSONDecodeError as e:
            print(f"ERROR: JSON decode error: {e}")
            print(f"Raw text_data (first 200 chars): {text_data[:200]}")
        except Exception as e:
            print(f"ERROR in receive: {e}")
            import traceback
            traceback.print_exc()

    async def chat_message(self, event):
        """Receive message from room group."""
        message = event["message"]
        # Render HTML message for HTMX
        html_message = await self.render_message_html(message)
        # Send HTML message with hx-swap-oob for HTMX
        await self.send(text_data=html_message)

    async def send_recent_messages(self):
        """Send recent messages to the client."""
        messages = await self.get_recent_messages()
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
            messages = Message.objects.filter(request=request).visible_to(viewer_role).select_related(
                "author",
                "request",
                "sender_user",
                "recipient_user",
            ).order_by("-created_at")[:50]
            out = []
            for msg in reversed(messages):
                display_name = resolve_display_name(msg)
                out.append({
                    "id": msg.id,
                    "body": msg.clean_body or msg.body,
                    "sender": msg.sender,
                    "sender_display": msg.get_sender_display(),
                    "display_name": display_name,
                    "is_blocked": msg.is_blocked,
                    "created_at": msg.created_at.isoformat(),
                    "created_at_display": msg.created_at.strftime("%b %d, %H:%M"),
                })
            return out
        except Exception as e:
            print(f"Error getting recent messages: {e}")
            return []

    @database_sync_to_async
    def create_message(self, body, user, alias=None):
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
                )
            except Exception:
                return None

            return {
                "id": message.id,
                "body": message.clean_body or message.body,
                "sender": message.sender,
                "sender_display": message.get_sender_display(),
                "display_name": resolve_display_name(message),
                "is_blocked": message.is_blocked,
                "created_at": message.created_at.isoformat(),
                "created_at_display": message.created_at.strftime("%b %d, %H:%M"),
            }
        except Exception as e:
            print(f"Error creating message: {e}")
            import traceback
            traceback.print_exc()
            return None

    @database_sync_to_async
    def render_message_html(self, message):
        """Render message as HTML for HTMX; include display_name (alias or profile default)."""
        is_requester = message.get("sender") == "requester"
        return render_to_string(
            "chat/message_fragment.html",
            {
                "message_id": message.get("id"),
                "message_body": message.get("body", ""),
                "display_name": message.get("display_name", ""),
                "is_requester": is_requester,
                "is_blocked": message.get("is_blocked", False),
                "created_at_display": message.get("created_at_display", ""),
            }
        )
    
class NotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time notifications."""

    async def connect(self):
        self.user = self.scope["user"]
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
            # Get notifications for user's requests
            user_requests = ShyRequest.objects.filter(user=self.user)
            notifications = Notification.objects.filter(
                related_request__in=user_requests,
                is_read=False
            ).order_by("-created_at")[:20]

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
            notification = Notification.objects.get(
                pk=notification_id,
                related_request__user=self.user
            )
            notification.is_read = True
            notification.save()
        except Notification.DoesNotExist:
            pass
        except Exception as e:
            print(f"Error marking notification read: {e}")
