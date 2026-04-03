from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from account.models import ActiveUser, EmailVerificationOTP, PasswordResetOTP, PendingVerificationUser, User

class UserModelTest(TestCase):
    def test_create_user(self):
        user = User.objects.create_user(
            email="test@valid.com",
            password="password123",
            first_name="Test",
            last_name="User"
        )
        self.assertEqual(user.email, "test@valid.com")
        self.assertTrue(user.check_password("password123"))
        self.assertEqual(user.get_full_name(), "Test User")
        self.assertFalse(user.is_verified)

    def test_user_str(self):
        user = User.objects.create_user(email="test@valid.com", password="password")
        self.assertEqual(str(user), "test@valid.com (test@valid.com)")
        user.alias_name = "Tester"
        self.assertEqual(str(user), "Tester (test@valid.com)")

    def test_user_queryset_helpers_and_proxies(self):
        active_verified = User.objects.create_user(email="active@valid.com", password="password", is_verified=True)
        inactive = User.objects.create_user(email="inactive@valid.com", password="password", is_active=False)
        pending = User.objects.create_user(email="pending@valid.com", password="password", is_verified=False)

        self.assertEqual(User.objects.find_by_email("ACTIVE@valid.com"), active_verified)
        self.assertIn(active_verified, ActiveUser.objects.active())
        self.assertNotIn(inactive, ActiveUser.objects.active())
        self.assertIn(pending, PendingVerificationUser.objects.unverified())

    def test_alias_name_cannot_closely_match_real_name(self):
        with self.assertRaises(ValidationError) as exc:
            User.objects.create_user(
                email="alias-conflict@valid.com",
                password="password123",
                first_name="John",
                last_name="Doe",
                alias_name="Jon Doe",
            )

        self.assertIn("alias_name", exc.exception.message_dict)

class OTPModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="user@valid.com", password="password")

    def test_password_reset_otp(self):
        expiry = timezone.now() + timedelta(hours=1)
        otp = PasswordResetOTP.objects.create(
            email="USER@valid.com",
            otp_code="123456",
            expires_at=expiry
        )
        self.assertEqual(otp.otp_code, "123456")
        self.assertEqual(str(otp), "OTP for user@valid.com")
        self.assertFalse(otp.is_expired)

    def test_email_verification_otp(self):
        expiry = timezone.now() + timedelta(hours=1)
        otp = EmailVerificationOTP.objects.create(
            user=self.user,
            otp_code="654321",
            expires_at=expiry
        )
        self.assertEqual(otp.otp_code, "654321")
        self.assertEqual(str(otp), "Verification OTP for user@valid.com")
