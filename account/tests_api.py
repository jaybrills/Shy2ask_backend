import json
from django.test import TestCase, Client
from django.urls import reverse
from account.models import User
from rest_framework.authtoken.models import Token

class AccountAPITest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="api@example.com",
            password="password123",
            first_name="API",
            last_name="User",
            is_verified=True
        )
        self.token, _ = Token.objects.get_or_create(user=self.user)
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token.key}"}

    def test_login(self):
        data = {"email": "api@example.com", "password": "password123"}
        response = self.client.post("/auth/login", data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json())

    def test_get_profile(self):
        response = self.client.get("/profile/me", **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "api@example.com")

    def test_update_profile(self):
        # Ninja expects the Schema to be a JSON string in the 'payload' field
        # when mixed with File arguments in a multipart request.
        # Since PATCH doesn't default to multipart in Django Client, we specify it.
        from django.test.client import MULTIPART_CONTENT, encode_multipart, BOUNDARY
        payload_data = {"first_name": "Updated"}
        data = {"payload": json.dumps(payload_data)}
        content = encode_multipart(BOUNDARY, data)
        response = self.client.patch("/profile/me", data=content, content_type=MULTIPART_CONTENT, **self.auth_headers)
        
        if response.status_code != 200:
            print(f"\nProfile Update Error: {response.content}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["first_name"], "Updated")
