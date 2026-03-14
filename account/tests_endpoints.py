import json
from unittest.mock import patch

from django.test import Client, TestCase
from rest_framework.authtoken.models import Token

from account.models import User


class AccountEndpointCoverageTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="owner@valid.com",
            password="password123",
            first_name="Owner",
            last_name="User",
            is_verified=True,
        )
        self.staff = User.objects.create_user(
            email="staff@valid.com",
            password="password123",
            first_name="Staff",
            last_name="User",
            is_verified=True,
            is_staff=True,
        )
        self.user_token, _ = Token.objects.get_or_create(user=self.user)
        self.staff_token, _ = Token.objects.get_or_create(user=self.staff)

    def auth_headers(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token.key}"}

    def test_home_page_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shy2Ask")
        self.assertContains(response, "Swiss Exclusive Beta")

    def test_docs_page_renders_current_endpoints(self):
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("/swagger/"))

    def test_markdown_and_openapi_docs_routes_render(self):
        markdown_response = self.client.get("/docs/api.md")
        self.assertEqual(markdown_response.status_code, 200)
        self.assertIn("text/markdown", markdown_response["Content-Type"])
        self.assertContains(markdown_response, "Shy2Ask – API Documentation")

        schema_response = self.client.get("/openapi.json")
        self.assertEqual(schema_response.status_code, 200)
        self.assertIn("openapi", json.loads(schema_response.content))

        swagger_response = self.client.get("/swagger/")
        self.assertEqual(swagger_response.status_code, 200)

    def test_api_root_lists_all_main_endpoint_groups(self):
        response = self.client.get("/api/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("auth", payload)
        self.assertIn("profile", payload)
        self.assertIn("chat", payload)
        self.assertTrue(payload["auth"]["login"].endswith("/api/auth/login"))
        self.assertTrue(payload["chat"]["requests"].endswith("/api/requests/"))

    @patch("account.api_views.create_and_send_verification_otp")
    def test_register_endpoint_creates_unverified_user(self, mock_send_verification):
        payload = {
            "email": "newuser@valid.com",
            "password": "password123",
            "first_name": "New",
            "last_name": "User",
            "alias_name": "newbie",
        }
        response = self.client.post("/auth/register", data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(email="newuser@valid.com", is_verified=False).exists())
        self.assertIn("token", response.json())
        mock_send_verification.assert_called_once()

    @patch("account.api_views.create_and_send_verification_otp")
    def test_register_existing_unverified_user_resends_verification(self, mock_send_verification):
        existing = User.objects.create_user(
            email="pending@valid.com",
            password="password123",
            is_verified=False,
        )

        response = self.client.post(
            "/auth/register",
            data=json.dumps({"email": existing.email, "password": "password123"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn("Verification OTP resent", response.json()["message"])
        mock_send_verification.assert_called_once_with(existing)

    def test_login_rejects_unverified_user(self):
        User.objects.create_user(email="pending2@valid.com", password="password123", is_verified=False)

        response = self.client.post(
            "/auth/login",
            data=json.dumps({"email": "pending2@valid.com", "password": "password123"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "email_not_verified")

    def test_login_returns_token_for_verified_user(self):
        response = self.client.post(
            "/auth/login",
            data=json.dumps({"email": self.user.email, "password": "password123"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json())
        self.assertEqual(response.json()["user"]["email"], self.user.email)

    def test_login_works_with_api_prefix_and_trailing_slash(self):
        response = self.client.post(
            "/api/auth/login/",
            data=json.dumps({"email": self.user.email, "password": "password123"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json())

    @patch("account.api_views.create_and_send_reset_otp")
    def test_forgot_password_calls_service(self, mock_send_reset):
        response = self.client.post(
            "/auth/forgot-password",
            data=json.dumps({"email": self.user.email}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        mock_send_reset.assert_called_once_with(self.user.email)

    @patch("account.api_views.verify_otp_and_reset_password", return_value=True)
    def test_reset_password_success(self, mock_verify_reset):
        response = self.client.post(
            "/auth/reset-password",
            data=json.dumps({"email": self.user.email, "otp": "123456", "new_password": "newpassword123"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        mock_verify_reset.assert_called_once_with(self.user.email, "123456", "newpassword123")

    def test_reset_password_rejects_short_password(self):
        response = self.client.post(
            "/auth/reset-password",
            data=json.dumps({"email": self.user.email, "otp": "123456", "new_password": "short"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    @patch("account.api_views.verify_email_otp")
    def test_verify_email_success(self, mock_verify_email):
        pending = User.objects.create_user(email="verifyme@valid.com", password="password123", is_verified=False)
        mock_verify_email.return_value = pending

        response = self.client.post(
            "/auth/verify-email",
            data=json.dumps({"email": pending.email, "otp_code": "111111"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["email"], pending.email)
        mock_verify_email.assert_called_once_with(pending.email, "111111")

    @patch("account.api_views.create_and_send_verification_otp")
    def test_resend_verification_for_known_unverified_user(self, mock_send_verification):
        pending = User.objects.create_user(email="resend@valid.com", password="password123", is_verified=False)

        response = self.client.post(
            "/auth/resend-verification",
            data=json.dumps({"email": pending.email}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        mock_send_verification.assert_called_once_with(pending)

    def test_check_email_endpoint_reports_existing_user(self):
        response = self.client.post(
            "/auth/check-email",
            data=json.dumps({"email": self.user.email}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_available"])

    def test_profile_me_get_and_patch(self):
        get_response = self.client.get("/profile/me", **self.auth_headers(self.user_token))
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["email"], self.user.email)

        patch_response = self.client.patch(
            "/profile/me",
            data=json.dumps({"first_name": "Updated", "alias_name": "alias-updated"}),
            content_type="application/json",
            **self.auth_headers(self.user_token),
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["first_name"], "Updated")
        self.assertEqual(patch_response.json()["alias_name"], "alias-updated")

    def test_profile_users_requires_staff_and_supports_search(self):
        forbidden = self.client.get("/profile/users", **self.auth_headers(self.user_token))
        self.assertEqual(forbidden.status_code, 403)

        allowed = self.client.get("/profile/users?search=owner", **self.auth_headers(self.staff_token))
        self.assertEqual(allowed.status_code, 200)
        self.assertGreaterEqual(allowed.json()["count"], 1)
