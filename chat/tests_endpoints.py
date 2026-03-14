import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from account.models import User
from chat.models import Message, ShyRequest, Subscription


class ChatEndpointCoverageTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="requester@valid.com",
            password="password123",
            alias_name="RequesterAlias",
            is_verified=True,
        )
        self.target = User.objects.create_user(
            email="target@valid.com",
            password="password123",
            is_verified=True,
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

        retrieve_response = self.client.get(
            f"/api/requests/{self.request.id}/",
            {"tracking_code": self.request.tracking_code},
        )
        self.assertEqual(retrieve_response.status_code, 200)
        self.assertEqual(retrieve_response.data["id"], self.request.id)

        slashless_list = self.client.get("/api/requests", **self.auth_headers(self.owner_token))
        self.assertEqual(slashless_list.status_code, 200)

    def test_request_conversation_and_message_endpoints(self):
        conversation = self.client.get(
            f"/api/requests/{self.request.id}/conversation/",
            {"tracking_code": self.request.tracking_code},
        )
        self.assertEqual(conversation.status_code, 200)
        self.assertEqual(conversation.data["messages"][0]["message_kind"], Message.Kind.INITIAL_REQUEST)

        owner_post = self.client.post(
            f"/api/requests/{self.request.id}/messages/",
            {"body": "Owner follow-up"},
            format="json",
            **self.auth_headers(self.owner_token),
        )
        self.assertEqual(owner_post.status_code, 201)
        self.assertEqual(owner_post.data["sender"], Message.Actor.REQUESTER)
        self.assertEqual(owner_post.data["recipient"], Message.Actor.TARGET)

        target_post = self.client.post(
            f"/api/requests/{self.request.id}/messages/",
            {"body": "Target response"},
            format="json",
            **self.auth_headers(self.target_token),
        )
        self.assertEqual(target_post.status_code, 201)
        self.assertEqual(target_post.data["sender"], Message.Actor.TARGET)
        self.assertEqual(target_post.data["recipient"], Message.Actor.REQUESTER)

    def test_reply_and_conversation_by_tracking_endpoints(self):
        reply = self.client.post(
            "/api/requests/reply/",
            {"tracking_code": self.request.tracking_code, "body": "Reply using tracking"},
            format="json",
        )
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(reply.data["message"]["sender"], Message.Actor.TARGET)

        by_tracking = self.client.get(
            f"/api/requests/conversation/by-tracking/{self.request.tracking_code}/"
        )
        self.assertEqual(by_tracking.status_code, 200)
        self.assertGreaterEqual(len(by_tracking.data), 2)

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
        outsider = User.objects.create_user(email="outsider@valid.com", password="password123", is_verified=True)
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
