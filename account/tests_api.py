import json
from django.test import TestCase, Client
from django.urls import reverse
from account.models import User
from rest_framework.authtoken.models import Token

class AccountAPITest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="api@valid.com",
            password="password123",
            first_name="API",
            last_name="User",
            is_verified=True
        )
        self.token, _ = Token.objects.get_or_create(user=self.user)
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token.key}"}

    def test_login(self):
        data = {"email": "api@valid.com", "password": "password123"}
        response = self.client.post("/auth/login", data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json())

    def test_get_profile(self):
        response = self.client.get("/profile/me", **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "api@valid.com")

    def test_update_profile(self):
        response = self.client.patch(
            "/profile/me",
            data=json.dumps({"first_name": "Updated"}),
            content_type="application/json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["first_name"], "Updated")
