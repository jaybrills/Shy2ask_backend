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
        self.assertTrue(user.alias_name)

    def test_user_str(self):
        user = User.objects.create_user(email="test@valid.com", password="password")
        self.assertEqual(str(user), f"{user.alias_name} (test@valid.com)")
        user.alias_name = "Tester"
        user.full_clean()
        self.assertEqual(str(user), "Tester (test@valid.com)")

    def test_alias_is_auto_generated_when_missing(self):
        user = User.objects.create_user(email="generated@valid.com", password="password123")

        self.assertTrue(user.alias_name)
        self.assertRegex(user.alias_name, r"^[A-Za-z]+[A-Za-z]+\d{4}$")

    def test_alias_generation_is_unique(self):
        first = User.objects.create_user(email="first@valid.com", password="password123")
        second = User.objects.create_user(email="second@valid.com", password="password123")

        self.assertNotEqual(first.alias_name.lower(), second.alias_name.lower())

    def test_alias_name_must_be_unique_case_insensitively(self):
        User.objects.create_user(email="first-alias@valid.com", password="password123", alias_name="ShadowComet1234")

        with self.assertRaises(ValidationError) as exc:
            User.objects.create_user(
                email="second-alias@valid.com",
                password="password123",
                alias_name="shadowcomet1234",
            )

        self.assertIn("alias_name", exc.exception.message_dict)

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

    def test_alias_name_cannot_be_shortened_version_of_real_name(self):
        with self.assertRaises(ValidationError) as exc:
            User.objects.create_user(
                email="alias-shortened@valid.com",
                password="password123",
                first_name="Khajan",
                last_name="Smith",
                alias_name="Khaj",
            )

        self.assertIn("alias_name", exc.exception.message_dict)

    def test_alias_name_cannot_be_split_shortened_parts_of_real_name(self):
        with self.assertRaises(ValidationError) as exc:
            User.objects.create_user(
                email="alias-split@valid.com",
                password="password123",
                first_name="Khajan",
                last_name="Singh",
                alias_name="Kha sin",
            )

        self.assertIn("alias_name", exc.exception.message_dict)

    def test_alias_name_cannot_be_compacted_parts_of_real_name(self):
        with self.assertRaises(ValidationError) as exc:
            User.objects.create_user(
                email="alias-compacted@valid.com",
                password="password123",
                first_name="Khajan",
                last_name="Singh",
                alias_name="khasing",
            )

        self.assertIn("alias_name", exc.exception.message_dict)

    def test_alias_name_cannot_use_first_initial_with_last_name(self):
        with self.assertRaises(ValidationError) as exc:
            User.objects.create_user(
                email="alias-initial-last@valid.com",
                password="password123",
                first_name="Khajan",
                last_name="Singh",
                alias_name="ksingh",
            )

        self.assertIn("alias_name", exc.exception.message_dict)

    def test_alias_name_cannot_use_last_initial_with_first_name(self):
        with self.assertRaises(ValidationError) as exc:
            User.objects.create_user(
                email="alias-initial-first@valid.com",
                password="password123",
                first_name="Khajan",
                last_name="Singh",
                alias_name="skhajan",
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
