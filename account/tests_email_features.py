import json
from unittest.mock import patch
from django.test import TestCase, Client
from account.models import User
from rest_framework.authtoken.models import Token
from django.utils import timezone
import datetime
from account.models import EmailVerificationOTP
from account.tasks import send_otp_email_task, send_verification_email_task

class EmailFeaturesTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_check_email_available(self):
        """Test that a new email is available."""
        data = {"email": "newuser@valid.com"}
        response = self.client.post("/auth/check-email", data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_available"])
        self.assertEqual(response.json()["message"], "Email is available.")

    def test_check_email_taken(self):
        """Test that an existing email is not available."""
        User.objects.create_user(email="existing@valid.com", password="password")
        data = {"email": "existing@valid.com"}
        response = self.client.post("/auth/check-email", data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_available"])
        self.assertEqual(response.json()["message"], "This email is already registered.")

    def test_check_email_disposable(self):
        """Test that a disposable email returns not available/invalid."""
        data = {"email": "test@example.com"}
        response = self.client.post("/auth/check-email", data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_available"])
        self.assertIn("Disposable email addresses are not allowed", response.json()["message"])

    def test_register_disposable(self):
        """Test registration with disposable email fails."""
        data = {
            "email": "test@mailinator.com",
            "password": "password123",
            "first_name": "Test",
            "last_name": "User"
        }
        response = self.client.post("/auth/register", data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Disposable email addresses are not allowed", response.json()["detail"])

    def test_verify_email_disposable(self):
        """Test verify email with disposable email fails (even if somehow registered)."""
        # Create user with valid email first
        user = User.objects.create_user(email="valid@email.com", password="password", is_verified=False)
        # Update to disposable email bypassing save() and full_clean()
        User.objects.filter(id=user.id).update(email="test@yopmail.com")
        user.refresh_from_db()

        # Manually create OTP
        otp = EmailVerificationOTP.objects.create(
            user=user,
            otp_code="123456",
            expires_at=timezone.now() + datetime.timedelta(minutes=10)
        )

        data = {"email": "test@yopmail.com", "otp_code": "123456"}
        response = self.client.post("/auth/verify-email", data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Disposable email addresses are not allowed", response.json()["detail"])

    @patch("account.tasks.send_templated_email")
    def test_password_reset_email_uses_branded_templates(self, mock_send):
        send_otp_email_task.run("user@valid.com", "123456")

        self.assertTrue(mock_send.called)
        _, kwargs = mock_send.call_args
        self.assertEqual(kwargs["subject"], "Shy2Ask.com password reset code")
        self.assertEqual(kwargs["recipient"], "user@valid.com")
        self.assertEqual(kwargs["text_template"], "emails/auth_otp.txt")
        self.assertEqual(kwargs["html_template"], "emails/auth_otp.html")
        self.assertEqual(kwargs["context"]["otp"], "123456")
        self.assertEqual(kwargs["context"]["app_name"], "Shy2Ask.com")

    @patch("account.tasks.send_templated_email")
    def test_verification_email_uses_branded_templates(self, mock_send):
        send_verification_email_task.run("user@valid.com", "654321")

        self.assertTrue(mock_send.called)
        _, kwargs = mock_send.call_args
        self.assertEqual(kwargs["subject"], "Verify your email for Shy2Ask.com")
        self.assertEqual(kwargs["recipient"], "user@valid.com")
        self.assertEqual(kwargs["text_template"], "emails/auth_otp.txt")
        self.assertEqual(kwargs["html_template"], "emails/auth_otp.html")
        self.assertEqual(kwargs["context"]["otp"], "654321")
        self.assertEqual(kwargs["context"]["headline"], "Verify your email")
