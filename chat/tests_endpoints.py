import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from account.models import User
from account.emailing import build_email_context
from chat.models import Message, Notification, ShyRequest, Subscription


class ChatEndpointCoverageTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="requester@valid.com",
            password="password123",
            alias_name="RequesterAlias",
            is_email_verified=True,
            is_phone_verified=True,
        )
        self.target = User.objects.create_user(
            email="target@valid.com",
            password="password123",
            is_email_verified=True,
            is_phone_verified=True,
        )
        self.owner_token, _ = Token.objects.get_or_create(user=self.owner)
        self.target_token, _ = Token.objects.get_or_create(user=self.target)
        self.request = ShyRequest.objects.create(
            user=self.owner,
            requester_user=self.owner,
            requester_name="Requester Name",
            requester_email=self.owner.email,
            requester_alias="RequesterAlias",
            target_name="Target Name",
            target_email=self.target.email,
            description="Need help with this request",
            status=ShyRequest.Status.SUBMITTED,
        )

    def auth_headers(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token.key}"}

    def test_requests_create_list_and_retrieve(self):
        create_response = self.client.post(
            "/api/requests/",
            {
                "requester_name": "Another Requester",
                "requester_email": self.owner.email,
                "target_name": "Unregistered Target",
                "target_email": "later-user@valid.com",
                "description": "Another description",
            },
            format="json",
            **self.auth_headers(self.owner_token),
        )
        self.assertEqual(create_response.status_code, 201)
        self.assertIn("id", create_response.data)

        list_response = self.client.get("/api/requests/", **self.auth_headers(self.owner_token))
        self.assertEqual(list_response.status_code, 200)
        self.assertGreaterEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["direction"], "sent")
        self.assertTrue(list_response.data[0]["is_sent"])
        self.assertFalse(list_response.data[0]["is_received"])

        retrieve_response = self.client.get(
            f"/api/requests/{self.request.id}/",
            {"tracking_code": self.request.tracking_code},
        )
        self.assertEqual(retrieve_response.status_code, 200)
        self.assertEqual(retrieve_response.data["id"], self.request.id)

        slashless_list = self.client.get("/api/requests", **self.auth_headers(self.owner_token))
        self.assertEqual(slashless_list.status_code, 200)

    def test_requests_list_marks_received_requests_for_target(self):
        response = self.client.get("/api/requests/", **self.auth_headers(self.target_token))

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["direction"], "received")
        self.assertFalse(response.data[0]["is_sent"])
        self.assertTrue(response.data[0]["is_received"])

    @patch("chat.emailing.send_templated_email")
    @patch("chat.tasks.process_request_created_task.delay")
    def test_request_create_sends_html_emails_to_requester_and_target(self, mock_delay, mock_send_email):
        from chat.tasks import process_request_created_task

        mock_delay.side_effect = lambda request_id: process_request_created_task.run(request_id)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/requests/",
                {
                    "requester_name": "Another Requester",
                    "requester_email": self.owner.email,
                    "target_name": "Unregistered Target",
                    "target_email": "later-user@valid.com",
                    "description": "Another description",
                },
                format="json",
                **self.auth_headers(self.owner_token),
            )

        self.assertEqual(response.status_code, 201)
        mock_delay.assert_called_once_with(response.data["id"])
        self.assertEqual(mock_send_email.call_count, 2)

        recipients = [call.kwargs["recipient"] for call in mock_send_email.call_args_list]
        self.assertEqual(recipients, [self.owner.email, "later-user@valid.com"])
        self.assertTrue(all(call.kwargs["html_template"] == "emails/request_update.html" for call in mock_send_email.call_args_list))
        self.assertTrue(all(call.kwargs["text_template"] == "emails/request_update.txt" for call in mock_send_email.call_args_list))
        self.assertIn(response.data["tracking_code"], mock_send_email.call_args_list[0].kwargs["subject"])
        self.assertNotIn("requester_name", mock_send_email.call_args_list[1].kwargs["context"])
        self.assertNotIn("requester_email", mock_send_email.call_args_list[1].kwargs["context"])
        self.assertNotIn("target_name", mock_send_email.call_args_list[1].kwargs["context"])
        self.assertNotIn("target_email", mock_send_email.call_args_list[1].kwargs["context"])

    def test_request_conversation_and_message_endpoints(self):
        conversation = self.client.get(
            f"/api/requests/{self.request.id}/conversation/",
            {"tracking_code": self.request.tracking_code},
        )
        self.assertEqual(conversation.status_code, 200)
        self.assertEqual(conversation.data["viewer"]["role"], Message.Actor.TARGET)
        self.assertEqual(conversation.data["participants"]["target"]["is_me"], True)
        self.assertEqual(conversation.data["messages"][0]["message_kind"], Message.Kind.INITIAL_REQUEST)
        self.assertFalse(conversation.data["messages"][0]["is_mine"])
        self.assertEqual(conversation.data["messages"][0]["direction"], "inbound")

        owner_post = self.client.post(
            f"/api/requests/{self.request.id}/messages/",
            {"body": "Owner follow-up"},
            format="json",
            **self.auth_headers(self.owner_token),
        )
        self.assertEqual(owner_post.status_code, 201)
        self.assertEqual(owner_post.data["sender"], Message.Actor.REQUESTER)
        self.assertEqual(owner_post.data["recipient"], Message.Actor.TARGET)
        self.assertTrue(owner_post.data["is_mine"])
        self.assertEqual(owner_post.data["direction"], "outbound")
        self.assertEqual(owner_post.data["sender_role"], Message.Actor.REQUESTER)

        target_post = self.client.post(
            f"/api/requests/{self.request.id}/messages/",
            {"body": "Target response"},
            format="json",
            **self.auth_headers(self.target_token),
        )
        self.assertEqual(target_post.status_code, 201)
        self.assertEqual(target_post.data["sender"], Message.Actor.TARGET)
        self.assertEqual(target_post.data["recipient"], Message.Actor.REQUESTER)
        self.assertTrue(target_post.data["is_mine"])
        self.assertEqual(target_post.data["direction"], "outbound")
        self.assertEqual(target_post.data["sender_role"], Message.Actor.TARGET)

    def test_message_reply_to_specific_message(self):
        first_reply = self.client.post(
            f"/api/requests/{self.request.id}/messages/",
            {"body": "First reply"},
            format="json",
            **self.auth_headers(self.owner_token),
        )
        self.assertEqual(first_reply.status_code, 201)

        second_reply = self.client.post(
            f"/api/requests/{self.request.id}/messages/",
            {"body": "Replying to first", "reply_to_id": first_reply.data["id"]},
            format="json",
            **self.auth_headers(self.target_token),
        )
        self.assertEqual(second_reply.status_code, 201)
        self.assertEqual(second_reply.data["reply_to_id"], first_reply.data["id"])
        self.assertEqual(second_reply.data["reply_to_body"], "First reply")

    def test_tracking_reply_to_specific_message(self):
        initial_message = self.request.messages.get(message_kind=Message.Kind.INITIAL_REQUEST)

        reply = self.client.post(
            "/api/requests/reply/",
            {
                "tracking_code": self.request.tracking_code,
                "body": "Reply using tracking",
                "reply_to_id": initial_message.id,
            },
            format="json",
        )
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(reply.data["message"]["reply_to_id"], initial_message.id)
        self.assertEqual(reply.data["message"]["reply_to_body"], self.request.description)

    def test_reply_to_message_must_belong_to_same_request(self):
        other_request = ShyRequest.objects.create(
            user=self.owner,
            requester_user=self.owner,
            requester_name="Requester Other",
            requester_email=self.owner.email,
            requester_alias="RequesterAlias",
            target_name="Target Other",
            target_email=self.target.email,
            description="Completely separate request",
            status=ShyRequest.Status.SUBMITTED,
        )
        foreign_message = other_request.messages.get(message_kind=Message.Kind.INITIAL_REQUEST)

        response = self.client.post(
            f"/api/requests/{self.request.id}/messages/",
            {"body": "Should fail", "reply_to_id": foreign_message.id},
            format="json",
            **self.auth_headers(self.owner_token),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Reply target message was not found.", response.data["detail"])

    def test_reply_and_conversation_by_tracking_endpoints(self):
        reply = self.client.post(
            "/api/requests/reply/",
            {"tracking_code": self.request.tracking_code, "body": "Reply using tracking"},
            format="json",
        )
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(reply.data["message"]["sender"], Message.Actor.TARGET)
        self.assertEqual(reply.data["viewer"]["role"], Message.Actor.TARGET)
        self.assertTrue(reply.data["message"]["is_mine"])
        self.assertEqual(reply.data["message"]["direction"], "outbound")

        by_tracking = self.client.get(
            f"/api/requests/conversation/by-tracking/{self.request.tracking_code}/"
        )
        self.assertEqual(by_tracking.status_code, 200)
        self.assertIn("messages", by_tracking.data)
        self.assertGreaterEqual(len(by_tracking.data["messages"]), 2)
        self.assertEqual(by_tracking.data["viewer"]["role"], Message.Actor.TARGET)

    @patch("chat.emailing.send_templated_email")
    @patch("chat.tasks.process_request_reply_side_effects_task.delay")
    def test_reply_sends_html_emails_to_both_participants(self, mock_delay, mock_send_email):
        from chat.tasks import process_request_reply_side_effects_task

        mock_delay.side_effect = lambda request_id, sender, body: process_request_reply_side_effects_task.run(request_id, sender, body)

        with self.captureOnCommitCallbacks(execute=True):
            reply = self.client.post(
                "/api/requests/reply/",
                {"tracking_code": self.request.tracking_code, "body": "Reply using tracking"},
                format="json",
            )

        self.assertEqual(reply.status_code, 201)
        mock_delay.assert_called_once_with(self.request.id, Message.Actor.TARGET, "Reply using tracking")
        self.assertEqual(mock_send_email.call_count, 2)

        recipients = [call.kwargs["recipient"] for call in mock_send_email.call_args_list]
        self.assertEqual(recipients, [self.owner.email, self.target.email])
        self.assertTrue(mock_send_email.call_args_list[0].kwargs["context"]["message_hidden"])
        self.assertTrue(mock_send_email.call_args_list[0].kwargs["context"]["has_new_message"])
        self.assertEqual(mock_send_email.call_args_list[0].kwargs["context"]["reply_url"], "")
        self.assertEqual(mock_send_email.call_args_list[1].kwargs["context"]["message_label"], "Your message")
        self.assertTrue(all(call.kwargs["html_template"] == "emails/request_update.html" for call in mock_send_email.call_args_list))

    @override_settings(
        REQUEST_REPLY_URL_TEMPLATE="shy2ask://reply/{tracking_code}",
        IOS_APP_URL="https://apps.apple.com/app/shy2ask",
        ANDROID_APP_URL="https://play.google.com/store/apps/details?id=com.shy2ask",
    )
    def test_request_email_template_hides_private_content_and_renders_app_ctas(self):
        html = render_to_string(
            "emails/request_update.html",
            build_email_context(
                recipient_name="Requester",
                summary_title="Latest update",
                summary_body="A new update is ready.",
                tracking_code=self.request.tracking_code,
                recipient_role_label="Requester",
                service_channel=self.request.get_service_channel_display(),
                status_label=self.request.get_status_display(),
                has_new_message=True,
                message_hidden=True,
                reply_url=f"shy2ask://reply/{self.request.tracking_code}",
                ios_app_url="https://apps.apple.com/app/shy2ask",
                android_app_url="https://play.google.com/store/apps/details?id=com.shy2ask",
            ),
        )

        self.assertNotIn("Need help with this request", html)
        self.assertNotIn("Reply using tracking", html)
        self.assertIn("Reply in App", html)
        self.assertIn("Download for iOS", html)
        self.assertIn("Download for Android", html)

    def test_unreplied_requests_endpoint_only_returns_requests_without_target_reply(self):
        unreplied_request = self.request
        replied_request = ShyRequest.objects.create(
            user=self.owner,
            requester_user=self.owner,
            requester_name="Requester Name 2",
            requester_email=self.owner.email,
            requester_alias="RequesterAlias",
            target_name="Target Name 2",
            target_email=self.target.email,
            description="Already answered request",
            status=ShyRequest.Status.SUBMITTED,
        )
        Message.objects.create(
            request=replied_request,
            sender=Message.Actor.TARGET,
            recipient=Message.Actor.REQUESTER,
            message_kind=Message.Kind.REPLY,
            sender_user=self.target,
            recipient_user=self.owner,
            sender_email=self.target.email,
            recipient_email=self.owner.email,
            body="Answered already",
        )

        response = self.client.get("/api/requests/unreplied/", **self.auth_headers(self.owner_token))

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data}
        self.assertIn(unreplied_request.id, returned_ids)
        self.assertNotIn(replied_request.id, returned_ids)

    def test_request_soft_delete_hides_request_and_messages(self):
        message = Message.objects.create(
            request=self.request,
            sender=Message.Actor.REQUESTER,
            recipient=Message.Actor.TARGET,
            message_kind=Message.Kind.REPLY,
            sender_user=self.owner,
            recipient_user=self.target,
            sender_email=self.owner.email,
            recipient_email=self.target.email,
            body="Delete this thread",
        )

        response = self.client.delete(
            f"/api/requests/{self.request.id}/",
            **self.auth_headers(self.owner_token),
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(ShyRequest.objects.filter(id=self.request.id).exists())
        self.assertTrue(ShyRequest.all_objects.get(id=self.request.id).is_deleted)
        self.assertFalse(Message.objects.filter(id=message.id).exists())
        self.assertTrue(Message.all_objects.get(id=message.id).is_deleted)

    def test_bulk_request_soft_delete(self):
        another_request = ShyRequest.objects.create(
            user=self.owner,
            requester_user=self.owner,
            requester_name="Requester Name 3",
            requester_email=self.owner.email,
            requester_alias="RequesterAlias",
            target_name="Target Name 3",
            target_email="third@valid.com",
            description="Bulk delete me",
            status=ShyRequest.Status.SUBMITTED,
        )

        response = self.client.post(
            "/api/requests/bulk-delete/",
            {"ids": [self.request.id, another_request.id]},
            format="json",
            **self.auth_headers(self.owner_token),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["deleted_count"], 2)
        self.assertEqual(ShyRequest.objects.filter(id__in=[self.request.id, another_request.id]).count(), 0)
        self.assertEqual(ShyRequest.all_objects.filter(id__in=[self.request.id, another_request.id], is_deleted=True).count(), 2)

    def test_message_soft_delete_endpoints(self):
        first_reply = Message.objects.create(
            request=self.request,
            sender=Message.Actor.REQUESTER,
            recipient=Message.Actor.TARGET,
            message_kind=Message.Kind.REPLY,
            sender_user=self.owner,
            recipient_user=self.target,
            sender_email=self.owner.email,
            recipient_email=self.target.email,
            body="Delete this message",
        )
        second_reply = Message.objects.create(
            request=self.request,
            sender=Message.Actor.TARGET,
            recipient=Message.Actor.REQUESTER,
            message_kind=Message.Kind.REPLY,
            sender_user=self.target,
            recipient_user=self.owner,
            sender_email=self.target.email,
            recipient_email=self.owner.email,
            body="Delete this one too",
        )

        delete_response = self.client.delete(
            f"/api/requests/{self.request.id}/messages/{first_reply.id}/",
            **self.auth_headers(self.owner_token),
        )
        self.assertEqual(delete_response.status_code, 204)
        first_reply.refresh_from_db()
        self.assertFalse(first_reply.is_deleted)
        self.assertTrue(first_reply.deleted_by_sender)
        self.assertIsNotNone(first_reply.sender_deleted_at)
        self.assertFalse(first_reply.deleted_by_recipient)

        bulk_response = self.client.post(
            f"/api/requests/{self.request.id}/messages/bulk-delete/",
            {"ids": [second_reply.id]},
            format="json",
            **self.auth_headers(self.owner_token),
        )
        self.assertEqual(bulk_response.status_code, 200)
        self.assertEqual(bulk_response.data["deleted_count"], 1)
        second_reply.refresh_from_db()
        self.assertFalse(second_reply.is_deleted)
        self.assertTrue(second_reply.deleted_by_recipient)
        self.assertIsNotNone(second_reply.recipient_deleted_at)
        self.assertFalse(second_reply.deleted_by_sender)

        owner_conversation = self.client.get(
            f"/api/requests/{self.request.id}/conversation/",
            **self.auth_headers(self.owner_token),
        )
        self.assertEqual(owner_conversation.status_code, 200)
        owner_message_ids = {item["id"] for item in owner_conversation.data["messages"]}
        self.assertNotIn(first_reply.id, owner_message_ids)
        self.assertNotIn(second_reply.id, owner_message_ids)

        target_conversation = self.client.get(
            f"/api/requests/{self.request.id}/conversation/",
            **self.auth_headers(self.target_token),
        )
        self.assertEqual(target_conversation.status_code, 200)
        target_message_ids = {item["id"] for item in target_conversation.data["messages"]}
        self.assertIn(first_reply.id, target_message_ids)
        self.assertIn(second_reply.id, target_message_ids)

    def test_blocking_three_requests_deactivates_requester(self):
        requests_to_block = [self.request]
        for index in range(2):
            requests_to_block.append(
                ShyRequest.objects.create(
                    user=self.owner,
                    requester_user=self.owner,
                    requester_name=f"Requester Name {index}",
                    requester_email=self.owner.email,
                    requester_alias="RequesterAlias",
                    target_user=self.target,
                    target_name="Target Name",
                    target_email=self.target.email,
                    description=f"Follow up request {index}",
                    status=ShyRequest.Status.SUBMITTED,
                )
            )

        final_response = None
        for blocked_request in requests_to_block:
            final_response = self.client.post(
                f"/api/requests/{blocked_request.id}/block/",
                {"note": "Unsafe request"},
                format="json",
                **self.auth_headers(self.target_token),
            )
            self.assertEqual(final_response.status_code, 200)

        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)
        self.assertEqual(final_response.data["blocked_requests_count"], 3)
        self.assertTrue(final_response.data["requester_user_blocked"])
        self.assertEqual(ShyRequest.all_objects.filter(requester_user=self.owner, is_blocked=True).count(), 3)

    def test_unread_messages_endpoint_returns_only_current_users_unread_notifications(self):
        Notification.objects.create(
            recipient_user=self.owner,
            recipient_email=self.owner.email,
            subject="Unread owner notification",
            body="Still unread",
            related_request=self.request,
        )
        Notification.objects.create(
            recipient_user=self.owner,
            recipient_email=self.owner.email,
            subject="Read owner notification",
            body="Already opened",
            related_request=self.request,
            is_read=True,
        )
        Notification.objects.create(
            recipient_user=self.target,
            recipient_email=self.target.email,
            subject="Unread target notification",
            body="Other user's notification",
            related_request=self.request,
        )

        response = self.client.get("/api/messages/unread/", **self.auth_headers(self.owner_token))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["subject"], "Unread owner notification")
        self.assertEqual(response.data[0]["request_id"], self.request.id)
        self.assertEqual(response.data[0]["tracking_code"], self.request.tracking_code)

    def test_subscriptions_create_list_and_delete(self):
        create_response = self.client.post(
            "/api/subscriptions",
            {"subscription_type": Subscription.Type.REQUEST_UPDATES, "request_id": self.request.id},
            format="json",
            **self.auth_headers(self.owner_token),
        )
        self.assertEqual(create_response.status_code, 201)
        subscription_id = create_response.data["id"]

        list_response = self.client.get("/api/subscriptions/", **self.auth_headers(self.owner_token))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data), 1)

        delete_response = self.client.delete(
            f"/api/subscriptions/{subscription_id}",
            **self.auth_headers(self.owner_token),
        )
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(Subscription.objects.get(id=subscription_id).is_active)

    def test_subscription_requires_owned_request(self):
        outsider = User.objects.create_user(
            email="outsider@valid.com",
            password="password123",
            is_email_verified=True,
            is_phone_verified=True,
        )
        outsider_token, _ = Token.objects.get_or_create(user=outsider)

        response = self.client.post(
            "/api/subscriptions/",
            {"subscription_type": Subscription.Type.REQUEST_UPDATES, "request_id": self.request.id},
            format="json",
            **self.auth_headers(outsider_token),
        )

        self.assertEqual(response.status_code, 400)

    @override_settings(OPENAI_API_KEY="")
    def test_censor_text_without_openai_key_returns_blocked(self):
        response = self.client.post("/api/censor/text/", {"text": "hello"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["blocked"])

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("chat.api_views.censor_text_full")
    def test_censor_text_endpoint_uses_engine(self, mock_censor_text_full):
        mock_censor_text_full.return_value = SimpleNamespace(
            blocked=False,
            censored_text="clean",
            detected=[],
            categories=[],
            ai_toxic_score=0.1,
            ai_provider="mock",
        )

        response = self.client.post("/api/censor/text/", {"text": "safe text"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["censored_text"], "clean")
        mock_censor_text_full.assert_called_once()

    @patch("chat.api_views.censor_image")
    def test_censor_image_endpoint(self, mock_censor_image):
        mock_censor_image.return_value = SimpleNamespace(
            censored_text="image clean",
            blocked=False,
            detected=[],
            categories=[],
            extracted_text="hello image",
            ocr_available=True,
            ai_toxic_score=0.0,
            ai_provider="mock",
        )
        uploaded = SimpleUploadedFile("sample.png", b"fake-image-bytes", content_type="image/png")

        response = self.client.post("/api/censor/image/", {"image": uploaded}, format="multipart")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["extracted_text"], "hello image")
        mock_censor_image.assert_called_once()
