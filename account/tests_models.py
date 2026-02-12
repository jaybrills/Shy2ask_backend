from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from account.models import User, PasswordResetOTP, EmailVerificationOTP

class UserModelTest(TestCase):
    def test_create_user(self):
        user = User.objects.create_user(
            email="test@example.com",
            password="password123",
            first_name="Test",
            last_name="User"
        )
        self.assertEqual(user.email, "test@example.com")
        self.assertTrue(user.check_password("password123"))
        self.assertEqual(user.get_full_name(), "Test User")
        self.assertFalse(user.is_verified)

    def test_user_str(self):
        user = User.objects.create_user(email="test@example.com", password="password")
        self.assertEqual(str(user), "test@example.com (test@example.com)")
        user.alias_name = "Tester"
        self.assertEqual(str(user), "Tester (test@example.com)")

class OTPModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="password")

    def test_password_reset_otp(self):
        expiry = timezone.now() + timedelta(hours=1)
        otp = PasswordResetOTP.objects.create(
            email="user@example.com",
            otp_code="123456",
            expires_at=expiry
        )
        self.assertEqual(otp.otp_code, "123456")
        self.assertEqual(str(otp), "OTP for user@example.com")

    def test_email_verification_otp(self):
        expiry = timezone.now() + timedelta(hours=1)
        otp = EmailVerificationOTP.objects.create(
            user=self.user,
            otp_code="654321",
            expires_at=expiry
        )
        self.assertEqual(otp.otp_code, "654321")
        self.assertEqual(str(otp), "Verification OTP for user@example.com")
