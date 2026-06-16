import asyncio

from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from rest_framework.authtoken.models import Token

from account.models import User
from chat.models import Message, Notification, ShyRequest
from chat.views import send_notification
from chat.websocket_utils import send_received_request_inbox_websocket


TEST_CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}


@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
class WebsocketConsumerTests(TransactionTestCase):
    def setUp(self):
        self.requester = User.objects.create_user(
            email="ws-requester@shy2ask.com",
            password="password123",
            is_email_verified=True,
            is_phone_verified=True,
        )
        self.target = User.objects.create_user(
            email="ws-target@shy2ask.com",
            password="password123",
            is_email_verified=True,
            is_phone_verified=True,
        )
        self.requester_token, _ = Token.objects.get_or_create(user=self.requester)
        self.target_token, _ = Token.objects.get_or_create(user=self.target)
        self.shy_request = ShyRequest.objects.create(
            user=self.requester,
            requester_user=self.requester,
            requester_name="Requester WS",
            requester_email=self.requester.email,
            requester_alias="RequesterAlias",
            target_user=self.target,
            target_name="Target WS",
            target_email=self.target.email,
            description="Initial websocket request",
            status=ShyRequest.Status.SUBMITTED,
        )

    async def _connect(self, path):
        from shy2ask.asgi import application

        communicator = WebsocketCommunicator(application, path)
        connected, _ = await communicator.connect()
        self.assertTrue(connected, msg=f"Expected websocket connection to succeed for {path}")
        return communicator

    def test_chat_websocket_tracking_code_client_can_send_and_receive_json_messages(self):
        async def scenario():
            communicator = await self._connect(
                f"/ws/chat/{self.shy_request.id}/?format=json&tracking_code={self.shy_request.tracking_code}"
            )
            try:
                history = await communicator.receive_json_from(timeout=5)
                self.assertEqual(history["type"], "chat.history")
                self.assertEqual(history["viewer"]["role"], Message.Actor.TARGET)
                self.assertEqual(history["request"]["id"], self.shy_request.id)
                self.assertEqual(len(history["messages"]), 1)

                await communicator.send_json_to(
                    {
                        "type": "chat.message",
                        "body": "Reply from target websocket",
                    }
                )
                event = await communicator.receive_json_from(timeout=5)
                self.assertEqual(event["type"], "chat.message")
                self.assertEqual(event["message"]["sender"], Message.Actor.TARGET)
                self.assertEqual(event["message"]["recipient"], Message.Actor.REQUESTER)
                self.assertEqual(event["message"]["clean_body"], "Reply from target websocket")
            finally:
                await communicator.disconnect()

        async_to_sync(scenario)()

        self.assertTrue(
            Message.objects.filter(
                request=self.shy_request,
                clean_body="Reply from target websocket",
                sender=Message.Actor.TARGET,
            ).exists()
        )

    def test_chat_websocket_can_broadcast_participant_read_cursor_updates(self):
        async def scenario():
            requester_ws = await self._connect(f"/ws/chat/{self.shy_request.id}/?format=json&token={self.requester_token.key}")
            target_ws = await self._connect(
                f"/ws/chat/{self.shy_request.id}/?format=json&tracking_code={self.shy_request.tracking_code}"
            )
            try:
                requester_history = await requester_ws.receive_json_from(timeout=5)
                target_history = await target_ws.receive_json_from(timeout=5)
                self.assertEqual(requester_history["type"], "chat.history")
                self.assertEqual(target_history["type"], "chat.history")

                latest_message_id = target_history["messages"][-1]["id"]
                await target_ws.send_json_to(
                    {
                        "type": "chat.read",
                        "last_read_message_id": latest_message_id,
                    }
                )

                requester_event = await requester_ws.receive_json_from(timeout=5)
                target_event = await target_ws.receive_json_from(timeout=5)
                events = sorted([requester_event, target_event], key=lambda item: item["read"]["is_me"])
                self.assertEqual(events[0]["type"], "chat.read")
                self.assertEqual(events[1]["type"], "chat.read")
                self.assertEqual(events[0]["read"]["actor_role"], Message.Actor.TARGET)
                self.assertEqual(events[0]["read"]["last_read_message_id"], latest_message_id)
                self.assertFalse(events[0]["read"]["is_me"])
                self.assertTrue(events[1]["read"]["is_me"])
            finally:
                await requester_ws.disconnect()
                await target_ws.disconnect()

        async_to_sync(scenario)()

    def test_notification_websocket_uses_notification_recipient_for_initial_and_live_events(self):
        owner_notification = Notification.objects.create(
            recipient_user=self.requester,
            recipient_email=self.requester.email,
            subject="Requester unread",
            body="Unread for requester",
            related_request=self.shy_request,
        )
        target_notification = Notification.objects.create(
            recipient_user=self.target,
            recipient_email=self.target.email,
            subject="Target unread",
            body="Unread for target",
            related_request=self.shy_request,
        )

        async def scenario():
            requester_ws = await self._connect(f"/ws/notifications/?token={self.requester_token.key}")
            target_ws = await self._connect(f"/ws/notifications/?token={self.target_token.key}")
            try:
                requester_initial = await requester_ws.receive_json_from(timeout=5)
                target_initial = await target_ws.receive_json_from(timeout=5)

                self.assertEqual(requester_initial["type"], "unread_notifications")
                self.assertEqual(target_initial["type"], "unread_notifications")
                self.assertEqual([item["subject"] for item in requester_initial["notifications"]], [owner_notification.subject])
                self.assertEqual([item["subject"] for item in target_initial["notifications"]], [target_notification.subject])

                await target_ws.send_json_to(
                    {
                        "type": "mark_read",
                        "notification_id": target_notification.id,
                    }
                )
                for _ in range(10):
                    await asyncio.sleep(0.05)
                    await sync_to_async(target_notification.refresh_from_db)()
                    if target_notification.is_read:
                        break
                self.assertTrue(target_notification.is_read)

                await sync_to_async(send_notification)(
                    subject="Live target notification",
                    body="This should reach only the target websocket",
                    recipient=self.target.email,
                    related_request=self.shy_request,
                    use_ai_enhance=False,
                    deliver_email=False,
                    deliver_push=False,
                )

                target_live = await target_ws.receive_json_from(timeout=5)
                self.assertEqual(target_live["type"], "notification")
                self.assertEqual(target_live["notification"]["subject"], "Live target notification")
                self.assertTrue(await requester_ws.receive_nothing(timeout=0.5))
            finally:
                await requester_ws.disconnect()
                await target_ws.disconnect()

        async_to_sync(scenario)()

    def test_request_inbox_websocket_sends_snapshot_and_refresh_events(self):
        async def scenario():
            communicator = await self._connect(f"/ws/requests/inbox/?token={self.target_token.key}")
            try:
                snapshot = await communicator.receive_json_from(timeout=5)
                self.assertEqual(snapshot["type"], "request_inbox.snapshot")
                self.assertEqual(snapshot["stats"]["received_requests_count"], 1)
                self.assertEqual(snapshot["recent_requests"][0]["id"], self.shy_request.id)
                self.assertEqual(snapshot["recent_requests"][0]["direction"], "received")
                self.assertEqual(snapshot["recent_requests"][0]["unread_count"], 1)
                self.assertIsNotNone(snapshot["recent_requests"][0]["latest_message"])
                self.assertEqual(
                    snapshot["recent_requests"][0]["last_message"]["id"],
                    snapshot["recent_requests"][0]["latest_message"]["id"],
                )

                await sync_to_async(send_received_request_inbox_websocket)(self.target.id)
                updated = await communicator.receive_json_from(timeout=5)
                self.assertEqual(updated["type"], "request_inbox.updated")
                self.assertEqual(updated["recent_requests"][0]["id"], self.shy_request.id)
            finally:
                await communicator.disconnect()

        async_to_sync(scenario)()
