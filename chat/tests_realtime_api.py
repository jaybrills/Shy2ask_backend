import json
from django.test import TestCase, Client
from account.models import User
from chat.models import Message, ShyRequest
from rest_framework.authtoken.models import Token

class RealtimeAPITest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="realtime@shy2ask.com",
            password="password123",
            is_verified=True
        )
        self.token, _ = Token.objects.get_or_create(user=self.user)
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token.key}"}

    def test_create_request_drf(self):
        data = {
            "requester_name": "Realtime User",
            "requester_email": "realtime_req@valid.com",
            "description": "Realtime test request"
        }
        response = self.client.post("/api/requests/", data=json.dumps(data), content_type="application/json", **self.auth_headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["requester_name"], "Realtime User")
        
        # Request description is mirrored as the initial message.
        request_id = response.json()["id"]
        self.assertEqual(Message.objects.filter(request_id=request_id).count(), 1)

    def test_list_requests_drf(self):
        ShyRequest.objects.create(user=self.user, requester_name="R1", requester_email="r1@e.com", description="D1")
        response = self.client.get("/api/requests/", **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()), 1)

    def test_list_requests_target_email(self):
        req = ShyRequest.objects.create(requester_name="RTarget", requester_email="r2@e.com", target_email=self.user.email, description="D2")
        response = self.client.get("/api/requests/", **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        ids = [r["id"] for r in response.json()]
        self.assertIn(req.id, ids)

    def test_get_conversation_drf(self):
        req = ShyRequest.objects.create(requester_name="R2", requester_email="r2@e.com", description="D2")
        response = self.client.get(f"/api/requests/{req.id}/conversation/")
        self.assertEqual(response.status_code, 403)
        response_ok = self.client.get(f"/api/requests/{req.id}/conversation/?tracking_code={req.tracking_code}")
        self.assertEqual(response_ok.status_code, 200)
        self.assertIn("description", response_ok.json())
        self.assertIn("messages", response_ok.json())

    def test_reply_by_tracking_drf(self):
        req = ShyRequest.objects.create(requester_name="R3", requester_email="r3@e.com", description="D3")
        payload = {
            "tracking_code": req.tracking_code,
            "body": "Responder message from realtime test",
            "alias": "ResponderN",
        }
        response = self.client.post(
            "/api/requests/reply/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["message"]["sender"], "target")

    def test_send_message_drf_requires_auth_or_tracking(self):
        req = ShyRequest.objects.create(requester_name="R4", requester_email="r4@e.com", description="D4")
        denied = self.client.post(
            f"/api/requests/{req.id}/messages/",
            data=json.dumps({"body": "No permission"}),
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)

        allowed = self.client.post(
            f"/api/requests/{req.id}/messages/",
            data=json.dumps({"body": "With tracking", "tracking_code": req.tracking_code}),
            content_type="application/json",
        )
        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(allowed.json()["sender"], "target")

    def test_owner_token_can_get_conversation(self):
        req = ShyRequest.objects.create(user=self.user, requester_name="R5", requester_email="r5@e.com", description="D5")
        resp = self.client.get(
            f"/api/requests/{req.id}/conversation/",
            HTTP_AUTHORIZATION=f"Bearer {self.token.key}",
        )
        self.assertEqual(resp.status_code, 200)
