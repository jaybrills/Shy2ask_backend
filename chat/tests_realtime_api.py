import json
from django.test import TestCase, Client
from account.models import User
from chat.models import Message, ShyRequest
from chat.message_service import create_message_for_request
from chat.websocket_utils import build_received_request_inbox_snapshot
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

    def test_realtime_docs_are_available_for_swagger(self):
        response = self.client.get("/api/realtime/docs/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("/ws/chat/{request_id}/", payload["chat"]["url"])
        self.assertIn("format=json", payload["chat"]["json_url"])
        self.assertIn("/ws/notifications/", payload["notifications"]["url"])
        self.assertIn("/ws/requests/inbox/", payload["request_inbox"]["url"])

        schema_response = self.client.get("/openapi.json")
        self.assertEqual(schema_response.status_code, 200)
        self.assertIn("/api/realtime/docs/", schema_response.json()["paths"])

    def test_received_request_inbox_snapshot_returns_recent_requests_and_stats(self):
        requester = User.objects.create_user(
            email="requester@shy2ask.com",
            password="password123",
            is_verified=True,
        )

        pending_request = ShyRequest.objects.create(
            user=requester,
            requester_user=requester,
            requester_name="Requester One",
            requester_email=requester.email,
            target_user=self.user,
            target_name="Realtime Target",
            target_email=self.user.email,
            description="Pending request",
            status=ShyRequest.Status.SUBMITTED,
        )
        create_message_for_request(
            pending_request,
            "Most recent requester message",
            user=requester,
            run_async_business_logic=False,
        )

        cancelled_request = ShyRequest.objects.create(
            user=requester,
            requester_user=requester,
            requester_name="Requester Two",
            requester_email=requester.email,
            target_user=self.user,
            target_name="Realtime Target",
            target_email=self.user.email,
            description="Cancelled request",
            status=ShyRequest.Status.REJECTED,
        )

        blocked_request = ShyRequest.objects.create(
            user=requester,
            requester_user=requester,
            requester_name="Requester Three",
            requester_email=requester.email,
            target_user=self.user,
            target_name="Realtime Target",
            target_email=self.user.email,
            description="Blocked request",
            status=ShyRequest.Status.SUBMITTED,
        )
        blocked_request.block(actor=self.user, note="Unsafe")

        snapshot = build_received_request_inbox_snapshot(self.user)

        self.assertEqual(snapshot["stats"]["received_requests_count"], 3)
        self.assertEqual(snapshot["stats"]["pending_requests_count"], 1)
        self.assertEqual(snapshot["stats"]["cancelled_requests_count"], 2)
        self.assertEqual(snapshot["stats"]["rejected_requests_count"], 2)
        self.assertEqual(snapshot["stats"]["blocked_requests_count"], 1)
        self.assertEqual(snapshot["recent_requests"][0]["id"], pending_request.id)
        self.assertEqual(
            snapshot["recent_requests"][0]["latest_message"]["clean_body"],
            "Most recent requester message",
        )
        request_ids = [item["id"] for item in snapshot["recent_requests"]]
        self.assertIn(cancelled_request.id, request_ids)
        self.assertIn(blocked_request.id, request_ids)
