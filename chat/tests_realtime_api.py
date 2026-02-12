import json
from django.test import TestCase, Client
from account.models import User
from chat.models import ShyRequest, Conversation
from rest_framework.authtoken.models import Token

class RealtimeAPITest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="ninja@example.com",
            password="password123",
            is_verified=True
        )
        self.token, _ = Token.objects.get_or_create(user=self.user)
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token.key}"}

    def test_create_request_ninja(self):
        data = {
            "requester_name": "Ninja User",
            "requester_email": "ninja_req@example.com",
            "description": "Ninja test request"
        }
        response = self.client.post("/requests/", data=json.dumps(data), content_type="application/json", **self.auth_headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["requester_name"], "Ninja User")
        
        # Verify conversation was created
        request_id = response.json()["id"]
        self.assertTrue(Conversation.objects.filter(request_id=request_id).exists())

    def test_list_requests_ninja(self):
        ShyRequest.objects.create(user=self.user, requester_name="R1", requester_email="r1@e.com", description="D1")
        response = self.client.get("/requests/", **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()), 1)

    def test_get_conversation_ninja(self):
        req = ShyRequest.objects.create(requester_name="R2", requester_email="r2@e.com", description="D2")
        response = self.client.get(f"/requests/{req.id}/conversation")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
