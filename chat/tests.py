from django.test import TestCase
from rest_framework.test import APIClient
from chat.models import Message, ShyRequest, Notification
from account.models import User

class ShyRequestVerificationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_request_and_notification(self):
        data = {
            "requester_name": "Test User",
            "requester_email": "test@example.com",
            "description": "This is a test request",
            "service_channel": "email"
        }
        response = self.client.post("/api/requests/", data, format="json")
        self.assertEqual(response.status_code, 201)

        # Check ShyRequest
        request_id = response.data["id"]
        shy_request = ShyRequest.objects.get(id=request_id)
        self.assertEqual(shy_request.requester_name, "Test User")

        # Check Notification (the requester should have a notification)
        self.assertTrue(Notification.objects.filter(related_request=shy_request, recipient_email="test@example.com").exists())

    def test_reply_on_request_by_tracking_code(self):
        shy_request = ShyRequest.objects.create(
            requester_name="Owner",
            requester_email="owner@example.com",
            description="Need follow-up",
            status=ShyRequest.Status.SUBMITTED,
        )
        response = self.client.post(
            "/api/requests/reply/",
            {"tracking_code": shy_request.tracking_code, "body": "Responder update", "alias": "Responder"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["message"]["sender"], "target")
        self.assertEqual(response.data["tracking_code"], shy_request.tracking_code)

    def test_messages_endpoint_requires_owner_or_tracking(self):
        shy_request = ShyRequest.objects.create(
            requester_name="Owner",
            requester_email="owner2@example.com",
            description="Access test",
            status=ShyRequest.Status.SUBMITTED,
        )
        denied = self.client.post(
            f"/api/requests/{shy_request.id}/messages/",
            {"body": "No access"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

        allowed = self.client.post(
            f"/api/requests/{shy_request.id}/messages/",
            {"body": "With tracking", "tracking_code": shy_request.tracking_code},
            format="json",
        )
        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(allowed.data["sender"], "target")

    def test_blocked_content_rejected(self):
        shy_request = ShyRequest.objects.create(
            requester_name="Owner",
            requester_email="owner3@example.com",
            description="Block test",
            status=ShyRequest.Status.SUBMITTED,
        )
        resp = self.client.post(
            f"/api/requests/{shy_request.id}/messages/",
            {"body": "I want to buy drugs", "tracking_code": shy_request.tracking_code},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_blocked_request_description_returns_field_error(self):
        response = self.client.post(
            "/api/requests/",
            {
                "requester_name": "Test User",
                "requester_email": "test2@example.com",
                "target_name": "Target User",
                "target_email": "target2@example.com",
                "description": "Willst du ein Madchen verkaufen?",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("description", response.data)
        self.assertEqual(response.data["description"], ["Description contains blocked content."])

    def test_messages_endpoint_as_owner_sender_is_requester(self):
        owner = User.objects.create_user(email="owner@shy2ask.com", password="pass12345", is_verified=True)
        shy_request = ShyRequest.objects.create(
            user=owner,
            requester_name="Owner",
            requester_email="owner@shy2ask.com",
            description="Owner post",
            status=ShyRequest.Status.SUBMITTED,
        )
        self.client.force_authenticate(user=owner)
        response = self.client.post(
            f"/api/requests/{shy_request.id}/messages/",
            {"body": "Owner message"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["sender"], "requester")
        self.assertTrue(Message.objects.filter(request=shy_request).exists())

    def test_target_email_can_access_and_send(self):
        target = User.objects.create_user(email="target@shy2ask.com", password="pass12345", is_verified=True)
        shy_request = ShyRequest.objects.create(
            user=None,
            requester_name="Requester",
            requester_email="req@shy2ask.com",
            target_email=target.email,
            description="Target reply",
            status=ShyRequest.Status.SUBMITTED,
        )
        self.client.force_authenticate(user=target)
        response = self.client.post(
            f"/api/requests/{shy_request.id}/messages/",
            {"body": "Target responding"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["sender"], "target")

        convo = self.client.get(f"/api/requests/{shy_request.id}/conversation/")
        self.assertEqual(convo.status_code, 200)
        self.assertGreaterEqual(len(convo.data["messages"]), 2)
