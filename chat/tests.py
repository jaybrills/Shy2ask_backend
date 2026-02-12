from django.test import TestCase
from rest_framework.test import APIClient
from chat.models import ShyRequest, Conversation, Notification

class ShyRequestVerificationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_request_creates_conversation_and_notification(self):
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

        # Check Conversation
        self.assertTrue(Conversation.objects.filter(request=shy_request).exists())

        # Check Notification (the requester should have a notification)
        self.assertTrue(Notification.objects.filter(related_request=shy_request, recipient_email="test@example.com").exists())
