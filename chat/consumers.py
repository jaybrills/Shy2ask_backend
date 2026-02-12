import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from django.template.loader import render_to_string

from .models import Conversation, Message, ShyRequest, Notification


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
        self.is_responder = False
        
        if query_string:
            import urllib.parse
            params = urllib.parse.parse_qs(query_string)
            self.tracking_code = params.get("tracking_code", [None])[0]

        request = await self.get_request(self.request_id)
        if not request:
            await self.close()
            return

        # Verify access: either authenticated requester OR responder with tracking code
        if isinstance(self.user, AnonymousUser):
            # Check if responder access via tracking code
            if self.tracking_code and self.tracking_code == request.tracking_code:
                self.is_responder = True
            else:
                await self.close()
                return
        else:
            # Authenticated user - must be the requester
            if request.user != self.user:
                await self.close()
                return
            self.is_responder = False

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
                    
                    # Send notifications (now in async context, safe to use await)
                    notification_info = message_data.pop("notification_info", None)
                    if notification_info:
                        await self.send_notifications_for_message(notification_info)
                    # AI deal detection (fire-and-forget): detect deal from conversation, create Deal, notify subscribers
                    try:
                        import asyncio
                        from .ai_services import run_deal_detection_and_notify
                        asyncio.get_event_loop().run_in_executor(
                            None, run_deal_detection_and_notify, self.request_id
                        )
                    except Exception:
                        pass
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
        """Get recent messages for the conversation; include display_name (alias or profile default)."""
        try:
            request = ShyRequest.objects.get(pk=self.request_id)
            conversation, _ = Conversation.objects.get_or_create(request=request)
            messages = conversation.messages.order_by("-created_at")[:50]
            out = []
            for msg in reversed(messages):
                display_name = msg.sender_display_name or self._message_display_name(msg, request)
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

    def _message_display_name(self, msg, request):
        """Resolve display name for a message (request alias or profile default)."""
        if msg.sender == Message.Sender.REQUESTER:
            if msg.author:
                return getattr(msg.author, "alias_name", None) or request.requester_alias or request.requester_name
            return request.requester_alias or request.requester_name
        if msg.sender == Message.Sender.RESPONDER:
            return request.requester_alias or request.requester_name or "Responder"
        return "Staff"

    @database_sync_to_async
    def create_message(self, body, user, alias=None):
        """Create a new message. alias = display name for this message (request-wise); else use profile/request default."""
        try:
            from .utils import censor_text

            request = ShyRequest.objects.get(pk=self.request_id)
            conversation, _ = Conversation.objects.get_or_create(request=request)

            clean_body, blocked = censor_text(body)

            if self.is_responder:
                sender = Message.Sender.RESPONDER
                author = None
            else:
                sender = Message.Sender.REQUESTER
                author = user

            display_name = (alias or "").strip()
            if not display_name and sender == Message.Sender.REQUESTER and author:
                display_name = getattr(author, "alias_name", "") or request.requester_alias or request.requester_name
            if not display_name and sender == Message.Sender.REQUESTER:
                display_name = request.requester_alias or request.requester_name
            if not display_name and sender == Message.Sender.RESPONDER:
                display_name = request.requester_alias or request.requester_name or "Responder"
            if not display_name:
                display_name = "Staff"

            message = Message.objects.create(
                conversation=conversation,
                sender=sender,
                author=author,
                sender_display_name=display_name if (alias or "").strip() else "",  # store only if client set alias
                body=body,
                clean_body=clean_body,
                is_blocked=blocked,
            )
            # Use resolved display_name for response (in case we computed it)
            out_display = (alias or "").strip() or display_name

            notification_info = {
                "is_responder": self.is_responder,
                "request": request,
                "body": body,
            }

            return {
                "id": message.id,
                "body": message.clean_body or message.body,
                "sender": message.sender,
                "sender_display": message.get_sender_display(),
                "display_name": out_display,
                "is_blocked": message.is_blocked,
                "created_at": message.created_at.isoformat(),
                "created_at_display": message.created_at.strftime("%b %d, %H:%M"),
                "notification_info": notification_info,
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
    
    async def send_notifications_for_message(self, notification_info):
        """Send notifications for a newly created message (async context)."""
        try:
            from django.conf import settings
            is_responder = notification_info["is_responder"]
            request = notification_info["request"]
            body = notification_info["body"]
            
            if is_responder:
                # Notify requester and admin
                await self.send_notification_async(
                    subject="New reply from responder",
                    body=f"Responder replied to your request {request.tracking_code}",
                    recipient=request.requester_email,
                    related_request=request,
                )
                await self.send_notification_async(
                    subject="New reply from responder",
                    body=body,
                    recipient=settings.ADMIN_NOTIFY_EMAIL,
                    related_request=request,
                )
            else:
                # Notify admin
                await self.send_notification_async(
                    subject="New reply from requester",
                    body=body,
                    recipient=settings.ADMIN_NOTIFY_EMAIL,
                    related_request=request,
                )
        except Exception as e:
            print(f"Error sending notifications: {e}")
            import traceback
            traceback.print_exc()
    
    @sync_to_async
    def send_notification_async(self, subject, body, recipient, related_request):
        """Async wrapper for send_notification."""
        from .views import send_notification
        send_notification(subject, body, recipient, related_request)


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

